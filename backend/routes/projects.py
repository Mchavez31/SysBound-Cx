from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from database_connection import get_db
from models.database import Project, ProjectMember, User
from routes.auth import get_current_user

router = APIRouter()

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    client: Optional[str] = None
    facility_type: Optional[str] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    client: Optional[str] = None
    facility_type: Optional[str] = None

def project_to_dict(p: Project, role: str = "owner"):
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "client": p.client,
        "facility_type": p.facility_type,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "role": role,
        "drawing_count": len(p.drawings) if p.drawings else 0,
        "member_count": len(p.members) if p.members else 0,
    }

@router.get("")
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    memberships = db.query(ProjectMember).filter(ProjectMember.user_id == current_user.id).all()
    result = []
    for m in memberships:
        project = db.query(Project).filter(Project.id == m.project_id, Project.is_active == True).first()
        if project:
            result.append(project_to_dict(project, m.role))
    return result

@router.post("")
def create_project(req: ProjectCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = Project(
        name=req.name,
        description=req.description,
        client=req.client,
        facility_type=req.facility_type,
    )
    db.add(project)
    db.flush()
    member = ProjectMember(project_id=project.id, user_id=current_user.id, role="owner")
    db.add(member)
    db.commit()
    db.refresh(project)
    return project_to_dict(project, "owner")

@router.get("/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    membership = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == current_user.id
    ).first()
    if not membership:
        raise HTTPException(status_code=404, detail="Project not found")
    project = db.query(Project).filter(Project.id == project_id).first()
    return project_to_dict(project, membership.role)

@router.patch("/{project_id}")
def update_project(project_id: str, req: ProjectUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    membership = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == current_user.id,
        ProjectMember.role.in_(["owner", "editor"])
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Not authorized")
    project = db.query(Project).filter(Project.id == project_id).first()
    for field, value in req.model_dump(exclude_none=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project_to_dict(project, membership.role)

@router.delete("/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    membership = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == current_user.id,
        ProjectMember.role == "owner"
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Only the owner can delete a project")
    project = db.query(Project).filter(Project.id == project_id).first()
    project.is_active = False
    db.commit()
    return {"success": True}

@router.post("/{project_id}/members")
def invite_member(project_id: str, email: str, role: str = "editor",
                  db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    owner_check = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == current_user.id,
        ProjectMember.role == "owner"
    ).first()
    if not owner_check:
        raise HTTPException(status_code=403, detail="Only owners can invite members")
    invitee = db.query(User).filter(User.email == email).first()
    if not invitee:
        raise HTTPException(status_code=404, detail="User not found — they need to register first")
    existing = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == invitee.id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="User is already a member")
    member = ProjectMember(project_id=project_id, user_id=invitee.id, role=role)
    db.add(member)
    db.commit()
    return {"success": True, "member": {"name": invitee.name, "email": invitee.email, "role": role}}
