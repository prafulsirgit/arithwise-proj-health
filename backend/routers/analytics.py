"""Analytics router – counts, charts, and insight data."""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database import get_db
from backend.models import (
    Article, Concept, Ontology, Author, ArticleAuthor,
    ArticleConceptMapping, IngestionJob, DiseaseEntity, DrugEntity, BiomarkerEntity
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    return {
        "total_articles": db.query(Article).count(),
        "total_concepts": db.query(Concept).count(),
        "total_ontologies": db.query(Ontology).count(),
        "total_authors": db.query(Author).count(),
        "total_mappings": db.query(ArticleConceptMapping).count(),
        "total_diseases": db.query(DiseaseEntity).count(),
        "total_drugs": db.query(DrugEntity).count(),
        "total_biomarkers": db.query(BiomarkerEntity).count(),
    }


@router.get("/publications-by-year")
def publications_by_year(db: Session = Depends(get_db)):
    rows = (
        db.query(Article.pub_year, func.count(Article.pmid))
        .filter(Article.pub_year.isnot(None))
        .group_by(Article.pub_year)
        .order_by(Article.pub_year)
        .all()
    )
    return {"data": [{"year": yr, "count": cnt} for yr, cnt in rows]}


@router.get("/top-concepts")
def top_concepts(limit: int = 15, db: Session = Depends(get_db)):
    rows = (
        db.query(Concept.id, Concept.label, Concept.category, func.count(ArticleConceptMapping.id).label("n"))
        .join(ArticleConceptMapping, Concept.id == ArticleConceptMapping.concept_id)
        .group_by(Concept.id)
        .order_by(func.count(ArticleConceptMapping.id).desc())
        .limit(limit)
        .all()
    )
    return {
        "data": [{"concept_id": cid, "label": lbl, "category": cat, "article_count": n}
                 for cid, lbl, cat, n in rows]
    }


@router.get("/top-journals")
def top_journals(limit: int = 10, db: Session = Depends(get_db)):
    rows = (
        db.query(Article.journal, func.count(Article.pmid).label("n"))
        .filter(Article.journal != "")
        .group_by(Article.journal)
        .order_by(func.count(Article.pmid).desc())
        .limit(limit)
        .all()
    )
    return {"data": [{"journal": j, "count": n} for j, n in rows]}


@router.get("/concepts-by-category")
def concepts_by_category(db: Session = Depends(get_db)):
    rows = (
        db.query(Concept.category, func.count(Concept.id))
        .group_by(Concept.category)
        .all()
    )
    return {"data": [{"category": cat, "count": cnt} for cat, cnt in rows]}


@router.get("/top-authors")
def top_authors(limit: int = 10, db: Session = Depends(get_db)):
    rows = (
        db.query(Author.id, Author.name, func.count(ArticleAuthor.article_pmid).label("n"))
        .join(ArticleAuthor, Author.id == ArticleAuthor.author_id)
        .group_by(Author.id)
        .order_by(func.count(ArticleAuthor.article_pmid).desc())
        .limit(limit)
        .all()
    )
    return {"data": [{"author_id": aid, "name": name, "article_count": n} for aid, name, n in rows]}


@router.get("/ingestion-jobs")
def ingestion_jobs(limit: int = 20, db: Session = Depends(get_db)):
    jobs = db.query(IngestionJob).order_by(IngestionJob.started_at.desc()).limit(limit).all()
    return {"jobs": [j.to_dict() for j in jobs]}
