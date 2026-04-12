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
from models.database import Comparison, Drawing, ProjectMember, Project, Tag, User
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
