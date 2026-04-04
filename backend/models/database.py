from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func
import uuid

class Base(DeclarativeBase):
    pass

def gen_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    projects = relationship("ProjectMember", back_populates="user")

class Project(Base):
    __tablename__ = "projects"
    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    description = Column(Text)
    client = Column(String)
    facility_type = Column(String)  # WCF, WOC, BT1, BT2, BT3, KPAD, etc.
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    members = relationship("ProjectMember", back_populates="project")
    drawings = relationship("Drawing", back_populates="project")
    subsystems = relationship("Subsystem", back_populates="project")
    color_palettes = relationship("ColorPalette", back_populates="project")

class ProjectMember(Base):
    __tablename__ = "project_members"
    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    role = Column(String, default="editor")  # owner, editor, viewer
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    project = relationship("Project", back_populates="members")
    user = relationship("User", back_populates="projects")

class Subsystem(Base):
    __tablename__ = "subsystems"
    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    number = Column(String, nullable=False)       # e.g. "57-01"
    description = Column(String, nullable=False)  # e.g. "Potable Water Treatment Package"
    system_group = Column(String)                 # e.g. "57"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    project = relationship("Project", back_populates="subsystems")

class ColorPalette(Base):
    __tablename__ = "color_palettes"
    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    plant = Column(String, nullable=False)         # WCF, WOC, DrillSites, KPAD, Infrastructure
    drawing_type = Column(String, nullable=False)  # P&ID, SLD, PFD, Panel Schedule, Telecom, Automation
    subsystem_number = Column(String, nullable=False)
    subsystem_description = Column(String)
    hex_color = Column(String, nullable=False)     # e.g. "#0080FF"
    r = Column(Integer)
    g = Column(Integer)
    b = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    project = relationship("Project", back_populates="color_palettes")

class Drawing(Base):
    __tablename__ = "drawings"
    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    drawing_number = Column(String, nullable=False)  # e.g. "WILG-WF00-PRO-PID-WOD-00000-31006-01"
    drawing_title = Column(String)
    drawing_type = Column(String)   # P&ID, SLD, PFD, etc.
    plant = Column(String)          # WCF, WOC, BT1, etc.
    module = Column(String)
    revision = Column(String)
    is_systemized = Column(Boolean, default=False)
    status = Column(String, default="uploaded")  # uploaded, compared, systemized, approved, published
    systemized_pdf_path = Column(String)
    original_pdf_path = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    project = relationship("Project", back_populates="drawings")
    tags = relationship("Tag", back_populates="drawing")
    revisions = relationship("DrawingRevision", back_populates="drawing")

class DrawingRevision(Base):
    __tablename__ = "drawing_revisions"
    id = Column(String, primary_key=True, default=gen_uuid)
    drawing_id = Column(String, ForeignKey("drawings.id"), nullable=False)
    revision = Column(String, nullable=False)
    pdf_path = Column(String)
    is_systemized = Column(Boolean, default=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    drawing = relationship("Drawing", back_populates="revisions")

class Tag(Base):
    __tablename__ = "tags"
    id = Column(String, primary_key=True, default=gen_uuid)
    drawing_id = Column(String, ForeignKey("drawings.id"), nullable=False)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    tag_number = Column(String, nullable=False, index=True)
    tag_type = Column(String)        # MV, XV, SDV, P, T, etc.
    tag_description = Column(String)
    subsystem_number = Column(String, index=True)
    subsystem_source = Column(String)  # manual, ai_suggested, carried_over
    ai_confidence = Column(Float)
    ai_reasoning = Column(Text)
    status = Column(String, default="pending")  # pending, approved, flagged, excluded
    is_x_tag = Column(Boolean, default=False)
    page_x = Column(Float)
    page_y = Column(Float)
    page_number = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    drawing = relationship("Drawing", back_populates="tags")
    history = relationship("TagHistory", back_populates="tag")

class TagHistory(Base):
    __tablename__ = "tag_history"
    id = Column(String, primary_key=True, default=gen_uuid)
    tag_id = Column(String, ForeignKey("tags.id"), nullable=False)
    changed_by = Column(String, ForeignKey("users.id"))
    old_subsystem = Column(String)
    new_subsystem = Column(String)
    old_status = Column(String)
    new_status = Column(String)
    change_reason = Column(Text)
    changed_at = Column(DateTime(timezone=True), server_default=func.now())
    tag = relationship("Tag", back_populates="history")

class SystemizationRule(Base):
    __tablename__ = "systemization_rules"
    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    rule_type = Column(String)       # tag_pattern, line_routing, adjacency, manual
    pattern = Column(String)         # e.g. "MV-306XXXX" or "tag_prefix:MV-30"
    subsystem_number = Column(String)
    confidence = Column(Float, default=1.0)
    example_tag = Column(String)
    drawing_number = Column(String)
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
