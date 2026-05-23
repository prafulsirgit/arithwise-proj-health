"""
FastAPI application entry point for the Oncology Knowledge Repository.
"""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.database import init_db
from backend.routers import publications, ontologies, relationships, ingest, analytics, search, ai
from backend.config import DEBUG

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Oncology Knowledge Repository",
    description="Integrated platform combining PubMed publications with NCBO BioPortal ontologies",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────
app.include_router(publications.router)
app.include_router(ontologies.router)
app.include_router(relationships.router)
app.include_router(ingest.router)
app.include_router(analytics.router)
app.include_router(search.router)
app.include_router(ai.router)

# ── Health check (must be before the SPA catch-all) ───────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "Oncology Knowledge Repository"}


# ── Admin: database reset ──────────────────────────────────────────────────
@app.post("/api/admin/reset-db")
def reset_database():
    """Drop all tables and recreate them empty. USE WITH CAUTION."""
    from backend.database import Base, engine
    from backend import models  # noqa: ensure all models are registered
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    logger.warning("Database was RESET — all data deleted.")
    return {"status": "ok", "message": "Database cleared and recreated successfully."}


@app.post("/api/admin/clear-table/{table_name}")
def clear_table(table_name: str):
    """Truncate a single table by name."""
    from backend.database import SessionLocal, Base, engine
    allowed = {t.name for t in Base.metadata.tables.values()}
    if table_name not in allowed:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown table '{table_name}'. Allowed: {sorted(allowed)}")
    db = SessionLocal()
    try:
        db.execute(Base.metadata.tables[table_name].delete())
        db.commit()
        logger.warning(f"Table '{table_name}' was cleared.")
        return {"status": "ok", "message": f"Table '{table_name}' cleared."}
    finally:
        db.close()


# ── Startup ────────────────────────────────────────────────────────────────
@app.on_event("startup")
def on_startup():
    logger.info("Initialising database…")
    init_db()
    logger.info("Oncology Knowledge Repository started ✓")


# ── Static frontend ────────────────────────────────────────────────────────
# NOTE: The SPA catch-all MUST be registered last so it never shadows /api/* routes.
_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def serve_index():
        return FileResponse(str(_FRONTEND_DIR / "index.html"))

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        # Never serve HTML for API paths — return 404 JSON instead
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"API route /{full_path} not found")
        file_path = _FRONTEND_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_FRONTEND_DIR / "index.html"))


# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    from backend.config import HOST, PORT
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=DEBUG)

