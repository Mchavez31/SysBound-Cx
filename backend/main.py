from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from database_connection import engine, Base
from db_migrate import migrate_sqlite
from routes import auth, projects, drawings, tags, palettes, subsystems

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_sqlite(engine)
    yield

app = FastAPI(
    title="Systemization Platform API",
    description="Multi-project engineering drawing systemization tool",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(drawings.router, prefix="/api/drawings", tags=["drawings"])
app.include_router(tags.router, prefix="/api/tags", tags=["tags"])
app.include_router(palettes.router, prefix="/api/palettes", tags=["palettes"])
app.include_router(subsystems.router, prefix="/api/subsystems", tags=["subsystems"])

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "systemization-platform"}
