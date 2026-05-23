"""
Trending Topics Service — extracts frequently occurring oncology concepts
from recently ingested publications.

Uses pure SQL frequency analysis on MeSH terms and keywords — no ML required.
"""
from __future__ import annotations
import json
import logging
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.models import Article, Concept, ArticleConceptMapping

logger = logging.getLogger(__name__)

# Oncology-relevant stop terms to exclude from trending
_STOP_TERMS = {
    "cancer", "tumor", "tumour", "neoplasm", "neoplasms", "oncology",
    "patients", "patient", "clinical", "study", "studies", "analysis",
    "treatment", "therapy", "human", "humans", "male", "female", "adult",
    "aged", "middle aged", "animals", "mice", "cell", "cells",
    "in vitro", "in vivo", "results", "conclusion", "method", "methods",
    "background", "objective", "introduction", "associated", "related",
    "prognosis", "diagnosis", "survival", "risk", "effect",
}


def get_trending_topics(db: Session, days: int = 90, limit: int = 20) -> list[dict]:
    """
    Return trending oncology topics from articles ingested in the last `days` days.
    Uses both concept mappings and raw keyword/MeSH frequency.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    recent_articles = (
        db.query(Article)
        .filter(Article.created_at >= cutoff)
        .all()
    )

    if not recent_articles:
        # Fall back to ALL articles if nothing in window
        recent_articles = db.query(Article).order_by(Article.created_at.desc()).limit(500).all()

    recent_pmids = {a.pmid for a in recent_articles}

    # ── 1. Concept frequency from mappings ───────────────────────────────
    concept_rows = (
        db.query(
            Concept.id,
            Concept.label,
            Concept.category,
            func.count(ArticleConceptMapping.id).label("cnt"),
        )
        .join(ArticleConceptMapping, Concept.id == ArticleConceptMapping.concept_id)
        .filter(ArticleConceptMapping.article_pmid.in_(recent_pmids))
        .group_by(Concept.id)
        .order_by(func.count(ArticleConceptMapping.id).desc())
        .limit(50)
        .all()
    )

    # ── 2. MeSH term frequency (raw text) ────────────────────────────────
    mesh_counter: Counter = Counter()
    kw_counter: Counter = Counter()

    for art in recent_articles:
        for term in art.mesh_terms:
            t = term.strip().lower()
            if t and t not in _STOP_TERMS and len(t) > 3:
                mesh_counter[term.strip()] += 1
        for kw in art.keywords:
            t = kw.strip().lower()
            if t and t not in _STOP_TERMS and len(t) > 3:
                kw_counter[kw.strip()] += 1

    # ── Assemble results ──────────────────────────────────────────────────
    results = []

    # Concepts from ontology mappings
    seen_labels: set[str] = set()
    for cid, label, category, cnt in concept_rows[:limit]:
        label_lower = label.lower()
        if label_lower in _STOP_TERMS or len(label) < 3:
            continue
        seen_labels.add(label_lower)
        results.append({
            "term": label,
            "count": cnt,
            "category": category,
            "source": "concept",
            "concept_id": cid,
        })

    # Supplement with MeSH terms not already covered
    for term, cnt in mesh_counter.most_common(30):
        if term.lower() not in seen_labels and len(results) < limit + 10:
            seen_labels.add(term.lower())
            results.append({
                "term": term,
                "count": cnt,
                "category": "mesh",
                "source": "mesh",
                "concept_id": None,
            })

    # Sort by count, cap at limit
    results.sort(key=lambda x: x["count"], reverse=True)
    return results[:limit]


def get_publication_timeline(db: Session, days: int = 365) -> list[dict]:
    """Return article counts grouped by month for the last N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    articles = (
        db.query(Article.pub_year, func.count(Article.pmid))
        .filter(Article.pub_year.isnot(None))
        .filter(Article.created_at >= cutoff)
        .group_by(Article.pub_year)
        .order_by(Article.pub_year)
        .all()
    )
    return [{"year": yr, "count": cnt} for yr, cnt in articles]
