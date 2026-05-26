import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from database_connection import engine, Base
from db_migrate import migrate_sqlite
from routes import auth, projects, drawings, tags, palettes, subsystems, tag_training

@asynccontextmanager
async def lifespan(app: FastAPI):
    import models.database  # noqa: F401 — ensure every ORM model is registered on Base.metadata before create_all
    Base.metadata.create_all(bind=engine)
    migrate_sqlite(engine)
    yield

app = FastAPI(
    title="SysBound Cx API",
    description="Multi-project engineering drawing commissioning and systemization tool",
    version="1.0.0",
    lifespan=lifespan,
)

def _cors_origins() -> list[str]:
    base = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    extra = os.getenv("FRONTEND_URL", "").strip()
    if extra:
        base.append(extra.rstrip("/"))
    return base


# Regex allows dev ports, GitHub Pages, and Vercel frontends.
_CORS_ORIGIN_REGEX = (
    r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
    r"|https://[a-zA-Z0-9][-a-zA-Z0-9]*\.github\.io$"
    r"|https://[a-zA-Z0-9][-a-zA-Z0-9]*\.vercel\.app$"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX", _CORS_ORIGIN_REGEX),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(tag_training.router, prefix="/api/projects", tags=["tag-training"])
app.include_router(drawings.router, prefix="/api/drawings", tags=["drawings"])
app.include_router(tags.router, prefix="/api/tags", tags=["tags"])
app.include_router(palettes.router, prefix="/api/palettes", tags=["palettes"])
app.include_router(subsystems.router, prefix="/api/subsystems", tags=["subsystems"])

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "sysbound-cx"}
