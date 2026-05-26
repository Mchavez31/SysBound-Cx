"""
Add tag_reports table for saved Excel reports.
Run: python db_migrate_tag_reports.py
"""
from database_connection import engine
from models.database import Base, TagReport

def migrate():
    print("Creating tag_reports table...")
    TagReport.__table__.create(engine, checkfirst=True)
    print("Migration complete!")

if __name__ == "__main__":
    migrate()
