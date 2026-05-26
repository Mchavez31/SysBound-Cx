"""Add missing columns on SQLite for existing databases (non-destructive)."""
from sqlalchemy import inspect, text


def migrate_sqlite(engine) -> None:
    if "sqlite" not in str(engine.url):
        return

    import models.database  # noqa: F401 — register ORM subclasses before creating missing tables
    from models.database import Base

    Base.metadata.create_all(bind=engine)

    insp = inspect(engine)
    tables = insp.get_table_names()

    def add_columns(table: str, columns: list[tuple[str, str]]) -> None:
        if table not in tables:
            return
        existing = {c["name"] for c in insp.get_columns(table)}
        with engine.connect() as conn:
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {name} {ddl}'))
                    conn.commit()
                    existing.add(name)

    add_columns(
        "drawings",
        [
            ("drawing_role", "VARCHAR DEFAULT 'new_engineering'"),
            ("file_path", "VARCHAR"),
            ("file_name", "VARCHAR"),
            ("page_count", "INTEGER"),
            ("detected_drawing_number", "VARCHAR"),
            ("detected_drawing_title", "VARCHAR"),
            ("detected_drawing_type", "VARCHAR"),
            ("detected_plant", "VARCHAR"),
            ("detected_revision", "VARCHAR"),
            ("extraction_error", "TEXT"),
        ],
    )
    insp = inspect(engine)
    add_columns(
        "tags",
        [
            ("comparison_id", "VARCHAR"),
            ("tag_category", "VARCHAR"),
            ("previous_subsystem", "VARCHAR"),
            ("color_in_drawing", "VARCHAR"),
            ("action_needed", "VARCHAR"),
            ("change_type", "VARCHAR"),
        ],
    )
    insp = inspect(engine)
    add_columns(
        "comparisons",
        [
            ("progress_percent", "INTEGER DEFAULT 0"),
            ("progress_message", "VARCHAR DEFAULT ''"),
        ],
    )
    insp = inspect(engine)
    add_columns(
        "tag_reports",
        [
            ("filtered_tags_count", "INTEGER DEFAULT 0"),
            ("filtered_tags_json", "TEXT"),
        ],
    )
