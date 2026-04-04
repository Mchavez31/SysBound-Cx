from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database_connection import get_db
from models.database import User
from routes.auth import get_current_user

router = APIRouter()

@router.get("/{project_id}")
def list_drawings(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return []  # Phase 2 — PDF upload and processing
