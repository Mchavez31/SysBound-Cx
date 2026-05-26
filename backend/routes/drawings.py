import json
import os
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database_connection import SessionLocal, get_db
from models.database import Comparison, Drawing, ProjectMember, Project, ProjectTagVerdict, Tag, User
from routes.auth import get_current_user
from services import file_storage, pdf_parser
from services.compare_progress import make_callback, mark_done, mark_error, set_progress, snapshot
from services.comparison_engine import compare_drawings, generate_excel_report
from services.pdf_snippet import extract_pdf_pages_bytes, pdf_page_count, render_tag_snippet_png

router = APIRouter()


def _require_member(project_id: str, user_id: str, db: Session) -> None:
    m = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        .first()
    )
    if not m:
        raise HTTPException(status_code=404, detail="Project not found")


class CompareBody(BaseModel):
    drawing_id_a: str
    drawing_id_b: str


def _compare_worker(
    cid: str,
    project_id: str,
    drawing_id_a: str,
    drawing_id_b: str,
) -> None:
    db = SessionLocal()
    try:
        da = db.query(Drawing).filter(Drawing.id == drawing_id_a, Drawing.project_id == project_id).first()
        dr_b = db.query(Drawing).filter(Drawing.id == drawing_id_b, Drawing.project_id == project_id).first()
        comp = db.query(Comparison).filter(Comparison.id == cid).first()
        if not da or not dr_b or not comp:
            mark_error(cid, "Comparison or drawings not found")
            return

        path_a = da.file_path or da.original_pdf_path
        path_b = dr_b.file_path or dr_b.original_pdf_path
        if not path_a or not path_b:
            comp.status = "failed"
            comp.result_json = json.dumps({"error": "Missing file path"})
            db.commit()
            mark_error(cid, "Drawing file missing on disk")
            return

        ctype = comp.comparison_type or pdf_parser.detect_comparison_type(da.drawing_role or "", dr_b.drawing_role or "")
        cb = make_callback(cid)
        cb(2, "Starting comparison…")

        invalid_rows = (
            db.query(ProjectTagVerdict)
            .filter(
                ProjectTagVerdict.project_id == project_id,
                ProjectTagVerdict.verdict == "invalid",
            )
            .all()
        )
        tag_exclude: frozenset[str] | None = None
        if invalid_rows:
            tag_exclude = frozenset(
                pdf_parser.normalize_tag_number(r.tag_normalized)
                for r in invalid_rows
                if r.tag_normalized
            )

        result = compare_drawings(
            str(Path(path_a).expanduser().resolve()),
            str(Path(path_b).expanduser().resolve()),
            da.drawing_role or "",
            dr_b.drawing_role or "",
            ctype,
            da.id,
            dr_b.id,
            project_id,
            da.drawing_number,
            dr_b.drawing_number,
            progress_cb=cb,
            tag_exclude_normalized=tag_exclude,
        )

        s = result["summary"]
        comp.status = "complete"
        comp.total_new = s.get("total_new", 0)
        comp.total_removed = s.get("total_removed", 0)
        comp.total_unchanged = s.get("total_unchanged", 0)
        comp.total_subsystem_changes = s.get("total_subsystem_changes", 0)
        comp.result_json = json.dumps(result, default=str)
        db.commit()

        rows_list = result.get("rows") or []
        batch_size = 300
        for batch_start in range(0, len(rows_list), batch_size):
            for row in rows_list[batch_start : batch_start + batch_size]:
                did = dr_b.id if row["change_type"] == "new" else da.id if row["change_type"] == "removed" else dr_b.id
                if row["change_type"] in ("unchanged", "color_changed", "subsystem_changed"):
                    did = dr_b.id
                ct = row["change_type"]
                sub_a, sub_b = row.get("subsystem_a"), row.get("subsystem_b")
                col_a, col_b = row.get("color_a"), row.get("color_b")
                if ct == "removed":
                    sub_num, sub_prev = sub_a, None
                    color_val = col_a
                elif ct == "new":
                    sub_num, sub_prev = sub_b, None
                    color_val = col_b
                else:
                    sub_num, sub_prev = sub_b, sub_a
                    color_val = col_b or col_a
                t = Tag(
                    id=str(uuid.uuid4()),
                    drawing_id=did,
                    project_id=project_id,
                    comparison_id=cid,
                    tag_number=row["tag_number"],
                    tag_type=row.get("tag_type"),
                    tag_category=row.get("tag_type"),
                    subsystem_number=sub_num,
                    previous_subsystem=sub_prev,
                    color_in_drawing=color_val,
                    action_needed=row.get("action_needed"),
                    change_type=row.get("change_type"),
                    is_x_tag=bool(row.get("is_x_tag")),
                    page_number=row.get("page_b") or row.get("page_a"),
                    page_x=None,
                    page_y=None,
                    status="comparison",
                )
                db.add(t)
            db.commit()

        cb(98, "Finishing…")
        mark_done(cid)
    except Exception as e:
        err_tb = traceback.format_exc()
        try:
            comp = db.query(Comparison).filter(Comparison.id == cid).first()
            if comp:
                comp.status = "failed"
                comp.result_json = json.dumps(
                    {"error": str(e), "traceback": err_tb[:12000]},
                    default=str,
                )
                db.commit()
        except Exception:
            db.rollback()
        mark_error(cid, str(e))
    finally:
        db.close()


def _drawing_to_dict(d: Drawing) -> dict[str, Any]:
    return {
        "id": d.id,
        "project_id": d.project_id,
        "drawing_number": d.drawing_number,
        "drawing_title": d.drawing_title,
        "drawing_type": d.drawing_type,
        "plant": d.plant,
        "revision": d.revision,
        "drawing_role": d.drawing_role,
        "status": d.status,
        "file_name": d.file_name,
        "page_count": d.page_count,
        "detected_drawing_number": d.detected_drawing_number,
        "detected_drawing_title": d.detected_drawing_title,
        "detected_drawing_type": d.detected_drawing_type,
        "detected_plant": d.detected_plant,
        "detected_revision": d.detected_revision,
        "extraction_error": d.extraction_error,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


@router.post("/{project_id}/upload")
async def upload_drawing(
    project_id: str,
    file: UploadFile = File(...),
    drawing_role: str = Form(...),
    manual_drawing_number: Optional[str] = Form(None),
    manual_drawing_type: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_member(project_id, current_user.id, db)
    if drawing_role not in ("current_systemized", "prior_systemized", "new_engineering"):
        raise HTTPException(status_code=400, detail="Invalid drawing_role")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    path = file_storage.save_upload(raw, project_id, file.filename or "drawing.pdf")

    info = pdf_parser.extract_drawing_info(path)
    dn = manual_drawing_number or info.get("drawing_number") or "UNKNOWN"
    dt = manual_drawing_type or info.get("drawing_type")
    title = info.get("drawing_title") or dn
    plant = info.get("plant")
    rev = info.get("revision")

    status = "uploaded"
    if info.get("extraction_error"):
        status = "extraction_partial"

    d = Drawing(
        id=str(uuid.uuid4()),
        project_id=project_id,
        drawing_number=dn,
        drawing_title=title,
        drawing_type=dt,
        plant=plant or info.get("detected_plant"),
        revision=rev,
        is_systemized=drawing_role in ("current_systemized", "prior_systemized"),
        status=status,
        original_pdf_path=path,
        drawing_role=drawing_role,
        file_path=path,
        file_name=file.filename,
        page_count=info.get("page_count") or 0,
        detected_drawing_number=info.get("drawing_number"),
        detected_drawing_title=info.get("drawing_title"),
        detected_drawing_type=info.get("drawing_type"),
        detected_plant=info.get("plant"),
        detected_revision=info.get("revision"),
        extraction_error=info.get("extraction_error"),
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return _drawing_to_dict(d)


@router.get("/{project_id}")
def list_drawings_grouped(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_member(project_id, current_user.id, db)
    rows = db.query(Drawing).filter(Drawing.project_id == project_id).order_by(Drawing.drawing_number).all()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for d in rows:
        key = d.drawing_number or "unknown"
        grouped.setdefault(key, []).append(_drawing_to_dict(d))
    return {"grouped_by_drawing_number": grouped, "drawings": [_drawing_to_dict(x) for x in rows]}


@router.post("/{project_id}/compare")
def run_compare(
    project_id: str,
    body: CompareBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_member(project_id, current_user.id, db)
    da = db.query(Drawing).filter(Drawing.id == body.drawing_id_a, Drawing.project_id == project_id).first()
    dr_b = db.query(Drawing).filter(Drawing.id == body.drawing_id_b, Drawing.project_id == project_id).first()
    if not da or not dr_b:
        raise HTTPException(status_code=404, detail="Drawing not found")

    ctype = pdf_parser.detect_comparison_type(da.drawing_role or "", dr_b.drawing_role or "")
    cid = str(uuid.uuid4())
    comp = Comparison(
        id=cid,
        project_id=project_id,
        drawing_id_a=da.id,
        drawing_id_b=dr_b.id,
        comparison_type=ctype,
        status="running",
        run_at=datetime.now(timezone.utc),
    )
    db.add(comp)
    db.commit()

    path_a = da.file_path or da.original_pdf_path
    path_b = dr_b.file_path or dr_b.original_pdf_path
    if not path_a or not path_b:
        comp.status = "failed"
        comp.result_json = json.dumps({"error": "Missing file path"})
        db.commit()
        raise HTTPException(status_code=400, detail="Drawing file missing on disk")

    set_progress(cid, 0, "Queued…")
    threading.Thread(
        target=_compare_worker,
        args=(cid, project_id, da.id, dr_b.id),
        daemon=True,
    ).start()

    return {"comparison_id": cid, "status": "running"}


@router.get("/{project_id}/comparisons/{comparison_id}/progress")
def get_compare_progress(
    project_id: str,
    comparison_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_member(project_id, current_user.id, db)
    c = (
        db.query(Comparison)
        .filter(Comparison.id == comparison_id, Comparison.project_id == project_id)
        .first()
    )
    if not c:
        raise HTTPException(status_code=404, detail="Not found")

    if c.status == "complete":
        return {"percent": 100, "message": "Complete", "done": True, "error": None}
    if c.status == "failed":
        err = None
        try:
            j = json.loads(c.result_json) if c.result_json else {}
            err = j.get("error")
        except Exception:
            pass
        snap = snapshot(comparison_id) or {}
        return {
            "percent": snap.get("percent", 100),
            "message": snap.get("message", "Failed"),
            "done": True,
            "error": err or snap.get("error") or "Comparison failed",
        }

    # Running: reload progress columns from DB (avoid stale ORM identity-map reads on repeated polls).
    try:
        db.expire(c, ["progress_percent", "progress_message"])
    except Exception:
        db.expire(c)

    # Running: read DB first (works across Uvicorn workers); merge in-memory snapshot when present.
    db_pct = getattr(c, "progress_percent", None)
    db_msg = getattr(c, "progress_message", None) or ""
    pct = int(db_pct) if db_pct is not None else 0
    msg = db_msg
    snap = snapshot(comparison_id)
    if snap:
        pct = max(pct, int(snap.get("percent", 0)))
        if snap.get("message"):
            msg = snap["message"]
        if snap.get("done"):
            return {
                "percent": snap.get("percent", pct),
                "message": snap.get("message", msg),
                "done": True,
                "error": snap.get("error"),
            }
    if not msg:
        msg = "Running…"
    return {"percent": pct, "message": msg, "done": False, "error": None}


@router.get("/{project_id}/comparisons")
def list_comparisons(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_member(project_id, current_user.id, db)
    comps = db.query(Comparison).filter(Comparison.project_id == project_id).order_by(Comparison.run_at.desc()).all()
    out = []
    for c in comps:
        da = db.query(Drawing).filter(Drawing.id == c.drawing_id_a).first()
        dr_b = db.query(Drawing).filter(Drawing.id == c.drawing_id_b).first()
        out.append(
            {
                "id": c.id,
                "comparison_type": c.comparison_type,
                "status": c.status,
                "run_at": c.run_at.isoformat() if c.run_at else None,
                "total_new": c.total_new,
                "total_removed": c.total_removed,
                "total_unchanged": c.total_unchanged,
                "total_subsystem_changes": c.total_subsystem_changes,
                "drawing_a": da.drawing_number if da else c.drawing_id_a,
                "drawing_b": dr_b.drawing_number if dr_b else c.drawing_id_b,
            }
        )
    return out


@router.delete("/{project_id}/comparisons/{comparison_id}")
def delete_comparison(
    project_id: str,
    comparison_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_member(project_id, current_user.id, db)
    c = (
        db.query(Comparison)
        .filter(Comparison.id == comparison_id, Comparison.project_id == project_id)
        .first()
    )
    if not c:
        raise HTTPException(status_code=404, detail="Comparison not found")
    db.query(Tag).filter(Tag.comparison_id == comparison_id).delete(synchronize_session=False)
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.get("/{project_id}/comparisons/{comparison_id}")
def get_comparison(
    project_id: str,
    comparison_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_member(project_id, current_user.id, db)
    c = (
        db.query(Comparison)
        .filter(Comparison.id == comparison_id, Comparison.project_id == project_id)
        .first()
    )
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    data = json.loads(c.result_json) if c.result_json else {}
    tags = db.query(Tag).filter(Tag.comparison_id == comparison_id).all()
    return {
        "comparison": {
            "id": c.id,
            "comparison_type": c.comparison_type,
            "status": c.status,
            "run_at": c.run_at.isoformat() if c.run_at else None,
            "totals": {
                "new": c.total_new,
                "removed": c.total_removed,
                "unchanged": c.total_unchanged,
                "subsystem_changes": c.total_subsystem_changes,
            },
        },
        "drawing_id_a": c.drawing_id_a,
        "drawing_id_b": c.drawing_id_b,
        "result": data,
        "tags": [
            {
                "id": t.id,
                "tag_number": t.tag_number,
                "tag_type": t.tag_category or t.tag_type,
                "change_type": t.change_type,
                "action_needed": t.action_needed,
                "subsystem_a": t.previous_subsystem,
                "subsystem_b": t.subsystem_number,
                "color_a": None,
                "color_b": t.color_in_drawing,
                "page": t.page_number,
                "is_x_tag": t.is_x_tag,
            }
            for t in tags
        ],
    }


@router.get("/{project_id}/report")
def download_report(
    project_id: str,
    comparison_id: str = Query(...),
    format: str = Query("json"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_member(project_id, current_user.id, db)
    c = (
        db.query(Comparison)
        .filter(Comparison.id == comparison_id, Comparison.project_id == project_id)
        .first()
    )
    if not c or not c.result_json:
        raise HTTPException(status_code=404, detail="Comparison not found")
    data = json.loads(c.result_json)
    proj = db.query(Project).filter(Project.id == project_id).first()
    name = proj.name if proj else project_id

    if format == "excel":
        blob = generate_excel_report(data, name)
        return Response(
            content=blob,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="comparison-{comparison_id}.xlsx"'},
        )
    return data


@router.delete("/{project_id}/{drawing_id}")
def delete_drawing(
    project_id: str,
    drawing_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_member(project_id, current_user.id, db)
    d = db.query(Drawing).filter(Drawing.id == drawing_id, Drawing.project_id == project_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    fp = d.file_path or d.original_pdf_path
    file_storage.delete_upload_file(fp or "")
    db.query(Tag).filter(Tag.drawing_id == drawing_id).delete()
    db.query(Comparison).filter(
        or_(Comparison.drawing_id_a == drawing_id, Comparison.drawing_id_b == drawing_id)
    ).delete(synchronize_session=False)
    db.query(Drawing).filter(Drawing.id == drawing_id).delete()
    db.commit()
    return {"ok": True}


@router.get("/{project_id}/drawing/{drawing_id}/snippet")
def get_drawing_snippet_png(
    project_id: str,
    drawing_id: str,
    page: int = Query(..., ge=1),
    x: Optional[float] = Query(None),
    y: Optional[float] = Query(None),
    margin: float = Query(170, ge=30, le=400),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """PNG crop around extracted tag coordinates (same space as pdfplumber). Omit x/y for a downscaled full-page image."""
    _require_member(project_id, current_user.id, db)
    d = db.query(Drawing).filter(Drawing.id == drawing_id, Drawing.project_id == project_id).first()
    if not d:
        raise HTTPException(
            status_code=404,
            detail="Drawing not found for this project (re-run comparison or re-upload the PDFs).",
        )
    raw = d.file_path or d.original_pdf_path
    if not raw:
        raise HTTPException(status_code=404, detail="PDF file not found on disk (no path stored for this drawing).")
    fp = Path(raw).expanduser().resolve()
    if not fp.is_file():
        raise HTTPException(
            status_code=404,
            detail="PDF file not found on disk — re-upload the drawing or check the file path on the server.",
        )
    try:
        png = render_tag_snippet_png(
            str(fp),
            page,
            x,
            y,
            margin_pt=margin,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not render snippet: {e!s}") from e
    return Response(content=png, media_type="image/png")


@router.get("/{project_id}/drawing/{drawing_id}/pdf")
def get_drawing_pdf_file(
    project_id: str,
    drawing_id: str,
    extract_pages: Optional[str] = Query(
        None,
        description="Comma-separated 1-based page numbers; returns a PDF with only those pages (order preserved)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream the stored PDF for side-by-side comparison in the browser."""
    _require_member(project_id, current_user.id, db)
    d = db.query(Drawing).filter(Drawing.id == drawing_id, Drawing.project_id == project_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    raw = d.file_path or d.original_pdf_path
    if not raw:
        raise HTTPException(status_code=404, detail="PDF file not found on disk")
    fp = Path(raw).expanduser().resolve()
    if not fp.is_file():
        raise HTTPException(status_code=404, detail="PDF file not found on disk")
    name = d.file_name or "drawing.pdf"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"

    if extract_pages and extract_pages.strip():
        try:
            nums = [int(p.strip()) for p in extract_pages.split(",") if p.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid extract_pages parameter") from None
        nums = [n for n in nums if n >= 1]
        if not nums:
            raise HTTPException(status_code=400, detail="Provide at least one valid page number")
        try:
            nmax = pdf_page_count(str(fp))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not read PDF: {e!s}") from e
        bad = [n for n in nums if n > nmax]
        if bad:
            raise HTTPException(status_code=400, detail=f"Page(s) out of range for this PDF: {bad}")
        try:
            subset = extract_pdf_pages_bytes(str(fp), nums)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Page extract failed: {e!s}") from e
        stem = Path(name).stem
        suffix = "-".join(str(x) for x in nums)
        sub_name = f"{stem}_p{suffix}.pdf"
        return Response(
            content=subset,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{sub_name}"'},
        )

    return FileResponse(str(fp), media_type="application/pdf", filename=name)


@router.get("/{project_id}/drawing/{drawing_id}")
def get_drawing(
    project_id: str,
    drawing_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_member(project_id, current_user.id, db)
    d = db.query(Drawing).filter(Drawing.id == drawing_id, Drawing.project_id == project_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    return _drawing_to_dict(d)


@router.get("/{project_id}/drawing/{drawing_id}/extract-tags")
def extract_tags_from_drawing(
    project_id: str,
    drawing_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Extract all tags from a drawing for verification - returns detailed tag data."""
    _require_member(project_id, current_user.id, db)
    d = db.query(Drawing).filter(Drawing.id == drawing_id, Drawing.project_id == project_id).first()
    if not d or not d.file_path:
        raise HTTPException(status_code=404, detail="Drawing not found")
    
    try:
        # Extract all tags from the PDF
        result = pdf_parser.extract_all(d.file_path)
        tags = result.get("tags", [])
        
        # Group tags by page for easier review
        tags_by_page = {}
        for tag in tags:
            page = tag.get("page_number", 1)
            if page not in tags_by_page:
                tags_by_page[page] = []
            tags_by_page[page].append({
                "tag_number": tag.get("tag_number"),
                "tag_type": tag.get("tag_type"),
                "page": page,
                "x": tag.get("x"),
                "y": tag.get("y"),
                "tag_fill_color": tag.get("tag_fill_color"),
                "nearest_subsystem": tag.get("nearest_subsystem"),
                "nearest_subsystem_color": tag.get("nearest_subsystem_color"),
            })
        
        return {
            "drawing_id": drawing_id,
            "drawing_number": d.drawing_number,
            "total_tags": len(tags),
            "total_pages": result.get("page_count", 0),
            "tags_by_page": tags_by_page,
            "extraction_info": {
                "label_count": result.get("label_count", 0),
                "subsystems_found": result.get("subsystems_found", []),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")


def _classify_discipline(tag_number: str) -> str:
    """Classify tag discipline based on prefix patterns.
    
    Important: V tags without inch marks are VESSELS (equipment), not valves/piping.
    """
    tag_upper = tag_number.upper()
    prefix = tag_upper.split('-')[0] if '-' in tag_upper else tag_upper[:3]
    
    # Piping lines (have inch marks) - check FIRST before other logic
    if '"' in tag_number:
        return 'Piping'
    
    # Instrument/Control tags (ISA standard)
    instrument_prefixes = {'FT', 'PT', 'TT', 'LT', 'FIC', 'PIC', 'TIC', 'LIC', 'FI', 'PI', 'TI', 'LI',
                          'FE', 'PE', 'TE', 'LE', 'ZT', 'ZIC', 'ZIO', 'ZSO', 'ZSC', 'HS', 'AIT', 'DCS',
                          'DFCS', 'FCCS'}
    if any(prefix.startswith(p) for p in instrument_prefixes):
        return 'Instrument'
    
    # V prefix: Vessel if no inch mark (e.g., V-37803), Valve if part of longer prefix (XV, HV, etc.)
    if prefix == 'V':
        # V-12345 without inch mark = Vessel (equipment)
        return 'Mechanical'
    
    # Valves (multi-letter prefixes with V)
    valve_prefixes = {'XV', 'HV', 'CV', 'PV', 'PSV', 'PRV', 'BDV', 'SDV', 'MOV', 'SOV', 'PCV', 'FCV', 'LCV'}
    if prefix in valve_prefixes:
        return 'Piping'
    
    # Pumps, compressors, vessels, tanks, drums
    mechanical_prefixes = {'P', 'C', 'K', 'T', 'D', 'F', 'R', 'E', 'H', 'G', 'U'}
    if prefix in mechanical_prefixes and not prefix.startswith('PT'):
        return 'Mechanical'
    
    # Electrical
    electrical_prefixes = {'M', 'MCC', 'VFD', 'MOT', 'MTR', 'PNL', 'XFM'}
    if any(prefix.startswith(p) for p in electrical_prefixes):
        return 'Electrical'
    
    # Specialty items
    if prefix == 'SP':
        return 'Specialty'
    
    # Structure/building
    structure_prefixes = {'S', 'STR', 'BLD', 'PLT'}
    if prefix in structure_prefixes:
        return 'Structural'
    
    return 'Other'


def _is_valid_tag(tag_number: str) -> bool:
    """Validate if a tag number is a real equipment tag per PIMS tagging specification.
    
    Returns False for:
    - Drawing codes (WOD-00000, WWOC-WGXX)
    - Drawing annotations (ENT-*, RENT-*, NOTE-*, ALARM-*)
    - Project codes (WILG-WFXX-PRO-...)
    - Text fragments (ALVE, ANDLI, ATON, etc.)
    - Tags with unknown prefixes not in PIMS specification
    
    Returns True ONLY for tags matching valid PIMS equipment code prefixes.
    """
    import re
    
    tag_upper = tag_number.upper().strip()
    
    # Must have minimum structure
    if len(tag_upper) < 3:
        return False
    
    # Filter out drawing metadata codes (WOD-, WWO-, WOC-, WWC-)
    if re.match(r'^W[OW][DCAOX]-', tag_upper):
        return False
    
    # Filter out project/drawing codes (WILG-WFXX-...)
    if re.match(r'^WILG-', tag_upper):
        return False
    
    # Filter out obvious text fragments and annotation codes
    text_fragments = {
        'FROM', 'NOTE', 'AREA', 'CASE', 'RENT', 'ENT', 'ALARM', 'FIRE',
        'ATION', 'ANDLI', 'ALVE', 'ALOW', 'AIRN', 'ALASD', 'AGEN', 'AGMV',
        'AELH', 'ADED', 'ACFM', 'ALNN', 'ASDSS', 'ASDW', 'ASOR', 'BBLR',
        'ANKU', 'ANY', 'ARY', 'ATON', 'ETON', 'TIFFOS', 'BOJV', 'SLR',
        'EHWGM', 'FCN', 'LNN', 'HOA', 'XXX', 'DLFR', 'BTT', 'FCT', 'PITMV',
        'VBT', 'ABV', 'KL', 'KLN', 'VALVE', 'LVE'
    }
    
    # Get prefix (part before first dash or inch mark)
    if '\"' in tag_upper:
        # Piping tag with inch mark - validate separately below
        pass
    elif '-' in tag_upper:
        prefix = tag_upper.split('-')[0]
        if prefix in text_fragments:
            return False
        # Check if prefix matches any valid PIMS equipment code
        if not _is_valid_pims_prefix(prefix):
            return False
    else:
        # No dash or inch mark - not a valid tag format
        return False
    
    # Filter out SPSP malformed tags
    if re.match(r'^SPSP-\d+(WGL|WGP|WGR)', tag_upper):
        return False
    
    # Piping lines must have valid format: NN"-XXX-NNNNNNN
    if '\"' in tag_upper:
        match = re.match(r'^(\d+(?:\.\d+)?)\"-([A-Z]{2,3})-(\d{5,7})', tag_upper)
        if not match:
            return False
        service_code = match.group(2)
        # Validate service code against PIMS Table 6.3.1
        valid_service_codes = {
            'AI', 'AM', 'AP', 'BC', 'BM', 'BW', 'CA', 'CB', 'CC', 'CCA', 'CCH', 'CD',
            'CE', 'CF', 'CG', 'CH', 'CI', 'CM', 'CO', 'CS', 'CW', 'DF', 'DO', 'DP',
            'FD', 'FG', 'FH', 'FL', 'GI', 'GL', 'GM', 'GN', 'GW', 'HF', 'HG', 'HO',
            'HW', 'LF', 'LN', 'LNG', 'LO', 'MC', 'ME', 'MG', 'MI', 'MP', 'MS', 'MT',
            'MU', 'MV', 'MW', 'MX', 'NGL', 'OS', 'PC', 'PG', 'PO', 'PW', 'SO', 'ST',
            'SW', 'VA', 'WA', 'WC', 'WD', 'WF', 'WG', 'WH', 'WI', 'WL', 'WM', 'WO',
            'WR', 'WS', 'WX'
        }
        if service_code not in valid_service_codes:
            return False
    
    # Tag should have at least one digit
    if not any(c.isdigit() for c in tag_upper):
        return False
    
    # If tag is very long, it's probably malformed
    if len(tag_upper) > 30:
        return False
    
    return True


def _is_valid_pims_prefix(prefix: str) -> bool:
    """Check if a tag prefix is valid according to PIMS Tagging Specification.
    
    Validates against:
    - Table 6.1.1: Mechanical Equipment Codes
    - Table 6.2.1: Manual Valve Codes
    - Table 6.4.1: HVAC Equipment Codes
    - Table 6.6.1: Electrical Equipment Codes
    - Table 6.9.1: Instrumentation Codes
    - Section 6.5: Special Item Code (SP)
    """
    # Mechanical/Process Equipment (Table 6.1.1)
    mechanical_codes = {
        'A', 'AW', 'BLN', 'C', 'DP', 'E', 'EF', 'F', 'G', 'H', 'HH', 'K', 'M',
        'P', 'S', 'SF', 'T', 'TB', 'U', 'V', 'VET', 'W', 'X', 'Z'
    }
    
    # Manual Valves (Table 6.2.1)
    valve_codes = {'MV', 'CK'}
    
    # HVAC Equipment (Table 6.4.1)
    hvac_codes = {
        'ACU', 'AHU', 'BD', 'CU', 'CVD', 'EHC', 'EUH', 'FSD', 'HHC', 'HU',
        'MCD', 'RAG', 'RF', 'SAD', 'SAG', 'SOD', 'TAG', 'TF', 'TU', 'UH', 'VCD'
    }
    
    # Electrical Equipment (Table 6.6.1) - Major codes
    electrical_codes = {
        'AB', 'AGS', 'ANT', 'ASD', 'ATS', 'AR', 'AWL', 'BC', 'BKR', 'BS', 'CAM',
        'CCTV', 'CJB', 'COMM', 'CP', 'CWJB', 'DIS', 'DO', 'DP', 'DPU', 'DSP', 'ED',
        'ELP', 'ELRW', 'ELTW', 'EN', 'EPH', 'EPP', 'EPT', 'ESD', 'ETV', 'FOJB',
        'FOPB', 'FOPP', 'FOS', 'FOVT', 'GATE', 'GR', 'HF', 'HP', 'HS', 'HT', 'HTB',
        'IP', 'LB', 'LBC', 'LBSC', 'LCR', 'LIR', 'LP', 'LREG', 'LJB', 'LSD', 'LTR',
        'MCC', 'MR', 'MS', 'MTS', 'NAP', 'NS', 'ODAL', 'OS', 'OWS', 'PAC', 'PACB',
        'PACH', 'PACL', 'PACM', 'PACR', 'PAJB', 'PAOF', 'PAPI', 'PCC', 'PCL', 'PEC',
        'PJB', 'PMS', 'PP', 'PS', 'PTB', 'PTR', 'PTRN', 'RAD', 'RCP', 'REIL', 'RGL',
        'RP', 'RVR', 'RX', 'SFRW', 'SG', 'SIGN', 'SPD', 'SRVR', 'STB', 'STE', 'STR',
        'SW', 'THMA', 'TJB', 'TP', 'TSG', 'UP', 'UPS', 'UTB', 'VE', 'WAP', 'WB', 'WC', 'WX'
    }
    
    # Instrumentation (Table 6.9.1) - Comprehensive list
    instrument_codes = {
        'AAH', 'AAHH', 'AAL', 'AALL', 'AC', 'AIC', 'AE', 'AH', 'AI', 'AIT', 'AK', 'AN', 'AP',
        'AS', 'ASH', 'ASL', 'AT', 'AY', 'AZ', 'AZI', 'AZT',
        'BA', 'BAH', 'BAHH', 'BAL', 'BALL', 'BDV', 'BDY', 'BE', 'BI', 'BL', 'BLC', 'BLO', 'BS',
        'BT', 'BY', 'BZE', 'BZI', 'BZT',
        'CAH', 'CAHH', 'CAL', 'CE', 'CI', 'CIC', 'CLH', 'CS', 'CT', 'CY',
        'DAH', 'DAL', 'DALL', 'DE', 'DI', 'DIC', 'DIT', 'DS', 'DT', 'DV', 'DY',
        'EI', 'ERP', 'ERS', 'EY',
        'FA', 'FAH', 'FAHH', 'FAL', 'FALL', 'FC', 'FCV', 'FDAH', 'FDI', 'FE', 'FFC', 'FFI', 'FG',
        'FHS', 'FI', 'FIC', 'FIT', 'FJB', 'FO', 'FQC', 'FQI', 'FS', 'FSH', 'FSL', 'FSV', 'FT',
        'FV', 'FX', 'FY', 'FZE', 'FZI', 'FZIT', 'FZT',
        'GDAL', 'GDC', 'GDE', 'GDI', 'GDO', 'GDOPR', 'GDOPT', 'GDP', 'GDT', 'GUA',
        'HAHH', 'HC', 'HCV', 'HI', 'HIS', 'HSX', 'HV', 'HX', 'HY', 'HZS',
        'II', 'IIT', 'IR', 'IJB', 'IT', 'IY',
        'JI', 'JOA',
        'KC', 'KE', 'KI', 'KIC', 'KQI', 'KQAH', 'KT', 'KY',
        'LA', 'LAH', 'LAHH', 'LAHHH', 'LAL', 'LALL', 'LC', 'LCV', 'LDA', 'LDAH', 'LDI', 'LG', 'LE',
        'LHS', 'LI', 'LIC', 'LIT', 'LKAH', 'LKI', 'LS', 'LSH', 'LSHH', 'LSL', 'LSLL', 'LT', 'LV',
        'LY', 'LZI', 'LZIT', 'LZT',
        'MC', 'ME', 'MI', 'MIC', 'MIT', 'MOV', 'MRC', 'MY',
        'NI', 'NT',
        'PAH', 'PAHH', 'PAL', 'PALL', 'PC', 'PCS', 'PCV', 'PDAH', 'PDAHH', 'PDAL', 'PDALL', 'PDC',
        'PDI', 'PDCV', 'PDIC', 'PDIT', 'PDS', 'PDSH', 'PDSL', 'PDT', 'PDV', 'PDY', 'PDZI', 'PDZIT',
        'PDZLH', 'PDZT', 'PG', 'PHS', 'PI', 'PIC', 'PIT', 'PKY', 'PS', 'PSE', 'PSH', 'PSL', 'PSLL',
        'PSV', 'PT', 'PV', 'PVSV', 'PY', 'PZI', 'PZAHH', 'PZALL', 'PZIT', 'PZLHH', 'PZT', 'PZY',
        'QAHH', 'QEV', 'QI', 'QY',
        'SAH', 'SAHH', 'SC', 'SD', 'SDV', 'SDY', 'SE', 'SG', 'SI', 'SIC', 'SJB', 'SOCH', 'SSHH',
        'SSV', 'SSSV', 'ST', 'SY',
        'TAH', 'TAHH', 'TAL', 'TALL', 'TC', 'TCH', 'TCL', 'TCV', 'TD', 'TDAH', 'TDC', 'TDI', 'TDY',
        'TE', 'THS', 'TI', 'TIC', 'TIT', 'TS', 'TSE', 'TSH', 'TSHH', 'TSL', 'TSV', 'TT', 'TV', 'TW',
        'TY', 'TZE', 'TZI', 'TZIT', 'TZT', 'TZV', 'TZY',
        'UA', 'UC', 'UCP', 'UI', 'US', 'UU', 'UV', 'UY',
        'VAH', 'VAHH', 'VI', 'VIS', 'VJB', 'VSH', 'VSHH', 'VT', 'VXAH', 'VXAHH', 'VXE', 'VXI', 'VXT',
        'VY', 'VYE', 'VYI', 'VYT', 'VZI', 'VZT',
        'WD', 'WE', 'WI', 'WL', 'WT',
        'XA', 'XAH', 'XAHH', 'XAL', 'XALL', 'XC', 'XCV', 'XE', 'XHS', 'XI', 'XL', 'XS', 'XT', 'XV',
        'XY', 'XYR', 'XZE', 'XZV', 'XZY',
        'YA', 'YI', 'YL', 'YS', 'YY',
        'ZA', 'ZAC', 'ZAF', 'ZAO', 'ZAR', 'ZE', 'ZC', 'ZDI', 'ZLC', 'ZLO', 'ZI', 'ZIC', 'ZIO', 'ZS',
        'ZSC', 'ZSF', 'ZSO', 'ZSR', 'ZT', 'ZV', 'ZY', 'ZZI', 'ZZIC', 'ZZIO', 'ZZSC', 'ZZSO', 'ZZT'
    }
    
    # Special Item Code (Section 6.5)
    special_codes = {'SP'}
    
    # Combine all valid codes
    all_valid_codes = (mechanical_codes | valve_codes | hvac_codes | electrical_codes | 
                      instrument_codes | special_codes)
    
    return prefix in all_valid_codes


def _parse_tag_type(tag_number: str) -> str:
    """Extract tag type from tag number matching PIMS commissioning format.
    
    For piping lines, includes the inch size in the tag type (e.g., 10"-WF, not just WF).
    Validates against PIMS specification tables to ensure only valid equipment codes are returned.
    
    Examples (PIMS format):
        1"-AI-7080707-T1X -> 1"-AI
        1"-DO-7080706-A1B3X -> 1"-DO
        FIT-9881234 -> FIT
        TIT-WGL1-001 -> TIT
        LAH-9881715 -> LAH
        HS-9881234 -> HS
        XV-9881520 -> XV
        10"-WF-6280974-A2C3 -> 10"-WF (includes inch size for piping)
        SP-988034 -> SP
        V-37803 -> V
        P-31001 -> P
    """
    import re
    
    # Remove any leading/trailing whitespace
    tag = tag_number.strip().upper()
    
    # Pattern 1: Size + "-" + Type + "-" + digits (e.g., 1"-AI-7080707, 10"-WF-6280974)
    # For piping lines, INCLUDE the inch size in the tag type
    match = re.match(r'^(\d+(?:\.\d+)?"-[A-Z]{2,3})-', tag)
    if match:
        full_type = match.group(1)  # Returns "10\"-WF" including inch size
        # Extract just the service code to validate
        service_match = re.match(r'\d+(?:\.\d+)?"-([A-Z]{2,3})', full_type)
        if service_match:
            service_code = service_match.group(1)
            # Validate service code against PIMS Table 6.3.1
            valid_service_codes = {
                'AI', 'AM', 'AP', 'BC', 'BM', 'BW', 'CA', 'CB', 'CC', 'CCA', 'CCH', 'CD',
                'CE', 'CF', 'CG', 'CH', 'CI', 'CM', 'CO', 'CS', 'CW', 'DF', 'DO', 'DP',
                'FD', 'FG', 'FH', 'FL', 'GI', 'GL', 'GM', 'GN', 'GW', 'HF', 'HG', 'HO',
                'HW', 'LF', 'LN', 'LNG', 'LO', 'MC', 'ME', 'MG', 'MI', 'MP', 'MS', 'MT',
                'MU', 'MV', 'MW', 'MX', 'NGL', 'OS', 'PC', 'PG', 'PO', 'PW', 'SO', 'ST',
                'SW', 'VA', 'WA', 'WC', 'WD', 'WF', 'WG', 'WH', 'WI', 'WL', 'WM', 'WO',
                'WR', 'WS', 'WX'
            }
            if service_code in valid_service_codes:
                return full_type
    
    # Pattern 2: Type + "-" + digits or Type + "-" + module (e.g., FIT-9881234, LAH-WGL1-001)
    match = re.match(r'^([A-Z]{1,5})-(?:\d|[A-Z])', tag)
    if match:
        prefix = match.group(1)
        
        # Use the comprehensive PIMS prefix validation
        if _is_valid_pims_prefix(prefix):
            return prefix
    
    # Pattern 3: Just letters at the start (e.g., for equipment tags like P-1234, V-5678)
    match = re.match(r'^([A-Z]{1,2})(?:-|\d)', tag)
    if match:
        prefix = match.group(1)
        # Validate against PIMS equipment codes
        if _is_valid_pims_prefix(prefix):
            return prefix
    
    return 'Unknown'


def _parse_tag_plant_module(tag_number: str, subsystem: str = "", drawing_metadata: dict = None) -> dict:
    """Parse plant and module from tag number using multiple strategies.
    
    Strategies (in order of priority):
    1. Module code directly in tag (e.g., TIT-WGL1-001, FIT-WGL3-234)
    2. Sheet suffix patterns (e.g., A1V3X -> WGL1, A2C3 -> WGL2)
    3. Terminal codes (e.g., BKP7 -> WGPT, BWD7 -> WGRT)
    4. Drawing metadata/title block (from drawing_metadata param)
    5. Fall back to "Unknown"
    
    Module codes are encoded in tag numbers in several ways:
    - Direct: TIT-WGL1-001 (module between prefix and sequence)
    - Suffix: FIT-9881234-A3V3X (A3 = module 3)
    - Terminal: 34"-PW-56002-BKP7 (BKP7 = pipeline terminal)
    """
    import re
    
    plant = 'WOC'  # Default plant for Willow
    module = 'Unknown'
    
    tag_upper = tag_number.upper().strip()
    
    # Strategy 1: Module code directly in tag (e.g., TIT-WGL1-001, LAH-WGL3-234)
    # Pattern: PREFIX-WGLX-NUMBERS or PREFIX-WGXX-NUMBERS
    direct_module_match = re.search(r'-(WGL[1-5]|WGPT|WGRT|WGJ[1-7]|WGM[1-8]|WGA[0-9]|WGXX|WGS\d)', tag_upper)
    if direct_module_match:
        module = direct_module_match.group(1)
        return {'plant': plant, 'module': module}
    
    # Strategy 2: Sheet suffix patterns (e.g., A1V3X, A2C3, T1X)
    # Pattern: Letter + Digit + optional alphanumeric (the digit indicates the module)
    suffix_match = re.search(r'-([A-Z](\d)[A-Z0-9]{1,3})$', tag_upper)
    if suffix_match:
        digit = suffix_match.group(2)
        module_map = {
            '1': 'WGL1',
            '2': 'WGL2',
            '3': 'WGL3',
            '4': 'WGL4',
            '5': 'WGL5',
        }
        if digit in module_map:
            return {'plant': plant, 'module': module_map[digit]}
    
    # Strategy 3: Terminal codes (BKP7, BWD7, etc.)
    terminal_match = re.search(r'-(B[A-Z]{2}\d)$', tag_upper)
    if terminal_match:
        suffix = terminal_match.group(1)
        if 'BKP' in suffix or 'BKD' in suffix:
            module = 'WGPT'  # Pipeline Terminal
        elif 'BWD' in suffix or 'BWR' in suffix:
            module = 'WGRT'  # Rail Terminal
        return {'plant': plant, 'module': module}
    
    # Strategy 4: Extract from drawing metadata (title block info)
    if drawing_metadata:
        # Check if drawing number contains module info
        # Example: "WILG-WFXX-PRO-PID-WOD-00000-00001-01" might have module in title
        drawing_title = drawing_metadata.get('drawing_title', '')
        drawing_number = drawing_metadata.get('drawing_number', '')
        
        # Look for module codes in drawing title or number
        module_pattern = re.search(r'(WGL[1-5]|WGPT|WGRT|WGJ[1-7]|WGM[1-8])', drawing_title + ' ' + drawing_number)
        if module_pattern:
            module = module_pattern.group(1)
            return {'plant': plant, 'module': module}
    
    # Strategy 5: Try to infer from system number in tag (first 2 digits after prefix)
    # This is a weak signal but better than nothing
    system_match = re.match(r'^[A-Z]{1,5}-(\d{2})', tag_upper)
    if system_match:
        system_num = system_match.group(1)
        # Certain system numbers might correlate with specific modules
        # This would require domain knowledge mapping
        # For now, we leave as Unknown but keep the framework for future enhancement
        pass
    
    return {'plant': plant, 'module': module}
    match = re.search(r'-(WGL[1-5]|WGPT|WGRT)-', tag_upper)
    if match:
        module = match.group(1)
        return {'plant': plant, 'module': module}
    
    # If subsystem is provided, we could potentially map it to modules
    # For now, this remains Unknown if no pattern matches
    
    return {'plant': plant, 'module': module}


@router.get("/{project_id}/drawing/{drawing_id}/tag-report")
def generate_tag_report(
    project_id: str,
    drawing_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate comprehensive tag extraction report for a drawing with all metadata."""
    _require_member(project_id, current_user.id, db)
    d = db.query(Drawing).filter(Drawing.id == drawing_id, Drawing.project_id == project_id).first()
    if not d or not d.file_path:
        raise HTTPException(status_code=404, detail="Drawing not found")
    
    try:
        # Get drawing metadata for module extraction
        drawing_info = pdf_parser.extract_drawing_info(d.file_path)
        drawing_metadata = {
            'drawing_number': d.drawing_number or drawing_info.get('drawing_number', ''),
            'drawing_title': drawing_info.get('drawing_title', ''),
            'plant': drawing_info.get('plant', ''),
        }
        
        # Get validated tags whitelist for this project
        from models.database import ValidatedTag
        validated_tags = db.query(ValidatedTag).filter(ValidatedTag.project_id == project_id).all()
        validated_tag_set = {vt.tag_number.upper().strip() for vt in validated_tags}
        
        # Extract all tags from the PDF
        result = pdf_parser.extract_all(d.file_path)
        tags = result.get("tags", [])
        
        # Build comprehensive tag report
        report_data = []
        filtered_tags = []  # Track filtered tags with reasons
        filtered_count = 0
        
        for tag in tags:
            tag_number = tag.get("tag_number", "")
            page_number = tag.get("page_number", 1)
            
            # Check if tag is in validated whitelist
            if tag_number.upper().strip() in validated_tag_set:
                # Tag is whitelisted - include it regardless of validation
                subsystem = tag.get("nearest_subsystem", "")
                tag_metadata = _parse_tag_plant_module(tag_number, subsystem, drawing_metadata)
                tag_type = _parse_tag_type(tag_number)
                if tag_type == 'Unknown':
                    tag_type = 'VALIDATED'  # Mark as validated if type unknown
                discipline = _classify_discipline(tag_number)
                
                report_data.append({
                    "plant": tag_metadata['plant'],
                    "module": tag_metadata['module'],
                    "tag_number": tag_number,
                    "tag_type": tag_type,
                    "tag_description": "",
                    "drawing_number": d.drawing_number,
                    "subsystem": subsystem,
                    "subsystem_color": tag.get("nearest_subsystem_color", ""),
                    "tag_color": tag.get("tag_fill_color", ""),
                    "discipline": discipline,
                    "page_number": page_number,
                    "x_position": round(tag.get("x", 0), 2),
                    "y_position": round(tag.get("y", 0), 2),
                })
                continue
            
            # Validate tag - record why it was filtered
            if not _is_valid_tag(tag_number):
                filtered_count += 1
                filtered_tags.append({
                    "tag_number": tag_number,
                    "page_number": page_number,
                    "reason": "Does not match PIMS tag format",
                    "tag_color": tag.get("tag_fill_color", ""),
                })
                continue
            
            subsystem = tag.get("nearest_subsystem", "")
            
            # Parse plant/module from the tag number itself
            tag_metadata = _parse_tag_plant_module(tag_number, subsystem, drawing_metadata)
            
            # Parse tag type from the tag number
            tag_type = _parse_tag_type(tag_number)
            
            # Skip tags with Unknown type that couldn't be parsed
            if tag_type == 'Unknown':
                filtered_count += 1
                filtered_tags.append({
                    "tag_number": tag_number,
                    "page_number": page_number,
                    "reason": "Unknown tag type (prefix not in PIMS specification)",
                    "tag_color": tag.get("tag_fill_color", ""),
                })
                continue
            
            # Classify discipline
            discipline = _classify_discipline(tag_number)
            
            report_data.append({
                "plant": tag_metadata['plant'],
                "module": tag_metadata['module'],
                "tag_number": tag_number,
                "tag_type": tag_type,
                "tag_description": "",  # Empty string instead of NaN
                "drawing_number": d.drawing_number,
                "subsystem": subsystem,
                "subsystem_color": tag.get("nearest_subsystem_color", ""),
                "tag_color": tag.get("tag_fill_color", ""),
                "discipline": discipline,
                "page_number": page_number,
                "x_position": round(tag.get("x", 0), 2),
                "y_position": round(tag.get("y", 0), 2),
            })
        
        # Log filtering stats
        print(f"Tag Extraction Report: {len(report_data)} valid tags extracted, {filtered_count} invalid tags filtered out")
        
        # Sort by page number, then by tag number
        report_data.sort(key=lambda x: (x['page_number'], x['tag_number']))
        filtered_tags.sort(key=lambda x: (x['page_number'], x['tag_number']))
        
        # Generate Excel file
        from services.excel_generator import generate_tag_report_excel
        from models.database import TagReport
        
        # Create reports directory
        reports_dir = Path(f"uploads/{project_id}/reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        excel_filename = f"tag_report_{d.drawing_number.replace('/', '_')}_{timestamp}.xlsx"
        excel_path = reports_dir / excel_filename
        
        # Generate Excel file
        generate_tag_report_excel(report_data, d.drawing_number, str(excel_path))
        
        # Save report metadata to database with filtered tags
        tag_report = TagReport(
            project_id=project_id,
            drawing_id=drawing_id,
            report_file_path=str(excel_path),
            drawing_number=d.drawing_number,
            total_tags=len(report_data),
            filtered_tags_count=filtered_count,
            filtered_tags_json=json.dumps(filtered_tags),
            total_pages=result.get("page_count", 0),
            generated_by=current_user.id
        )
        db.add(tag_report)
        db.commit()
        db.refresh(tag_report)
        
        # Calculate summary statistics
        summary = {
            "by_discipline": _group_count(report_data, 'discipline'),
            "by_tag_type": _group_count(report_data, 'tag_type'),
            "by_plant": _group_count(report_data, 'plant'),
            "by_module": _group_count(report_data, 'module'),
            "by_subsystem": _group_count(report_data, 'subsystem'),
            "by_page": _group_count(report_data, 'page_number'),
        }
        
        return {
            "report_id": tag_report.id,
            "drawing_id": drawing_id,
            "drawing_number": d.drawing_number,
            "total_tags": len(report_data),
            "filtered_tags_count": filtered_count,
            "total_pages": result.get("page_count", 0),
            "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
            "excel_file_saved": True,
            "tags": report_data,
            "summary": summary
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Report generation failed: {str(e)}")


def _group_count(data: list, field: str) -> dict:
    """Count occurrences of field values."""
    counts = {}
    for item in data:
        value = str(item.get(field, 'Unknown'))
        counts[value] = counts.get(value, 0) + 1
    return counts


@router.get("/{project_id}/reports")
def list_saved_reports(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all saved tag reports for a project."""
    from models.database import TagReport
    
    _require_member(project_id, current_user.id, db)
    
    reports = (
        db.query(TagReport)
        .filter(TagReport.project_id == project_id)
        .order_by(TagReport.generated_at.desc())
        .all()
    )
    
    return {
        "reports": [
            {
                "id": r.id,
                "drawing_id": r.drawing_id,
                "drawing_number": r.drawing_number,
                "total_tags": r.total_tags,
                "filtered_tags_count": r.filtered_tags_count or 0,
                "total_pages": r.total_pages,
                "generated_at": r.generated_at.isoformat() if r.generated_at else None,
                "file_path": r.report_file_path,
            }
            for r in reports
        ]
    }


@router.get("/{project_id}/reports/{report_id}/download")
def download_saved_report(
    project_id: str,
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download a saved tag report Excel file."""
    from models.database import TagReport
    
    _require_member(project_id, current_user.id, db)
    
    report = (
        db.query(TagReport)
        .filter(TagReport.id == report_id, TagReport.project_id == project_id)
        .first()
    )
    
    if not report or not report.report_file_path:
        raise HTTPException(status_code=404, detail="Report not found")
    
    file_path = Path(report.report_file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Report file not found on disk")
    
    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@router.delete("/{project_id}/reports/{report_id}")
def delete_saved_report(
    project_id: str,
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a saved tag report."""
    from models.database import TagReport
    
    _require_member(project_id, current_user.id, db)
    
    report = (
        db.query(TagReport)
        .filter(TagReport.id == report_id, TagReport.project_id == project_id)
        .first()
    )
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Delete file from disk
    if report.report_file_path:
        file_path = Path(report.report_file_path)
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception as e:
                print(f"Error deleting report file: {e}")
    
    # Delete database entry
    db.delete(report)
    db.commit()
    
    return {"message": "Report deleted successfully"}


@router.get("/{project_id}/reports/{report_id}/filtered-tags")
def get_filtered_tags(
    project_id: str,
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get filtered tags for a specific report."""
    from models.database import TagReport
    
    _require_member(project_id, current_user.id, db)
    
    report = (
        db.query(TagReport)
        .filter(TagReport.id == report_id, TagReport.project_id == project_id)
        .first()
    )
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Parse filtered tags JSON
    filtered_tags = []
    if report.filtered_tags_json:
        try:
            filtered_tags = json.loads(report.filtered_tags_json)
        except json.JSONDecodeError:
            filtered_tags = []
    
    return {
        "report_id": report_id,
        "filtered_tags_count": report.filtered_tags_count or 0,
        "filtered_tags": filtered_tags
    }


class ValidateTagBody(BaseModel):
    tag_number: str
    tag_type: str = ""
    notes: str = ""


@router.post("/{project_id}/validated-tags")
def validate_tag(
    project_id: str,
    body: ValidateTagBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a filtered tag as valid (add to whitelist)."""
    from models.database import ValidatedTag
    
    _require_member(project_id, current_user.id, db)
    
    # Check if already validated
    existing = (
        db.query(ValidatedTag)
        .filter(
            ValidatedTag.project_id == project_id,
            ValidatedTag.tag_number == body.tag_number.upper().strip()
        )
        .first()
    )
    
    if existing:
        return {"message": "Tag already validated", "validated_tag": {
            "id": existing.id,
            "tag_number": existing.tag_number,
            "tag_type": existing.tag_type,
            "validated_at": existing.validated_at.isoformat() if existing.validated_at else None,
        }}
    
    # Create new validated tag
    validated_tag = ValidatedTag(
        project_id=project_id,
        tag_number=body.tag_number.upper().strip(),
        tag_type=body.tag_type,
        notes=body.notes,
        validated_by=current_user.id
    )
    db.add(validated_tag)
    db.commit()
    db.refresh(validated_tag)
    
    return {
        "message": "Tag validated successfully",
        "validated_tag": {
            "id": validated_tag.id,
            "tag_number": validated_tag.tag_number,
            "tag_type": validated_tag.tag_type,
            "validated_at": validated_tag.validated_at.isoformat() if validated_tag.validated_at else None,
        }
    }


@router.get("/{project_id}/validated-tags")
def list_validated_tags(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all validated tags for a project."""
    from models.database import ValidatedTag
    
    _require_member(project_id, current_user.id, db)
    
    validated_tags = (
        db.query(ValidatedTag)
        .filter(ValidatedTag.project_id == project_id)
        .order_by(ValidatedTag.validated_at.desc())
        .all()
    )
    
    return {
        "validated_tags": [
            {
                "id": vt.id,
                "tag_number": vt.tag_number,
                "tag_type": vt.tag_type,
                "notes": vt.notes,
                "validated_by": vt.validated_by,
                "validated_at": vt.validated_at.isoformat() if vt.validated_at else None,
            }
            for vt in validated_tags
        ]
    }


@router.delete("/{project_id}/validated-tags/{validated_tag_id}")
def delete_validated_tag(
    project_id: str,
    validated_tag_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a tag from the validated whitelist."""
    from models.database import ValidatedTag
    
    _require_member(project_id, current_user.id, db)
    
    validated_tag = (
        db.query(ValidatedTag)
        .filter(ValidatedTag.id == validated_tag_id, ValidatedTag.project_id == project_id)
        .first()
    )
    
    if not validated_tag:
        raise HTTPException(status_code=404, detail="Validated tag not found")
    
    db.delete(validated_tag)
    db.commit()
    
    return {"message": "Validated tag removed successfully"}

