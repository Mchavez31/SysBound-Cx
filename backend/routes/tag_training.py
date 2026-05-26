import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database_connection import get_db
from models.database import Comparison, ProjectMember, ProjectReferenceDocument, ProjectTagVerdict, User
from routes.auth import get_current_user
from services import file_storage
from services.pdf_parser import normalize_tag_number

router = APIRouter()

_ALLOWED_DOC_ROLES = frozenset({"tagging_spec", "supplemental"})


def _require_member(project_id: str, user_id: str, db: Session) -> None:
    m = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        .first()
    )
    if not m:
        raise HTTPException(status_code=404, detail="Project not found")


def _require_editor(project_id: str, user_id: str, db: Session) -> None:
    m = (
        db.query(ProjectMember)
        .filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.role.in_(["owner", "editor"]),
        )
        .first()
    )
    if not m:
        raise HTTPException(status_code=403, detail="Not authorized")


class BulkVerdictItem(BaseModel):
    tag: str
    verdict: str = Field(description="valid or invalid")


class BulkVerdictBody(BaseModel):
    items: list[BulkVerdictItem]


@router.get("/{project_id}/tag-training/reference-docs")
def list_reference_docs(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_member(project_id, current_user.id, db)
    rows = (
        db.query(ProjectReferenceDocument)
        .filter(ProjectReferenceDocument.project_id == project_id)
        .order_by(ProjectReferenceDocument.uploaded_at.desc())
        .all()
    )
    return {
        "documents": [
            {
                "id": r.id,
                "doc_role": r.doc_role,
                "original_filename": r.original_filename,
                "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
            }
            for r in rows
        ]
    }


@router.post("/{project_id}/tag-training/reference-docs")
async def upload_reference_doc(
    project_id: str,
    file: UploadFile = File(...),
    doc_role: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_editor(project_id, current_user.id, db)
    role = (doc_role or "").strip().lower()
    if role not in _ALLOWED_DOC_ROLES:
        raise HTTPException(status_code=400, detail=f"doc_role must be one of {sorted(_ALLOWED_DOC_ROLES)}")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    fname = file.filename or "reference.pdf"
    safe_prefix = {"tagging_spec": "tagspec_", "supplemental": "supplemental_"}.get(role, "doc_")
    path = file_storage.save_upload(raw, project_id, safe_prefix + fname)

    doc = ProjectReferenceDocument(
        id=str(uuid.uuid4()),
        project_id=project_id,
        doc_role=role,
        file_path=path,
        original_filename=fname,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return {"id": doc.id, "doc_role": doc.doc_role, "original_filename": doc.original_filename}


@router.delete("/{project_id}/tag-training/reference-docs/{doc_id}")
def delete_reference_doc(
    project_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    _require_editor(project_id, current_user.id, db)
    row = (
        db.query(ProjectReferenceDocument)
        .filter(ProjectReferenceDocument.id == doc_id, ProjectReferenceDocument.project_id == project_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    file_storage.delete_upload_file(row.file_path)
    db.delete(row)
    db.commit()
    return {"success": True}


@router.get("/{project_id}/tag-training/verdicts")
def list_verdicts(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_member(project_id, current_user.id, db)
    rows = (
        db.query(ProjectTagVerdict)
        .filter(ProjectTagVerdict.project_id == project_id)
        .order_by(ProjectTagVerdict.updated_at.desc())
        .all()
    )
    return {
        "verdicts": [
            {
                "tag_normalized": r.tag_normalized,
                "verdict": r.verdict,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    }


@router.post("/{project_id}/tag-training/verdicts/bulk")
def bulk_set_verdicts(
    project_id: str,
    body: BulkVerdictBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_editor(project_id, current_user.id, db)
    if len(body.items) > 2000:
        raise HTTPException(status_code=400, detail="Too many items in one request")
    changed = 0
    for it in body.items:
        v = (it.verdict or "").strip().lower()
        if v not in ("valid", "invalid"):
            raise HTTPException(status_code=400, detail="Each verdict must be valid or invalid")
        nk = normalize_tag_number(it.tag)
        if not nk or len(nk) < 3:
            continue
        row = (
            db.query(ProjectTagVerdict)
            .filter(ProjectTagVerdict.project_id == project_id, ProjectTagVerdict.tag_normalized == nk)
            .first()
        )
        if row:
            if row.verdict != v:
                row.verdict = v
                changed += 1
        else:
            db.add(
                ProjectTagVerdict(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    tag_normalized=nk,
                    verdict=v,
                )
            )
            changed += 1
    db.commit()
    return {"success": True, "records_touched": changed}


def _comparison_row_tags(comp: Comparison) -> list[dict[str, Any]]:
    """Extract unique tags with their position data from comparison result."""
    if not comp or not comp.result_json:
        return []
    try:
        data = json.loads(comp.result_json)
    except (TypeError, json.JSONDecodeError):
        return []
    rows = data.get("rows") or []
    tags: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        tn = r.get("tag_number")
        if not tn:
            continue
        s = normalize_tag_number(str(tn))
        if s not in seen:
            seen.add(s)
            # Prefer side B (new drawing) if available, else side A
            tag_info: dict[str, Any] = {"tag": s}
            if r.get("page_b") and r.get("tag_x_b") is not None and r.get("tag_y_b") is not None:
                tag_info["page"] = int(r.get("page_b"))
                tag_info["x"] = float(r.get("tag_x_b"))
                tag_info["y"] = float(r.get("tag_y_b"))
                tag_info["drawing_id"] = r.get("drawing_id_b")
            elif r.get("page_a") and r.get("tag_x_a") is not None and r.get("tag_y_a") is not None:
                tag_info["page"] = int(r.get("page_a"))
                tag_info["x"] = float(r.get("tag_x_a"))
                tag_info["y"] = float(r.get("tag_y_a"))
                tag_info["drawing_id"] = r.get("drawing_id_a")
            tags.append(tag_info)
    return tags


@router.get("/{project_id}/tag-training/review-candidates")
def review_candidates(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Unique tag texts from this project's latest completed comparison, plus saved verdict labels and position data.
    """
    _require_member(project_id, current_user.id, db)
    comp = (
        db.query(Comparison)
        .filter(Comparison.project_id == project_id, Comparison.status == "complete")
        .order_by(Comparison.run_at.desc().nullslast(), Comparison.id.desc())
        .first()
    )
    tag_infos = _comparison_row_tags(comp) if comp else []
    verdict_rows = db.query(ProjectTagVerdict).filter(ProjectTagVerdict.project_id == project_id).all()
    verdict_map = {r.tag_normalized: r.verdict for r in verdict_rows}
    return {
        "comparison_id": comp.id if comp else None,
        "project_id": project_id,
        "tags": tag_infos,
        "verdicts": verdict_map,
    }
