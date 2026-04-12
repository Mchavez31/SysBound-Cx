"""
Raster snippets around tag coordinates (pdfplumber — same coordinate space as extraction).
Falls back to PyMuPDF (MuPDF) or pypdfium2 when pdfplumber’s PDFium raster path fails
(e.g. “Data format error” on some CAD exports).
"""
from __future__ import annotations

from io import BytesIO

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageDraw

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None  # type: ignore[misc, assignment]


def pdf_page_count(pdf_path: str) -> int:
    doc = pdfium.PdfDocument(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


def extract_pdf_pages_bytes(pdf_path: str, page_numbers_one_based: list[int]) -> bytes:
    """Build a PDF containing only the given 1-based page numbers (order preserved)."""
    spec = ",".join(str(n) for n in page_numbers_one_based)
    src = pdfium.PdfDocument(pdf_path)
    dst = None
    try:
        dst = pdfium.PdfDocument.new()
        dst.import_pages(src, spec)
        out = BytesIO()
        dst.save(out)
        return out.getvalue()
    finally:
        src.close()
        if dst is not None:
            dst.close()


def _draw_tag_marker(
    pil: Image.Image,
    *,
    crop_x0: float,
    crop_top: float,
    crop_x1: float,
    crop_bottom: float,
    cx: float,
    cy: float,
) -> None:
    cw = max(crop_x1 - crop_x0, 1e-6)
    ch = max(crop_bottom - crop_top, 1e-6)
    pw, ph = pil.size
    px_cx = (float(cx) - crop_x0) * (pw / cw)
    px_cy = (float(cy) - crop_top) * (ph / ch)
    scale = min(pw / cw, ph / ch)
    half = max(12.0, 38.0 * scale)
    pad = max(2.0, scale * 3)
    lw = max(3, min(pw, ph) // 180)
    draw = ImageDraw.Draw(pil)
    draw.rectangle(
        [px_cx - half - pad, px_cy - half - pad, px_cx + half + pad, px_cy + half + pad],
        outline="#ff0000",
        width=lw,
    )


def _render_snippet_pypdfium2(
    pdf_path: str,
    page_index_0: int,
    *,
    w: float,
    h: float,
    x0: float,
    top: float,
    x1: float,
    bottom: float,
    res: int,
    did_crop: bool,
    cx: float | None,
    cy: float | None,
) -> bytes:
    doc = pdfium.PdfDocument(pdf_path)
    try:
        page = doc[page_index_0]
        scale = res / 72.0
        bitmap = page.render(scale=scale)
        pil_full = bitmap.to_pil()
        pw, ph = pil_full.size
        left = max(0, min(pw - 1, int(x0 / w * pw)))
        upper = max(0, min(ph - 1, int(top / h * ph)))
        right = max(left + 1, min(pw, int(x1 / w * pw)))
        lower = max(upper + 1, min(ph, int(bottom / h * ph)))
        pil = pil_full.crop((left, upper, right, lower))
        if did_crop and cx is not None and cy is not None:
            _draw_tag_marker(pil, crop_x0=x0, crop_top=top, crop_x1=x1, crop_bottom=bottom, cx=cx, cy=cy)
        buf = BytesIO()
        pil.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        doc.close()


def _render_snippet_pymupdf(
    pdf_path: str,
    page_index_0: int,
    *,
    w: float,
    h: float,
    x0: float,
    top: float,
    x1: float,
    bottom: float,
    res: int,
    did_crop: bool,
    cx: float | None,
    cy: float | None,
) -> bytes:
    if fitz is None:
        raise RuntimeError("PyMuPDF is not installed")
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_index_0]
        zoom = res / 72.0
        mat = fitz.Matrix(zoom, zoom)
        if did_crop:
            clip = fitz.Rect(x0, top, x1, bottom)
            pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
        else:
            pix = page.get_pixmap(matrix=mat, alpha=False)
        pil = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        if did_crop and cx is not None and cy is not None:
            _draw_tag_marker(pil, crop_x0=x0, crop_top=top, crop_x1=x1, crop_bottom=bottom, cx=cx, cy=cy)
        buf = BytesIO()
        pil.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        doc.close()


def render_tag_snippet_png(
    pdf_path: str,
    page_num: int,
    cx: float | None = None,
    cy: float | None = None,
    *,
    margin_pt: float = 150.0,
    resolution_crop: int = 260,
    resolution_full_page: int = 112,
) -> bytes:
    """
    Return PNG bytes: crop around (cx, cy) when both set; otherwise whole page at lower resolution.
    Coordinates match pdfplumber word space (origin top-left, y downward).
    """
    with pdfplumber.open(pdf_path) as pdf:
        if page_num < 1 or page_num > len(pdf.pages):
            raise ValueError(f"page {page_num} out of range (1–{len(pdf.pages)})")
        page = pdf.pages[page_num - 1]
        w, h = float(page.width), float(page.height)

        x0 = top = x1 = bottom = 0.0
        did_crop = False
        if cx is not None and cy is not None:
            m = max(40.0, min(margin_pt, 320.0))
            x0 = max(0.0, float(cx) - m)
            x1 = min(w, float(cx) + m)
            top = max(0.0, float(cy) - m)
            bottom = min(h, float(cy) + m)
            if x1 - x0 < 36:
                x0, x1 = max(0.0, float(cx) - m * 1.5), min(w, float(cx) + m * 1.5)
            if bottom - top < 36:
                top, bottom = max(0.0, float(cy) - m * 1.5), min(h, float(cy) + m * 1.5)
            crop = page.within_bbox((x0, top, x1, bottom))
            res = resolution_crop
            did_crop = True
        else:
            crop = page
            x0, top, x1, bottom = 0.0, 0.0, w, h
            long_side = max(w, h)
            res = resolution_full_page
            if long_side > 0:
                px_long = long_side * (res / 72)
                if px_long > 2400:
                    res = max(72, int(2400 * 72 / long_side))

        page_index_0 = page_num - 1
        fallback_kw = dict(
            w=w,
            h=h,
            x0=x0,
            top=top,
            x1=x1,
            bottom=bottom,
            res=res,
            did_crop=did_crop,
            cx=cx,
            cy=cy,
        )

        try:
            img = crop.to_image(resolution=res)
        except Exception:
            if fitz is not None:
                try:
                    return _render_snippet_pymupdf(pdf_path, page_index_0, **fallback_kw)
                except Exception:
                    pass
            return _render_snippet_pypdfium2(pdf_path, page_index_0, **fallback_kw)

        pil = getattr(img, "original", None)
        if pil is None:
            buf = BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        if did_crop and cx is not None and cy is not None:
            _draw_tag_marker(
                pil,
                crop_x0=x0,
                crop_top=top,
                crop_x1=x1,
                crop_bottom=bottom,
                cx=cx,
                cy=cy,
            )
        buf = BytesIO()
        pil.save(buf, format="PNG")
        return buf.getvalue()
