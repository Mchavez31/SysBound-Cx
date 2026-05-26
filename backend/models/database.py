from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, JSON, UniqueConstraint
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
    facility_type = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    members = relationship("ProjectMember", back_populates="project")
    drawings = relationship("Drawing", back_populates="project")
    subsystems = relationship("Subsystem", back_populates="project")
    color_palettes = relationship("ColorPalette", back_populates="project")
    comparisons = relationship("Comparison", back_populates="project")
    reference_documents = relationship("ProjectReferenceDocument", back_populates="project")
    tag_verdicts = relationship("ProjectTagVerdict", back_populates="project")

class ProjectReferenceDocument(Base):
    """
    Project tagging spec / supplemental documents. Files persist on disk until the user removes them.
    """
    __tablename__ = "project_reference_documents"
    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    doc_role = Column(String, nullable=False)  # tagging_spec | supplemental
    file_path = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    project = relationship("Project", back_populates="reference_documents")

class ProjectTagVerdict(Base):
    """Training labels for tag strings — invalid verdicts suppress extraction on future comparisons."""
    __tablename__ = "project_tag_verdicts"
    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    tag_normalized = Column(String, nullable=False)
    verdict = Column(String, nullable=False)  # valid | invalid
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("project_id", "tag_normalized", name="uq_project_tag_verdict"),)
    project = relationship("Project", back_populates="tag_verdicts")

class ProjectMember(Base):
    __tablename__ = "project_members"
    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    role = Column(String, default="editor")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    project = relationship("Project", back_populates="members")
    user = relationship("User", back_populates="projects")

class Subsystem(Base):
    __tablename__ = "subsystems"
    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    number = Column(String, nullable=False)
    description = Column(String, nullable=False)
    system_group = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    project = relationship("Project", back_populates="subsystems")

class ColorPalette(Base):
    __tablename__ = "color_palettes"
    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    plant = Column(String, nullable=False)
    drawing_type = Column(String, nullable=False)
    subsystem_number = Column(String, nullable=False)
    subsystem_description = Column(String)
    hex_color = Column(String, nullable=False)
    r = Column(Integer)
    g = Column(Integer)
    b = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    project = relationship("Project", back_populates="color_palettes")

class Drawing(Base):
    __tablename__ = "drawings"
    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    drawing_number = Column(String, nullable=False)
    drawing_title = Column(String)
    drawing_type = Column(String)
    plant = Column(String)
    module = Column(String)
    revision = Column(String)
    is_systemized = Column(Boolean, default=False)
    status = Column(String, default="uploaded")
    systemized_pdf_path = Column(String)
    original_pdf_path = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    drawing_role = Column(String, default="new_engineering")
    file_path = Column(String)
    file_name = Column(String)
    page_count = Column(Integer)
    detected_drawing_number = Column(String)
    detected_drawing_title = Column(String)
    detected_drawing_type = Column(String)
    detected_plant = Column(String)
    detected_revision = Column(String)
    extraction_error = Column(Text)

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

class Comparison(Base):
    __tablename__ = "comparisons"
    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    drawing_id_a = Column(String, ForeignKey("drawings.id"), nullable=False)
    drawing_id_b = Column(String, ForeignKey("drawings.id"), nullable=False)
    comparison_type = Column(String, nullable=False)
    status = Column(String, default="pending")
    run_at = Column(DateTime(timezone=True))
    total_new = Column(Integer, default=0)
    total_removed = Column(Integer, default=0)
    total_unchanged = Column(Integer, default=0)
    total_subsystem_changes = Column(Integer, default=0)
    result_json = Column(Text)
    # Polled by GET …/progress; stored in DB so multi-worker / any process sees the same values.
    progress_percent = Column(Integer, default=0)
    progress_message = Column(String, default="")

    project = relationship("Project", back_populates="comparisons")

class Tag(Base):
    __tablename__ = "tags"
    id = Column(String, primary_key=True, default=gen_uuid)
    drawing_id = Column(String, ForeignKey("drawings.id"), nullable=False)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    comparison_id = Column(String, ForeignKey("comparisons.id"), nullable=True)
    tag_number = Column(String, nullable=False, index=True)
    tag_type = Column(String)
    tag_category = Column(String)
    tag_description = Column(String)
    subsystem_number = Column(String, index=True)
    subsystem_source = Column(String)
    previous_subsystem = Column(String)
    ai_confidence = Column(Float)
    ai_reasoning = Column(Text)
    status = Column(String, default="pending")
    is_x_tag = Column(Boolean, default=False)
    page_x = Column(Float)
    page_y = Column(Float)
    page_number = Column(Integer)
    color_in_drawing = Column(String)
    action_needed = Column(String)
    change_type = Column(String)
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

class TagReport(Base):
    """Saved tag extraction reports with Excel exports."""
    __tablename__ = "tag_reports"
    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    drawing_id = Column(String, ForeignKey("drawings.id"), nullable=False)
    report_file_path = Column(String, nullable=False)  # Path to saved Excel file
    drawing_number = Column(String)
    total_tags = Column(Integer)
    filtered_tags_count = Column(Integer, default=0)  # Count of filtered/rejected tags
    filtered_tags_json = Column(Text)  # JSON array of filtered tags with reasons
    total_pages = Column(Integer)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    generated_by = Column(String, ForeignKey("users.id"))


class ValidatedTag(Base):
    """User-validated tags that should bypass automatic filtering."""
    __tablename__ = "validated_tags"
    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    tag_number = Column(String, nullable=False)  # The validated tag
    tag_type = Column(String)  # User-specified tag type
    validated_by = Column(String, ForeignKey("users.id"))
    validated_at = Column(DateTime(timezone=True), server_default=func.now())
    notes = Column(Text)  # Optional user notes about why this tag is valid

class SystemizationRule(Base):
    __tablename__ = "systemization_rules"
    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    rule_type = Column(String)
    pattern = Column(String)
    subsystem_number = Column(String)
    confidence = Column(Float, default=1.0)
    example_tag = Column(String)
    drawing_number = Column(String)
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
