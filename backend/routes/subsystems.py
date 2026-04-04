from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from database_connection import get_db
from models.database import Subsystem, ProjectMember, User
from routes.auth import get_current_user
import openpyxl, io

router = APIRouter()

class SubsystemCreate(BaseModel):
    number: str
    description: str
    system_group: Optional[str] = None

def check_access(project_id, user_id, db):
    m = db.query(ProjectMember).filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id).first()
    if not m:
        raise HTTPException(status_code=403, detail="Not authorized")
    return m

@router.get("/{project_id}")
def list_subsystems(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    check_access(project_id, current_user.id, db)
    subs = db.query(Subsystem).filter(Subsystem.project_id == project_id, Subsystem.is_active == True).order_by(Subsystem.number).all()
    return [{"id": s.id, "number": s.number, "description": s.description, "system_group": s.system_group} for s in subs]

@router.post("/{project_id}")
def create_subsystem(project_id: str, req: SubsystemCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    m = check_access(project_id, current_user.id, db)
    if m.role not in ["owner", "editor"]:
        raise HTTPException(status_code=403, detail="Editors and owners only")
    sub = Subsystem(project_id=project_id, number=req.number, description=req.description, system_group=req.system_group)
    db.add(sub); db.commit(); db.refresh(sub)
    return {"id": sub.id, "number": sub.number, "description": sub.description}

@router.post("/{project_id}/upload")
async def upload_subsystem_register(project_id: str, file: UploadFile = File(...),
                                     db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    m = check_access(project_id, current_user.id, db)
    if m.role not in ["owner", "editor"]:
        raise HTTPException(status_code=403, detail="Editors and owners only")
    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active
    entries = []
    for row in ws.iter_rows(min_row=2, max_row=500, max_col=3, values_only=True):
        num, desc, group = (str(row[0]).strip() if row[0] else None), (str(row[1]).strip() if row[1] else ""), (str(row[2]).strip() if len(row) > 2 and row[2] else None)
        if num and num not in ("Subsystem", "nan", "None"):
            entries.append({"number": num, "description": desc, "system_group": group})
    db.query(Subsystem).filter(Subsystem.project_id == project_id).delete()
    for e in entries:
        db.add(Subsystem(project_id=project_id, **e))
    db.commit()
    return {"success": True, "imported": len(entries)}

@router.delete("/{project_id}/{subsystem_id}")
def delete_subsystem(project_id: str, subsystem_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    m = check_access(project_id, current_user.id, db)
    if m.role not in ["owner", "editor"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    sub = db.query(Subsystem).filter(Subsystem.id == subsystem_id, Subsystem.project_id == project_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Not found")
    sub.is_active = False; db.commit()
    return {"success": True}
