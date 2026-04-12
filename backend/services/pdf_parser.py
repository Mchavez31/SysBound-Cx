"""
PDF extraction for drawing metadata, tags, and subsystem labels (pdfplumber).
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional

import pdfplumber

# Primary: cap digit run and suffix length to avoid merged / garbage strings from wide word windows
TAG_RE_PRIMARY = re.compile(r"\b[A-Z]{1,5}-[0-9]{4,8}[A-Z0-9]{0,4}\b")
TAG_RE_X = re.compile(r"\b[A-Z]{1,5}-[0-9A-Z]{0,6}X{2,}[0-9A-Z]{0,6}\b")
# Space between prefix and digits (common on systemized P&IDs)
TAG_RE_SPACE = re.compile(r"\b([A-Z]{1,5})\s+([0-9]{4,8}[A-Z0-9]{0,4})\b")
# Joined without separator — only safe on short windows (applied with extra guards)
TAG_RE_JOINED = re.compile(r"\b([A-Z]{2,5})([0-9]{4,8}[A-Z0-9]{0,4})\b")

SUBSYSTEM_LABEL_TEXT_RE = re.compile(r"\b(\d{2}-\d{2})\b")

# Drawing number pattern (long dashed codes)
DRAWING_NUM_RE = re.compile(
    r"\b([A-Z]{3,5}-[A-Z0-9]{2,5}-[A-Z]{3}-[A-Z]{3,4}-[A-Z]{3}-[0-9]{5}-[A-Z0-9]{2,}-[0-9]{2,})\b",
    re.IGNORECASE,
)

PLANT_PREFIX_MAP = [
    (re.compile(r"WILG", re.I), "WCF"),
    (re.compile(r"WWOC", re.I), "WOC"),
    (re.compile(r"BT10", re.I), "BT1"),
    (re.compile(r"BT20", re.I), "BT2"),
    (re.compile(r"BT30", re.I), "BT3"),
    (re.compile(r"WKPD", re.I), "KPAD"),
]

def _env_workers(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return max(lo, min(hi, default))
    try:
        return max(lo, min(hi, int(raw)))
    except ValueError:
        return max(lo, min(hi, default))


# Parallel page chunks (each chunk opens the PDF once). Default 4; cap to limit RAM with huge PDFs.
_w = _env_workers("PDF_EXTRACT_WORKERS", 4, 2, 12)
_MAX_TAG_WORKERS = _w
_MAX_LABEL_WORKERS = _w
_MAX_COMBINED_WORKERS = _w

# Avoid TAG_RE_JOINED false positives on common English / title words
_SKIP_JOINED_PREFIX = {
    "THE", "AND", "FOR", "NOT", "ARE", "ALL", "CAN", "HAS", "SHE", "BUT", "OUT", "USE",
    "MAY", "ONE", "TWO", "THAT", "THIS", "WITH", "FROM", "WAS", "WERE", "BEEN", "HAVE",
    "WILL", "EACH", "WHICH", "THEIR", "SAFETY", "NOTE", "REFER", "DRAWING", "SCALE",
    "SHEET", "REV", "DATE", "PROJECT", "SYSTEM", "AREA", "ZONE", "LINE", "SIZE",
    "MODULE", "NOTES", "GENERAL", "DETAIL", "DETAILS", "NORTH", "SOUTH", "EAST", "WEST",
}


def _infer_plant_from_drawing_number(dn: str) -> str | None:
    if not dn:
        return None
    u = dn.upper()
    for rx, plant in PLANT_PREFIX_MAP:
        if rx.search(u):
            return plant
    return None


def _infer_drawing_type(text: str) -> str | None:
    t = text.upper()
    if "PIPING AND INSTRUMENTATION" in t or "P&ID" in t or "P&ID" in text:
        return "P&ID"
    if "ONE LINE" in t or "SINGLE LINE" in t or "ONE-LINE" in t:
        return "SLD"
    if "PROCESS FLOW" in t or re.search(r"\bPFD\b", t):
        return "PFD"
    if "PANEL SCHEDULE" in t:
        return "Panel Schedule"
    if ("CABLE BLOCK" in t or "BLOCK DIAGRAM" in t) and "INSTRUMENT" in t:
        return "Automation"
    if "NETWORK" in t or "TELECOM" in t or "ARCHITECTURE" in t:
        return "Telecom"
    return None


def _extract_revision(text: str) -> str | None:
    m = re.search(r"\bREV\.?\s*([0-9]{1,2})\b", text, re.I)
    if m:
        return m.group(1)
    m = re.search(r"\bREVISION\s*([0-9]{1,2})\b", text, re.I)
    if m:
        return m.group(1)
    return None


def normalize_tag_number(raw: str) -> str:
    """Canonical form PREFIX-DIGITS for dedupe and comparison."""
    t = re.sub(r"\s+", "-", raw.strip().upper())
    while "--" in t:
        t = t.replace("--", "-")
    return t


# Willow spec: single-letter mechanical equipment may use longer numeric fields;
# instruments, manual valves, and piping line numbers use a 7-digit block (§6.2, 6.3, 6.9).
_EQUIP_SINGLE_LETTER_MAX_DIGITS = frozenset("PTVSUECXAMK")


def is_plausible_tag_number(tn: str) -> bool:
    """
    Reject merged OCR-style garbage: long digit runs, repeated acronyms (MV-9580056MV),
    doubled number blocks (95800289580028), long alpha tails (DRAINHEADER).
    """
    n = normalize_tag_number(tn)
    if len(n) < 5 or len(n) > 20:
        return False
    if re.search(r"X{2,}", n):
        return bool(re.match(r"^[A-Z]{1,5}-[0-9A-Z]{2,14}$", n)) and len(n) <= 18
    m = re.match(r"^([A-Z]{1,5})-([0-9]{4,10})([A-Z0-9]*)$", n)
    if not m:
        return False
    pref, nums, suff = m.group(1), m.group(2), (m.group(3) or "").upper()
    if len(pref) == 1 and pref in _EQUIP_SINGLE_LETTER_MAX_DIGITS:
        max_digits = 10
    else:
        max_digits = 7
    if len(nums) > max_digits:
        return False
    # Repeated digit block (e.g. 95800289580028)
    for L in range(4, min(len(nums) // 2 + 1, 9)):
        if nums[:L] == nums[L : L * 2]:
            return False
    # Suffix repeats tag prefix (MV-9580056MV)
    if suff == pref:
        return False
    # Long word-like suffix glued to tag (U-57850DRAINHEADER)
    if len(suff) >= 5 and suff.isalpha():
        return False
    if len(suff) > 4:
        return False
    # Same acronym appears twice (…DFCS…DFCS)
    rest = n[len(pref) + 1 :]
    if pref in rest:
        return False
    return True


def classify_tag_category(tag_number: str) -> str:
    norm = normalize_tag_number(tag_number)
    prefix = norm.split("-")[0].upper() if "-" in norm else norm[:3].upper()
    valve_prefixes = {"MV", "XV", "SDV", "HV", "LV", "FV", "PV", "TV", "CV", "BDV", "PCV"}
    inst_prefixes = {
        "FI", "FIT", "PI", "PIT", "TI", "TIT", "LI", "LIT", "AI", "AIC", "PDI", "FIC", "PIC",
        "ZIO", "ZIC", "ZSC", "ZSO", "HS", "PT", "PDT", "ZS", "ZSH",
    }
    equip_prefixes = {"P", "T", "V", "S", "E", "C", "U", "X", "A", "M", "K"}
    if prefix in valve_prefixes:
        return "valve"
    if prefix in inst_prefixes:
        return "instrument"
    if len(prefix) <= 2 and prefix in equip_prefixes:
        return "equipment"
    if re.match(r"^[A-Z]{2,4}$", prefix) and len(tag_number) > 6:
        return "line"
    return "other"


def _norm_rgb_component(v: float) -> float:
    return v / 255.0 if v > 1.0 else v


def _hex_from_rgb_fill(r: float, g: float, b: float) -> str:
    r, g, b = _norm_rgb_component(r), _norm_rgb_component(g), _norm_rgb_component(b)

    def _byte(x: float) -> int:
        return max(0, min(255, int(round(x * 255)) if x <= 1 else int(round(x))))

    return f"#{_byte(r):02X}{_byte(g):02X}{_byte(b):02X}"


def _hex_from_rgb(r: float, g: float, b: float) -> str:
    def _c(x: float) -> int:
        return max(0, min(255, int(round(x * 255)) if x <= 1 else int(round(x))))

    if r <= 1 and g <= 1 and b <= 1:
        return f"#{_c(r):02x}{_c(g):02x}{_c(b):02x}"
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def _hex_to_rgb_ints(h: str | None) -> tuple[int, int, int] | None:
    """Parse #RRGGBB (any case) to 0–255 RGB."""
    if not h or not isinstance(h, str):
        return None
    s = h.strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def _color_distance_hex(h1: str | None, h2: str | None) -> float:
    """Euclidean distance in RGB 0–255; large value if either color missing."""
    a = _hex_to_rgb_ints(h1)
    b = _hex_to_rgb_ints(h2)
    if not a or not b:
        return 1e9
    return math.sqrt(float((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2))


def _chunk_ranges(n: int, workers: int) -> list[tuple[int, int]]:
    if n <= 0:
        return []
    workers = max(1, min(workers, n))
    size = (n + workers - 1) // workers
    return [(i, min(i + size, n)) for i in range(0, n, size)]


def _flatten_chars(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _tag_in_window(tn: str, chunk: str, chunk_spaced: str) -> bool:
    """Whether tag tn is supported by this word window (hyphen or space forms)."""
    flat = _flatten_chars(tn)
    if flat and (flat in _flatten_chars(chunk) or flat in _flatten_chars(chunk_spaced)):
        return True
    return tn in chunk or tn in chunk.replace(" ", "") or tn.replace("-", " ") in chunk_spaced


def _bbox_for_chunk_span(
    sub: list[dict[str, Any]], chunk: str, c0: int, c1: int
) -> tuple[float, float, float, float]:
    """Map character span [c0, c1) in chunk (concatenated word texts, no separators) to bbox."""
    pos = 0
    covering: list[dict[str, Any]] = []
    for w in sub:
        t = w.get("text", "") or ""
        wl = len(t)
        ws, we = pos, pos + wl
        if we > c0 and ws < c1:
            covering.append(w)
        pos += wl
    if not covering:
        covering = sub
    x0 = min(float(w["x0"]) for w in covering)
    x1 = max(float(w["x1"]) for w in covering)
    top = min(float(w["top"]) for w in covering)
    bottom = max(float(w["bottom"]) for w in covering)
    return x0, x1, top, bottom


def _bbox_for_chunk_spaced_span(
    sub: list[dict[str, Any]], chunk_spaced: str, c0: int, c1: int
) -> tuple[float, float, float, float]:
    """Map character span in chunk_spaced (= ' '.join(word texts)) to bbox."""
    pos = 0
    covering: list[dict[str, Any]] = []
    for idx, w in enumerate(sub):
        if idx > 0:
            pos += 1  # single space between words
        t = w.get("text", "") or ""
        ws, we = pos, pos + len(t)
        if we > c0 and ws < c1:
            covering.append(w)
        pos = we
    if not covering:
        covering = sub
    x0 = min(float(w["x0"]) for w in covering)
    x1 = max(float(w["x1"]) for w in covering)
    top = min(float(w["top"]) for w in covering)
    bottom = max(float(w["bottom"]) for w in covering)
    return x0, x1, top, bottom


def _tags_from_page(page: Any, page_num: int) -> list[dict[str, Any]]:
    words = page.extract_words() or []
    if not words:
        return []
    lines: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for w in words:
        key = round(float(w["top"]), 1)
        lines[key].append(w)
    found: dict[str, dict[str, Any]] = {}
    for rk in sorted(lines.keys()):
        lw = sorted(lines[rk], key=lambda w: float(w["x0"]))
        n = len(lw)
        for i in range(n):
            for j in range(i, min(n, i + 18)):
                sub = lw[i : j + 1]
                chunk = "".join(w.get("text", "") for w in sub)
                chunk_spaced = " ".join(w.get("text", "") for w in sub)
                # (tag_number, bbox) — bbox from the matched substring only, not the whole window
                candidates: list[tuple[str, tuple[float, float, float, float]]] = []
                for rx in (TAG_RE_PRIMARY, TAG_RE_X):
                    for m in rx.finditer(chunk):
                        tn = normalize_tag_number(m.group(0))
                        bb = _bbox_for_chunk_span(sub, chunk, m.start(), m.end())
                        candidates.append((tn, bb))
                for m in TAG_RE_SPACE.finditer(chunk_spaced):
                    tn = normalize_tag_number(f"{m.group(1)}-{m.group(2)}")
                    bb = _bbox_for_chunk_spaced_span(sub, chunk_spaced, m.start(), m.end())
                    candidates.append((tn, bb))
                # Joined tags only from tight windows (avoids DFCS95800…95800…DFCS merges)
                if j - i <= 4 and len(chunk) <= 16:
                    for m in TAG_RE_JOINED.finditer(chunk):
                        p1, p2 = m.group(1).upper(), m.group(2)
                        if len(p1) < 2 or len(p1) > 5 or p1 in _SKIP_JOINED_PREFIX:
                            continue
                        if len(p1 + p2) < 8:
                            continue
                        tn = normalize_tag_number(f"{p1}-{p2}")
                        bb = _bbox_for_chunk_span(sub, chunk, m.start(), m.end())
                        candidates.append((tn, bb))
                for tn, bb in candidates:
                    if tn in found:
                        continue
                    if not is_plausible_tag_number(tn):
                        continue
                    if not _tag_in_window(tn, chunk, chunk_spaced):
                        continue
                    x0, x1, top, bottom = bb
                    pw, ph = float(page.width), float(page.height)
                    found[tn] = {
                        "tag_number": tn,
                        "page_number": page_num,
                        "x": (x0 + x1) / 2,
                        "y": (top + bottom) / 2,
                        "page_width": pw,
                        "page_height": ph,
                        "tag_type": classify_tag_category(tn),
                        "is_x_tag": bool(TAG_RE_X.search(tn)) or ("XX" in tn and re.search(r"X{2,}", tn)),
                    }
    return list(found.values())


def _extract_tags_page_range(pdf_path: str, start: int, end: int) -> list[dict[str, Any]]:
    acc: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx in range(start, end):
            acc.extend(_tags_from_page(pdf.pages[idx], idx + 1))
    return acc


def extract_tags(pdf_path: str) -> list[dict[str, Any]]:
    """
    Extract instrument/equipment tag numbers from every page (parallel page chunks).
    Deduplicates by tag_number — first occurrence in page order wins.
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            n = len(pdf.pages)
        if n == 0:
            return []
        chunks = _chunk_ranges(n, _MAX_TAG_WORKERS)
        flat: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=len(chunks)) as ex:
            futs = [ex.submit(_extract_tags_page_range, pdf_path, a, b) for a, b in chunks]
            for fut in as_completed(futs):
                flat.extend(fut.result())
        flat.sort(key=lambda t: (t["page_number"], t.get("y") or 0, t.get("x") or 0))
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for t in flat:
            tn = t["tag_number"]
            if tn in seen:
                continue
            seen.add(tn)
            unique.append(t)
        return unique
    except Exception:
        return []


def _point_in_rect(px: float, py: float, rect: dict[str, Any]) -> bool:
    try:
        x0, x1 = float(rect["x0"]), float(rect["x1"])
        top, bottom = float(rect["top"]), float(rect["bottom"])
    except (KeyError, TypeError, ValueError):
        return False
    return x0 <= px <= x1 and top <= py <= bottom


def _colored_rect_candidates(page: Any) -> list[dict[str, Any]]:
    """Rects with a non-white/non-black fill — built once per page for repeated point queries."""
    out: list[dict[str, Any]] = []
    for rect in page.rects or []:
        fill = rect.get("fill") or rect.get("non_stroking_color")
        if not fill or not isinstance(fill, (list, tuple)) or len(fill) < 3:
            continue
        r, g, b = float(fill[0]), float(fill[1]), float(fill[2])
        r, g, b = _norm_rgb_component(r), _norm_rgb_component(g), _norm_rgb_component(b)
        if r > 0.95 and g > 0.95 and b > 0.95:
            continue
        if r < 0.05 and g < 0.05 and b < 0.05:
            continue
        try:
            x0, x1 = float(rect["x0"]), float(rect["x1"])
            top, bottom = float(rect["top"]), float(rect["bottom"])
        except (KeyError, TypeError, ValueError):
            continue
        w, h = abs(x1 - x0), abs(bottom - top)
        if w > 520 or h > 160 or w < 2 or h < 2:
            continue
        out.append(rect)
    return out


def _smallest_colored_rect_covering_point(
    page: Any,
    px: float,
    py: float,
    *,
    max_w: float = 520,
    max_h: float = 160,
    rects: list[dict[str, Any]] | None = None,
) -> tuple[str | None, float | None]:
    """Find smallest non-white rect containing (px,py); return (hex, area)."""
    best_hex: str | None = None
    best_area = 1e18
    rect_iter = rects if rects is not None else (page.rects or [])
    for rect in rect_iter:
        fill = rect.get("fill") or rect.get("non_stroking_color")
        if not fill or not isinstance(fill, (list, tuple)) or len(fill) < 3:
            continue
        r, g, b = float(fill[0]), float(fill[1]), float(fill[2])
        r, g, b = _norm_rgb_component(r), _norm_rgb_component(g), _norm_rgb_component(b)
        if r > 0.95 and g > 0.95 and b > 0.95:
            continue
        if r < 0.05 and g < 0.05 and b < 0.05:
            continue
        try:
            x0, x1 = float(rect["x0"]), float(rect["x1"])
            top, bottom = float(rect["top"]), float(rect["bottom"])
        except (KeyError, TypeError, ValueError):
            continue
        w, h = abs(x1 - x0), abs(bottom - top)
        if w > max_w or h > max_h or w < 2 or h < 2:
            continue
        if not _point_in_rect(px, py, rect):
            continue
        area = w * h
        if area < best_area:
            best_area = area
            best_hex = _hex_from_rgb_fill(float(fill[0]), float(fill[1]), float(fill[2]))
    return best_hex, best_area if best_hex else None


def _is_likely_markup_red(hx: str | None) -> bool:
    """Bright red often used for manual review / highlighted tag text, not subsystem equipment color."""
    t = _hex_to_rgb_ints(hx)
    if not t:
        return False
    r, g, b = t
    return r >= 185 and g <= 100 and b <= 100 and r > g + 60 and r > b + 60


def _stroke_hex_from_line_like(obj: dict[str, Any]) -> str | None:
    """Stroke color from a pdfplumber line or curve dict."""
    for key in ("stroking_color", "non_stroking_color", "stroke"):
        c = obj.get(key)
        if isinstance(c, (list, tuple)) and len(c) >= 3:
            r, g, b = float(c[0]), float(c[1]), float(c[2])
            r, g, b = _norm_rgb_component(r), _norm_rgb_component(g), _norm_rgb_component(b)
            if r > 0.95 and g > 0.95 and b > 0.95:
                continue
            if r < 0.05 and g < 0.05 and b < 0.05:
                continue
            return _hex_from_rgb_fill(float(c[0]), float(c[1]), float(c[2]))
    return None


def _line_bbox_center_dist(px: float, py: float, ln: dict[str, Any]) -> float | None:
    try:
        x0, x1 = float(ln["x0"]), float(ln["x1"])
        top, bottom = float(ln["top"]), float(ln["bottom"])
    except (KeyError, TypeError, ValueError):
        return None
    mx, my = (x0 + x1) / 2, (top + bottom) / 2
    return math.hypot(px - mx, py - my)


def _line_stroke_colors_near(page: Any, px: float, py: float, max_dist: float = 130.0) -> list[str]:
    out: list[str] = []
    for ln in page.lines or []:
        d = _line_bbox_center_dist(px, py, ln)
        if d is None or d > max_dist:
            continue
        hx = _stroke_hex_from_line_like(ln)
        if hx:
            out.append(hx)
    for cr in page.curves or []:
        d = _line_bbox_center_dist(px, py, cr)
        if d is None or d > max_dist:
            continue
        hx = _stroke_hex_from_line_like(cr)
        if hx:
            out.append(hx)
    return out


def infer_subsystem_linking_color(
    page: Any,
    tx: float,
    ty: float,
    *,
    rects: list[dict[str, Any]] | None = None,
) -> str | None:
    """
    Best-effort color to match subsystem bubbles against.

    PDFs do not expose every pixel — only vector paths. We combine:
    - Fills from rects sampled *around* the tag (valve body / piping / equipment), not only on the tag text
    - Stroke colors from lines/curves near the tag (often the actual valve outline / process line)

    Manual review often colors **tag text** red; that is de-prioritized when other samples disagree.
    """
    tx, ty = float(tx), float(ty)
    offset_samples: list[str] = []
    # Away from the tag centroid — tends to hit equipment rather than a red text box
    for dx, dy in (
        (-64, 0),
        (64, 0),
        (0, 54),
        (0, -50),
        (-50, 34),
        (50, 34),
        (-54, -30),
        (54, -30),
        (-38, 42),
        (38, 42),
    ):
        hx, _ = _smallest_colored_rect_covering_point(page, tx + dx, ty + dy, rects=rects)
        if hx:
            offset_samples.append(hx)
    line_colors = _line_stroke_colors_near(page, tx, ty, 140.0)
    center_hex, _ = _smallest_colored_rect_covering_point(page, tx, ty, rects=rects)

    pool = offset_samples + line_colors
    non_markup = [h for h in pool if not _is_likely_markup_red(h)]
    if non_markup:
        return Counter(non_markup).most_common(1)[0][0]
    if pool:
        return Counter(pool).most_common(1)[0][0]
    if center_hex and not _is_likely_markup_red(center_hex):
        return center_hex
    if center_hex:
        return center_hex
    return None


def _labels_from_page(page: Any, page_num: int) -> list[dict[str, Any]]:
    """
    Subsystem label boxes: small colored rects with NN-MM text.
    Also picks up NN-MM as plain words inside a colored rect (white text on purple/green box).
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, str, int, int]] = set()

    def _add(
        sub: str,
        hx: str,
        cx: float,
        cy: float,
        w: float,
        h: float,
    ) -> None:
        key = (page_num, sub, int(cx // 25), int(cy // 25))
        if key in seen:
            return
        seen.add(key)
        out.append(
            {
                "subsystem_number": sub,
                "hex_color": hx,
                "x": cx,
                "y": cy,
                "page_number": page_num,
                "width": w,
                "height": h,
            }
        )

    for rect in page.rects or []:
        fill = rect.get("fill") or rect.get("non_stroking_color")
        if not fill or not isinstance(fill, (list, tuple)) or len(fill) < 3:
            continue
        r, g, b = float(fill[0]), float(fill[1]), float(fill[2])
        r, g, b = _norm_rgb_component(r), _norm_rgb_component(g), _norm_rgb_component(b)
        if r > 0.95 and g > 0.95 and b > 0.95:
            continue
        if r < 0.05 and g < 0.05 and b < 0.05:
            continue
        try:
            x0, x1 = float(rect["x0"]), float(rect["x1"])
            top, bottom = float(rect["top"]), float(rect["bottom"])
        except (KeyError, TypeError, ValueError):
            continue
        w = abs(x1 - x0)
        h = abs(bottom - top)
        # Skip huge highlight regions (whole drawing areas); allow wide strip labels at line ends
        if w > 520 or h > 160:
            continue
        if w < 2 or h < 3:
            continue
        hex_color = _hex_from_rgb_fill(float(fill[0]), float(fill[1]), float(fill[2]))
        try:
            cropped = page.within_bbox((x0, top, x1, bottom))
            ttext = cropped.extract_text() or ""
            words = cropped.extract_words() or []
        except Exception:
            continue
        combined = "".join(w.get("text", "") for w in words) if words else ttext.replace(" ", "")
        m = SUBSYSTEM_LABEL_TEXT_RE.search(combined) or SUBSYSTEM_LABEL_TEXT_RE.search(ttext.replace(" ", ""))
        if not m:
            continue
        sub = m.group(1)
        cx = (x0 + x1) / 2
        cy = (top + bottom) / 2
        _add(sub, hex_color, cx, cy, w, h)

    # Word-based: "95-02" drawn as text (often white) on top of a colored rect — rects list may omit fill
    for wobj in page.extract_words() or []:
        raw = (wobj.get("text") or "").strip().replace("\u00a0", " ")
        compact = re.sub(r"\s+", "", raw)
        if not re.match(r"^\d{2}-\d{2}$", compact):
            continue
        sub = compact
        try:
            wx0, wx1 = float(wobj["x0"]), float(wobj["x1"])
            wtop, wbot = float(wobj["top"]), float(wobj["bottom"])
        except (KeyError, TypeError, ValueError):
            continue
        cx = (wx0 + wx1) / 2
        cy = (wtop + wbot) / 2
        ww, wh = abs(wx1 - wx0), abs(wbot - wtop)
        hx, _ = _smallest_colored_rect_covering_point(page, cx, cy)
        if hx:
            _add(sub, hx, cx, cy, max(ww, 12), max(wh, 8))

    return out


def _extract_labels_page_range(pdf_path: str, start: int, end: int) -> list[dict[str, Any]]:
    acc: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx in range(start, end):
            acc.extend(_labels_from_page(pdf.pages[idx], idx + 1))
    return acc


def _extract_combined_page_range(pdf_path: str, start: int, end: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One pdfplumber.open per chunk: tags + subsystem labels (half the I/O of two separate passes)."""
    tags_acc: list[dict[str, Any]] = []
    labels_acc: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx in range(start, end):
            page = pdf.pages[idx]
            pnum = idx + 1
            colored_rects = _colored_rect_candidates(page)
            page_tags = _tags_from_page(page, pnum)
            for t in page_tags:
                tx, ty = t.get("x"), t.get("y")
                if tx is not None and ty is not None:
                    hx = infer_subsystem_linking_color(page, float(tx), float(ty), rects=colored_rects)
                    if hx:
                        t["tag_fill_color"] = hx
            tags_acc.extend(page_tags)
            labels_acc.extend(_labels_from_page(page, pnum))
    return tags_acc, labels_acc


def extract_subsystem_labels(pdf_path: str) -> list[dict[str, Any]]:
    """
    Scan every page for small colored rects containing a subsystem label (NN-MM).
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            n = len(pdf.pages)
        if n == 0:
            return []
        chunks = _chunk_ranges(n, _MAX_LABEL_WORKERS)
        flat: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=len(chunks)) as ex:
            futs = [ex.submit(_extract_labels_page_range, pdf_path, a, b) for a, b in chunks]
            for fut in as_completed(futs):
                flat.extend(fut.result())
        return flat
    except Exception:
        return []


def enrich_tags_with_subsystems(
    tags: list[dict[str, Any]],
    subsystem_labels: list[dict[str, Any]],
    *,
    max_distance: float = 500.0,
) -> list[dict[str, Any]]:
    """
    Link each tag to a subsystem bubble (NN-MM).

    When ``tag_fill_color`` is present (see ``infer_subsystem_linking_color``: offsets +
    line strokes; avoids tag-text-only markup reds), we **prefer matching subsystem labels by color** among
    candidates near the tag, then break ties by distance. This avoids wrong subsystem
    when several bubbles are nearby but only one matches the tag/equipment color.

    Without a tag color, behavior falls back to nearest label within ``max_distance``.
    """
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for lab in subsystem_labels:
        by_page[int(lab["page_number"])].append(lab)

    def _spatial(tx: float, ty: float, lab: dict[str, Any]) -> float:
        lx, ly = float(lab["x"]), float(lab["y"])
        return math.hypot(tx - lx, ty - ly)

    enriched: list[dict[str, Any]] = []
    for tag in tags:
        t = dict(tag)
        pn = int(t.get("page_number") or 1)
        tx, ty = t.get("x"), t.get("y")
        tag_hex = t.get("tag_fill_color")
        labels = by_page.get(pn, [])
        nearest_sub = None
        nearest_color = None
        nearest_dist = None
        if tx is not None and ty is not None and labels:
            txf, tyf = float(tx), float(ty)
            nearby = [lab for lab in labels if _spatial(txf, tyf, lab) <= max_distance]
            # Prefer labels near the tag; if none in range, still allow matching by color on the whole page.
            pool = nearby if nearby else list(labels)

            best_lab: dict[str, Any] | None = None
            best_key: tuple[float, float] | None = None

            if tag_hex:
                for lab in pool:
                    cd = _color_distance_hex(tag_hex, lab.get("hex_color"))
                    sd = _spatial(txf, tyf, lab)
                    key = (cd, sd)
                    if best_key is None or key < best_key:
                        best_key = key
                        best_lab = lab
            else:
                best_d = 1e18
                for lab in labels:
                    sd = _spatial(txf, tyf, lab)
                    if sd < best_d:
                        best_d = sd
                        best_lab = lab
                if best_lab is not None and best_d > max_distance:
                    best_lab = None
                    best_d = None
                nearest_dist = best_d

            if best_lab is not None:
                nearest_sub = best_lab["subsystem_number"]
                nearest_color = best_lab["hex_color"]
                if nearest_dist is None:
                    nearest_dist = _spatial(txf, tyf, best_lab)
        t["nearest_subsystem"] = nearest_sub
        t["nearest_subsystem_color"] = nearest_color
        t["nearest_subsystem_distance"] = nearest_dist
        enriched.append(t)
    return enriched


def extract_all(
    pdf_path: str,
    *,
    progress_cb: Optional[Callable[[int, str], None]] = None,
    progress_lo: int = 4,
    progress_hi: int = 16,
    progress_label: str = "Reading PDF",
) -> dict[str, Any]:
    """
    Single combined pass over the PDF (parallel chunks) for tags + labels.
    Faster and more stable than calling extract_tags + extract_subsystem_labels separately.

    Optional ``progress_cb`` reports incremental percent while chunks finish (large PDFs can take minutes).
    """
    with pdfplumber.open(pdf_path) as pdf:
        n = len(pdf.pages)
    if n == 0:
        return {
            "tags": [],
            "subsystem_labels": [],
            "tag_count": 0,
            "label_count": 0,
            "subsystems_found": [],
        }
    chunks = _chunk_ranges(n, _MAX_COMBINED_WORKERS)
    nchunks = len(chunks)
    if progress_cb:
        progress_cb(progress_lo, f"{progress_label}: scanning {n} page(s) in {nchunks} part(s)…")
    tags_flat: list[dict[str, Any]] = []
    labels_flat: list[dict[str, Any]] = []
    done = 0
    span = max(1, progress_hi - progress_lo)
    with ThreadPoolExecutor(max_workers=nchunks) as ex:
        futs = [ex.submit(_extract_combined_page_range, pdf_path, a, b) for a, b in chunks]
        for fut in as_completed(futs):
            tpart, lpart = fut.result()
            tags_flat.extend(tpart)
            labels_flat.extend(lpart)
            done += 1
            if progress_cb and nchunks > 0:
                p = progress_lo + int(span * done / nchunks)
                progress_cb(min(99, p), f"{progress_label}: finished part {done}/{nchunks}…")
    tags_flat.sort(key=lambda t: (t["page_number"], t.get("y") or 0, t.get("x") or 0))
    seen: set[str] = set()
    unique_tags: list[dict[str, Any]] = []
    for t in tags_flat:
        tn = t["tag_number"]
        if tn in seen:
            continue
        seen.add(tn)
        unique_tags.append(t)
    subs = sorted({str(l["subsystem_number"]) for l in labels_flat if l.get("subsystem_number")})
    enriched = enrich_tags_with_subsystems(unique_tags, labels_flat)
    return {
        "tags": enriched,
        "subsystem_labels": labels_flat,
        "tag_count": len(unique_tags),
        "label_count": len(labels_flat),
        "subsystems_found": subs,
    }


def _debug_sample_tags(tags: list[dict[str, Any]], n: int = 5) -> list[dict[str, Any]]:
    out = []
    for t in tags[:n]:
        out.append(
            {
                "tag_number": t.get("tag_number"),
                "page_number": t.get("page_number"),
                "tag_fill_color": t.get("tag_fill_color"),
                "nearest_subsystem": t.get("nearest_subsystem"),
                "nearest_subsystem_color": t.get("nearest_subsystem_color"),
                "nearest_subsystem_distance": t.get("nearest_subsystem_distance"),
            }
        )
    return out


def build_extraction_debug(result: dict[str, Any]) -> dict[str, Any]:
    tags = result.get("tags") or []
    return {
        "total_tags_extracted": result.get("tag_count", 0),
        "total_labels_extracted": result.get("label_count", 0),
        "subsystems_found": result.get("subsystems_found") or [],
        "sample_tags": _debug_sample_tags(tags, 5),
    }


def extract_drawing_info(pdf_path: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "drawing_number": None,
        "drawing_title": None,
        "drawing_type": None,
        "plant": None,
        "revision": None,
        "page_count": 0,
        "extraction_error": None,
    }
    try:
        with pdfplumber.open(pdf_path) as pdf:
            out["page_count"] = len(pdf.pages)
            if not pdf.pages:
                return out
            page = pdf.pages[0]
            w, h = float(page.width), float(page.height)
            crop = page.within_bbox((0, h * 0.85, w, h))
            text = crop.extract_text() or ""
            full_text = page.extract_text() or ""
            blob = (text + "\n" + full_text).upper()

            for m in DRAWING_NUM_RE.finditer(text + "\n" + full_text):
                cand = m.group(1).strip()
                if len(cand) > 20:
                    out["drawing_number"] = cand
                    break
            if not out["drawing_number"]:
                m2 = re.search(
                    r"([A-Z]{3,5}-[A-Z0-9]{2,5}-[A-Z]{3}-[A-Z]{3,4}-[A-Z]{3}-[0-9]{5}-[A-Z0-9]+-[0-9]{2,})",
                    text + full_text,
                    re.I,
                )
                if m2:
                    out["drawing_number"] = m2.group(1).strip()

            lines = [ln.strip() for ln in (text + "\n" + full_text).splitlines() if ln.strip()]
            if lines and not out["drawing_title"]:
                for ln in lines:
                    if len(ln) > 15 and not DRAWING_NUM_RE.search(ln):
                        if "SHEET" not in ln.upper() and "SCALE" not in ln.upper():
                            out["drawing_title"] = ln[:500]
                            break

            out["drawing_type"] = _infer_drawing_type(text + full_text)
            out["revision"] = _extract_revision(text + full_text)
            if out["drawing_number"]:
                out["plant"] = _infer_plant_from_drawing_number(out["drawing_number"])
            if not out["drawing_type"]:
                out["drawing_type"] = _infer_drawing_type(blob)
    except Exception as e:
        out["extraction_error"] = str(e)[:500]
    return out


def extract_colors_near_tags(pdf_path: str, tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach color_hex to each tag using rects near x,y (non-systemized comparison path)."""
    enriched = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for tag in tags:
                t = dict(tag)
                page_num = int(t.get("page_number") or 1) - 1
                if page_num < 0 or page_num >= len(pdf.pages):
                    t["color_hex"] = None
                    enriched.append(t)
                    continue
                page = pdf.pages[page_num]
                px, py = t.get("x"), t.get("y")
                best_hex = None
                best_d = 99999.0
                if px is not None and py is not None:
                    for rect in page.rects or []:
                        fill = rect.get("fill") or rect.get("non_stroking_color")
                        if not fill:
                            continue
                        if isinstance(fill, (list, tuple)) and len(fill) >= 3:
                            r, g, b = float(fill[0]), float(fill[1]), float(fill[2])
                        else:
                            continue
                        rr, gg, bb = r, g, b
                        if rr <= 1:
                            rr, gg, bb = rr * 255, gg * 255, bb * 255
                        if rr > 240 and gg > 240 and bb > 240:
                            continue
                        if rr < 15 and gg < 15 and bb < 15:
                            continue
                        rx = (float(rect["x0"]) + float(rect["x1"])) / 2
                        ry = (float(rect["top"]) + float(rect["bottom"])) / 2
                        d = ((rx - px) ** 2 + (ry - py) ** 2) ** 0.5
                        if d < 50 and d < best_d:
                            best_d = d
                            best_hex = _hex_from_rgb(r, g, b)
                t["color_hex"] = best_hex
                enriched.append(t)
    except Exception:
        for tag in tags:
            t = dict(tag)
            t["color_hex"] = None
            enriched.append(t)
    return enriched


def detect_comparison_type(role_a: str, role_b: str) -> str:
    a, b = role_a, role_b
    pair = {a, b}
    if pair == {"current_systemized", "new_engineering"}:
        return "new_vs_systemized"
    if pair == {"current_systemized", "prior_systemized"}:
        return "systemized_vs_systemized"
    if a == "new_engineering" and b == "new_engineering":
        return "new_vs_new"
    if "current_systemized" in pair and "new_engineering" in pair:
        return "new_vs_systemized"
    if "current_systemized" in pair and "prior_systemized" in pair:
        return "systemized_vs_systemized"
    return "new_vs_new"
