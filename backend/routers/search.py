"""
Search router — unified semantic search across publications, concepts, and entities.

Endpoints:
  GET /api/search/unified?q=...   — search everything, return categorized results
  GET /api/search/similar/{pmid}  — semantically similar articles
  GET /api/search/trending        — trending oncology topics
  GET /api/search/suggest?q=...   — fast autocomplete suggestions
"""
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from backend.database import get_db
from backend.models import (
    Article, Author, ArticleAuthor,
    Concept, Ontology, ArticleConceptMapping,
    DiseaseEntity, DrugEntity, BiomarkerEntity,
)

router = APIRouter(prefix="/api/search", tags=["search"])
logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Unified Search
# ────────────────────────────────────────────────────────────────────────────

@router.get("/unified")
def unified_search(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(10, le=50),
    db: Session = Depends(get_db),
):
    """
    Search across publications AND ontology concepts simultaneously.
    Returns categorized results: publications, diseases, drugs, biomarkers, concepts.
    """
    search = f"%{q}%"
    q_lower = q.lower()

    # ── Publications ─────────────────────────────────────────────────────
    pub_query = db.query(Article).filter(
        or_(
            Article.title.ilike(search),
            Article.abstract.ilike(search),
            Article.keywords_json.ilike(search),
            Article.mesh_terms_json.ilike(search),
            Article.pmid == q.strip(),
        )
    ).order_by(Article.pub_year.desc()).limit(limit)

    publications = [
        {
            "pmid": a.pmid,
            "title": a.title,
            "journal": a.journal,
            "pub_year": a.pub_year,
            "abstract_snippet": (a.abstract or "")[:220],
            "doi": a.doi,
        }
        for a in pub_query.all()
    ]

    # ── Concepts (all categories) ────────────────────────────────────────
    concept_query = db.query(Concept).filter(
        or_(
            Concept.label.ilike(search),
            Concept.synonyms_json.ilike(search),
            Concept.definition.ilike(search),
        )
    ).limit(limit * 2)

    all_concepts = concept_query.all()

    diseases, drugs, biomarkers, general_concepts = [], [], [], []
    for c in all_concepts:
        entry = {
            "id": c.id,
            "label": c.label,
            "category": c.category,
            "definition": (c.definition or "")[:150],
            "ontology": c.ontology.acronym if c.ontology else "",
        }
        if c.category == "disease" and len(diseases) < limit:
            diseases.append(entry)
        elif c.category == "drug" and len(drugs) < limit:
            drugs.append(entry)
        elif c.category == "biomarker" and len(biomarkers) < limit:
            biomarkers.append(entry)
        elif len(general_concepts) < limit:
            general_concepts.append(entry)

    # ── Related article counts for top concepts ───────────────────────────
    for cat_list in [diseases, drugs, biomarkers, general_concepts]:
        for entry in cat_list:
            entry["article_count"] = (
                db.query(func.count(ArticleConceptMapping.id))
                .filter(ArticleConceptMapping.concept_id == entry["id"])
                .scalar() or 0
            )

    total_results = (
        len(publications) + len(diseases) + len(drugs) +
        len(biomarkers) + len(general_concepts)
    )

    return {
        "query": q,
        "total_results": total_results,
        "publications": publications,
        "diseases": diseases,
        "drugs": drugs,
        "biomarkers": biomarkers,
        "concepts": general_concepts,
    }


# ────────────────────────────────────────────────────────────────────────────
# Semantic Similarity
# ────────────────────────────────────────────────────────────────────────────

@router.get("/similar/{pmid}")
def similar_articles(
    pmid: str,
    limit: int = Query(6, le=20),
    db: Session = Depends(get_db),
):
    """Return articles semantically similar to the given PMID."""
    article = db.get(Article, pmid)
    if not article:
        raise HTTPException(status_code=404, detail=f"Article {pmid} not found")

    from backend.services import embedding_service
    results = embedding_service.find_similar_articles(db, pmid, limit=limit)
    return {
        "pmid": pmid,
        "title": article.title,
        "similar_articles": results,
    }


# ────────────────────────────────────────────────────────────────────────────
# Trending Topics
# ────────────────────────────────────────────────────────────────────────────

@router.get("/trending")
def trending_topics(
    days: int = Query(90, ge=7, le=3650, description="Rolling window in days"),
    limit: int = Query(20, le=50),
    db: Session = Depends(get_db),
):
    """Return trending oncology topics from recently ingested publications."""
    from backend.services import trending_service
    topics = trending_service.get_trending_topics(db, days=days, limit=limit)
    total_articles = db.query(Article).count()
    return {
        "days": days,
        "total_articles_analyzed": total_articles,
        "topics": topics,
    }


# ────────────────────────────────────────────────────────────────────────────
# Autocomplete / Suggestions
# ────────────────────────────────────────────────────────────────────────────

@router.get("/suggest")
def search_suggestions(
    q: str = Query(..., min_length=2),
    limit: int = Query(8, le=20),
    db: Session = Depends(get_db),
):
    """Fast autocomplete: returns article titles and concept labels."""
    search = f"{q}%"   # prefix match for speed
    search_any = f"%{q}%"

    # Article title suggestions
    articles = (
        db.query(Article.pmid, Article.title, Article.pub_year)
        .filter(Article.title.ilike(search_any))
        .order_by(Article.pub_year.desc())
        .limit(limit)
        .all()
    )

    # Concept label suggestions
    concepts = (
        db.query(Concept.id, Concept.label, Concept.category)
        .filter(Concept.label.ilike(search))
        .limit(limit)
        .all()
    )

    return {
        "query": q,
        "articles": [{"pmid": p, "title": t, "pub_year": y} for p, t, y in articles],
        "concepts": [{"id": i, "label": l, "category": c} for i, l, c in concepts],
    }


# ────────────────────────────────────────────────────────────────────────────
# Highly Cited / Featured Publications
# ────────────────────────────────────────────────────────────────────────────

@router.get("/featured")
def featured_publications(
    limit: int = Query(8, le=20),
    db: Session = Depends(get_db),
):
    """Return publications with the most concept mappings — proxy for importance."""
    rows = (
        db.query(
            Article.pmid,
            Article.title,
            Article.journal,
            Article.pub_year,
            Article.abstract,
            func.count(ArticleConceptMapping.id).label("mapping_count"),
        )
        .join(ArticleConceptMapping, Article.pmid == ArticleConceptMapping.article_pmid)
        .group_by(Article.pmid)
        .order_by(func.count(ArticleConceptMapping.id).desc())
        .limit(limit)
        .all()
    )

    return {
        "publications": [
            {
                "pmid": pmid,
                "title": title,
                "journal": journal,
                "pub_year": pub_year,
                "abstract_snippet": (abstract or "")[:200],
                "mapping_count": mc,
            }
            for pmid, title, journal, pub_year, abstract, mc in rows
        ]
    }
