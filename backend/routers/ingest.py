"""Ingestion trigger router – starts background ingestion jobs."""
from __future__ import annotations
import threading
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db, SessionLocal
from backend.models import IngestionJob
from backend.config import DEFAULT_PUBMED_QUERY, DEFAULT_MAX_ARTICLES, DEFAULT_ONTOLOGIES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ingest", tags=["ingestion"])

# Track running jobs globally (simple in-memory for prototype)
_running_jobs: dict[int, str] = {}


class PubMedIngestRequest(BaseModel):
    query: str = Field(default=DEFAULT_PUBMED_QUERY, description="PubMed search query")
    max_results: int = Field(default=DEFAULT_MAX_ARTICLES, ge=1, le=2000)


class BioPortalIngestRequest(BaseModel):
    ontologies: list[str] = Field(default=DEFAULT_ONTOLOGIES)
    max_concepts_per_ontology: int = Field(default=500, ge=10, le=5000)


class MappingRequest(BaseModel):
    limit_unmapped: int = Field(default=100, ge=1, le=1000)


# ────────────────────────────────────────────────────────────────────────────
# PubMed
# ────────────────────────────────────────────────────────────────────────────

@router.post("/pubmed")
def trigger_pubmed_ingestion(
    request: PubMedIngestRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    job = IngestionJob(job_type="pubmed", status="pending", query=request.query)
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id

    background_tasks.add_task(_run_pubmed_bg, job_id, request.query, request.max_results)
    return {"job_id": job_id, "status": "queued", "message": "PubMed ingestion started"}


def _run_pubmed_bg(job_id: int, query: str, max_results: int):
    from backend.ingestion.pubmed_ingestor import run_pubmed_ingestion
    db = SessionLocal()
    try:
        job = db.get(IngestionJob, job_id)
        run_pubmed_ingestion(db, query=query, max_results=max_results, job=job)
    except Exception as exc:
        logger.error(f"PubMed bg job {job_id} failed: {exc}", exc_info=True)
    finally:
        db.close()


# ────────────────────────────────────────────────────────────────────────────
# BioPortal
# ────────────────────────────────────────────────────────────────────────────

@router.post("/bioportal")
def trigger_bioportal_ingestion(
    request: BioPortalIngestRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    from backend.config import is_bioportal_configured
    if not is_bioportal_configured():
        raise HTTPException(
            status_code=400,
            detail="BioPortal API key not configured. Set BIOPORTAL_API_KEY in .env file."
        )

    job = IngestionJob(
        job_type="bioportal",
        status="pending",
        query=",".join(request.ontologies),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(
        _run_bioportal_bg, job.id, request.ontologies, request.max_concepts_per_ontology
    )
    return {"job_id": job.id, "status": "queued", "message": "BioPortal ingestion started"}


def _run_bioportal_bg(job_id: int, ontologies: list[str], max_concepts: int):
    from backend.ingestion.bioportal_ingestor import run_bioportal_ingestion
    db = SessionLocal()
    try:
        job = db.get(IngestionJob, job_id)
        run_bioportal_ingestion(db, ontology_acronyms=ontologies,
                                max_concepts_per_ontology=max_concepts, job=job)
    except Exception as exc:
        logger.error(f"BioPortal bg job {job_id} failed: {exc}", exc_info=True)
    finally:
        db.close()


# ────────────────────────────────────────────────────────────────────────────
# Concept Mapping
# ────────────────────────────────────────────────────────────────────────────

@router.post("/map")
def trigger_mapping(
    request: MappingRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    job = IngestionJob(job_type="mapping", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_run_mapping_bg, job.id, request.limit_unmapped)
    return {"job_id": job.id, "status": "queued", "message": "Concept mapping started"}


def _run_mapping_bg(job_id: int, limit: int):
    from backend.ingestion.mapper import run_mapping
    db = SessionLocal()
    try:
        job = db.get(IngestionJob, job_id)
        run_mapping(db, limit_unmapped=limit, job=job)
    except Exception as exc:
        logger.error(f"Mapping bg job {job_id} failed: {exc}", exc_info=True)
    finally:
        db.close()


# ────────────────────────────────────────────────────────────────────────────
# Status
# ────────────────────────────────────────────────────────────────────────────

@router.get("/jobs")
def list_jobs(limit: int = 20, db: Session = Depends(get_db)):
    jobs = db.query(IngestionJob).order_by(IngestionJob.started_at.desc()).limit(limit).all()
    return {"jobs": [j.to_dict() for j in jobs]}


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(IngestionJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


# ────────────────────────────────────────────────────────────────────────────
# Embeddings
# ────────────────────────────────────────────────────────────────────────────

@router.post("/embeddings")
def trigger_embedding_generation(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Generate semantic embeddings for all articles that don't have one yet."""
    job = IngestionJob(job_type="embeddings", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    background_tasks.add_task(_run_embeddings_bg, job.id)
    return {"job_id": job.id, "status": "queued", "message": "Embedding generation started"}


def _run_embeddings_bg(job_id: int):
    from backend.services import embedding_service
    db = SessionLocal()
    try:
        job = db.get(IngestionJob, job_id)
        if job:
            job.status = "running"
            db.commit()
        stats = embedding_service.generate_article_embeddings(db)
        if job:
            job.status = "completed"
            job.records_processed = stats.get("processed", 0)
            job.records_new = stats.get("processed", 0)
            from datetime import datetime
            job.completed_at = datetime.utcnow()
            db.commit()
    except Exception as exc:
        logger.error(f"Embedding bg job {job_id} failed: {exc}", exc_info=True)
        try:
            job = db.get(IngestionJob, job_id)
            if job:
                job.status = "failed"
                job.error_message = str(exc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()

