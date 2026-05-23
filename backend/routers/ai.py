"""
AI router — Groq-powered publication summaries with caching.

Endpoints:
  GET  /api/ai/summarize/{pmid}  — get cached or generate new summary
  POST /api/ai/summarize/{pmid}  — force-regenerate summary
  GET  /api/ai/status            — Groq availability status
"""
from __future__ import annotations
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Article, AIPublicationSummary, Concept, ArticleConceptMapping

router = APIRouter(prefix="/api/ai", tags=["ai"])
logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Status
# ────────────────────────────────────────────────────────────────────────────

@router.get("/status")
def ai_status():
    """Return Groq availability and embedding model status."""
    from backend.config import is_groq_configured, GROQ_MODEL, EMBEDDING_MODEL_NAME
    from backend.services import embedding_service
    return {
        "groq_configured": is_groq_configured(),
        "groq_model": GROQ_MODEL if is_groq_configured() else None,
        "embedding_model": EMBEDDING_MODEL_NAME,
        "embedding_available": embedding_service.is_available(),
    }


# ────────────────────────────────────────────────────────────────────────────
# Summary — GET (cached)
# ────────────────────────────────────────────────────────────────────────────

@router.get("/summarize/{pmid}")
def get_summary(pmid: str, db: Session = Depends(get_db)):
    """Return cached AI summary if available, otherwise indicate it hasn't been generated."""
    article = db.get(Article, pmid)
    if not article:
        raise HTTPException(status_code=404, detail=f"Article {pmid} not found")

    cached = db.query(AIPublicationSummary).filter_by(article_pmid=pmid).first()
    if cached:
        return {
            "pmid": pmid,
            "cached": True,
            "summary": cached.summary_text,
            "model_used": cached.model_used,
            "created_at": cached.created_at.isoformat() if cached.created_at else None,
        }

    return {"pmid": pmid, "cached": False, "summary": None}


# ────────────────────────────────────────────────────────────────────────────
# Summary — POST (generate / regenerate)
# ────────────────────────────────────────────────────────────────────────────

@router.post("/summarize/{pmid}")
def generate_summary(pmid: str, db: Session = Depends(get_db)):
    """Generate (or regenerate) an AI summary for a publication using Groq."""
    article = db.get(Article, pmid)
    if not article:
        raise HTTPException(status_code=404, detail=f"Article {pmid} not found")

    # Gather concept labels for richer context
    concept_rows = (
        db.query(Concept.label, Concept.category)
        .join(ArticleConceptMapping, Concept.id == ArticleConceptMapping.concept_id)
        .filter(ArticleConceptMapping.article_pmid == pmid)
        .limit(15)
        .all()
    )
    concept_labels = [label for label, _ in concept_rows]

    from backend.services import groq_service
    result = groq_service.summarize_publication(
        title=article.title or "",
        abstract=article.abstract or "",
        mesh_terms=article.mesh_terms,
        concept_labels=concept_labels,
        pmid=pmid,
    )

    if not result["success"]:
        raise HTTPException(
            status_code=503 if "key" not in (result.get("error") or "").lower() else 400,
            detail=result["error"],
        )

    # Cache / upsert
    existing = db.query(AIPublicationSummary).filter_by(article_pmid=pmid).first()
    if existing:
        existing.summary_text = result["summary"]
        existing.model_used = result["model"] or ""
        existing.created_at = datetime.utcnow()
    else:
        summary_obj = AIPublicationSummary(
            article_pmid=pmid,
            summary_text=result["summary"],
            model_used=result["model"] or "",
        )
        db.add(summary_obj)
    db.commit()

    return {
        "pmid": pmid,
        "cached": False,
        "summary": result["summary"],
        "model_used": result["model"],
        "created_at": datetime.utcnow().isoformat(),
    }
