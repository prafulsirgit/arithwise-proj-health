"""Relationships router – query article ↔ concept mappings."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import ArticleConceptMapping, Concept, Article

router = APIRouter(prefix="/api/relationships", tags=["relationships"])


@router.get("")
def list_relationships(
    pmid: str | None = Query(None),
    concept_id: int | None = Query(None),
    match_type: str | None = Query(None),
    category: str | None = Query(None, description="Concept category filter"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = (
        db.query(ArticleConceptMapping, Concept, Article)
        .join(Concept, ArticleConceptMapping.concept_id == Concept.id)
        .join(Article, ArticleConceptMapping.article_pmid == Article.pmid)
    )

    if pmid:
        query = query.filter(ArticleConceptMapping.article_pmid == pmid)
    if concept_id:
        query = query.filter(ArticleConceptMapping.concept_id == concept_id)
    if match_type:
        query = query.filter(ArticleConceptMapping.match_type == match_type)
    if category:
        query = query.filter(Concept.category == category)

    total = query.count()
    rows = query.offset(offset).limit(limit).all()

    results = []
    for m, c, a in rows:
        results.append({
            "mapping_id": m.id,
            "article": {"pmid": a.pmid, "title": a.title[:80], "pub_year": a.pub_year},
            "concept": {"id": c.id, "label": c.label, "category": c.category},
            "match_type": m.match_type,
            "match_score": m.match_score,
            "matched_text": m.matched_text,
            "matched_via": m.matched_via,
        })

    return {"total": total, "offset": offset, "limit": limit, "results": results}


@router.get("/summary")
def relationship_summary(db: Session = Depends(get_db)):
    """Category breakdown of all relationships."""
    from sqlalchemy import func
    rows = (
        db.query(Concept.category, func.count(ArticleConceptMapping.id))
        .join(ArticleConceptMapping, Concept.id == ArticleConceptMapping.concept_id)
        .group_by(Concept.category)
        .all()
    )
    return {"by_category": {cat: count for cat, count in rows}}
