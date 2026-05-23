"""
Concept Mapper: links PubMed articles to BioPortal ontology concepts.

Strategy (applied in order):
1. MeSH term direct label match against stored concepts
2. Keyword direct match
3. BioPortal Annotator API (sends abstract text, returns concept annotations)
"""
from __future__ import annotations
import json
import logging
import time
from datetime import datetime
from typing import Any

import requests
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.config import BIOPORTAL_BASE_URL, get_bioportal_headers, is_bioportal_configured
from backend.models import Article, Concept, ArticleConceptMapping, IngestionJob

logger = logging.getLogger(__name__)

_RATE_LIMIT_DELAY = 0.3


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────

def run_mapping(
    db: Session,
    limit_unmapped: int = 100,
    job: IngestionJob | None = None,
) -> dict:
    """
    Map articles that have no concept mappings yet.
    Applies both local label matching and BioPortal Annotator.
    """
    if job:
        job.status = "running"
        db.commit()

    stats = {"processed": 0, "new_mappings": 0, "errors": 0}

    try:
        # Find articles with zero mappings
        mapped_pmids = db.query(ArticleConceptMapping.article_pmid).distinct().subquery()
        unmapped = (
            db.query(Article)
            .filter(~Article.pmid.in_(mapped_pmids))
            .limit(limit_unmapped)
            .all()
        )

        logger.info(f"Mapping {len(unmapped)} unmapped articles")

        # Pre-load concept label → id mapping for fast local matching
        label_index = _build_label_index(db)

        for article in unmapped:
            try:
                n = _map_article(db, article, label_index)
                stats["new_mappings"] += n
            except Exception as exc:
                logger.warning(f"Mapping error for {article.pmid}: {exc}")
                stats["errors"] += 1
            stats["processed"] += 1

            if job and stats["processed"] % 10 == 0:
                job.records_processed = stats["processed"]
                job.records_new = stats["new_mappings"]
                db.commit()

        if job:
            job.status = "completed"
            job.records_processed = stats["processed"]
            job.records_new = stats["new_mappings"]
            job.completed_at = datetime.utcnow()
            db.commit()

        logger.info(f"Mapping complete: {stats}")
        return stats

    except Exception as exc:
        logger.error(f"Mapping failed: {exc}", exc_info=True)
        if job:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.utcnow()
            db.commit()
        raise


# ────────────────────────────────────────────────────────────────────────────
# Per-article mapping
# ────────────────────────────────────────────────────────────────────────────

def _map_article(db: Session, article: Article, label_index: dict[str, list[int]]) -> int:
    """Map a single article. Returns number of new mappings created."""
    created = 0

    # ── 1. MeSH term matching ─────────────────────────────────────────────
    for mesh in article.mesh_terms:
        for concept_id in _lookup_label(mesh, label_index):
            if _create_mapping(db, article.pmid, concept_id, "mesh", 1.0, mesh, "mesh"):
                created += 1

    # ── 2. Keyword matching ───────────────────────────────────────────────
    for kw in article.keywords:
        for concept_id in _lookup_label(kw, label_index):
            if _create_mapping(db, article.pmid, concept_id, "keyword", 0.9, kw, "keyword"):
                created += 1

    # ── 3. BioPortal Annotator (abstract + title) ─────────────────────────
    if is_bioportal_configured():
        text = f"{article.title} {article.abstract}"[:3000]
        if text.strip():
            annotations = _call_annotator(text)
            for ann in annotations[:50]:   # cap at 50 per article
                concept_id = _find_concept_by_uri(db, ann.get("uri", ""))
                if concept_id:
                    matched_text = ann.get("text", "")[:400]
                    if _create_mapping(db, article.pmid, concept_id, "annotator", 0.95,
                                       matched_text, "abstract"):
                        created += 1

    return created


# ────────────────────────────────────────────────────────────────────────────
# BioPortal Annotator
# ────────────────────────────────────────────────────────────────────────────

def _call_annotator(text: str) -> list[dict]:
    """
    Call the BioPortal Annotator endpoint and return list of
    {uri, ontology, text} dicts.
    """
    try:
        headers = get_bioportal_headers()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        url = f"{BIOPORTAL_BASE_URL}/annotator"
        payload = {
            "text": text,
            "ontologies": "NCIT,DOID,CHEBI,GO,SNOMEDCT",
            "include": "prefLabel",
            "display_links": "false",
            "display_context": "false",
            "longest_only": "true",
            "whole_word_only": "true",
        }
        time.sleep(_RATE_LIMIT_DELAY)
        resp = requests.post(url, data=payload, headers=headers, timeout=30)
        if resp.status_code != 200:
            logger.debug(f"Annotator returned {resp.status_code}")
            return []

        results = resp.json()
        annotations = []
        for item in results:
            ann_class = item.get("annotatedClass", {})
            uri = ann_class.get("@id", "")
            for text_ann in item.get("annotations", []):
                annotations.append({
                    "uri": uri,
                    "text": text_ann.get("text", ""),
                    "from": text_ann.get("from", 0),
                    "to": text_ann.get("to", 0),
                })
        return annotations
    except Exception as exc:
        logger.debug(f"Annotator error: {exc}")
        return []


# ────────────────────────────────────────────────────────────────────────────
# Local index helpers
# ────────────────────────────────────────────────────────────────────────────

def _build_label_index(db: Session) -> dict[str, list[int]]:
    """Build an in-memory dict: lower-case label → list of concept IDs."""
    index: dict[str, list[int]] = {}
    rows = db.query(Concept.id, Concept.label, Concept.synonyms_json).all()
    for concept_id, label, synonyms_json in rows:
        _add_to_index(index, label, concept_id)
        try:
            syns = json.loads(synonyms_json or "[]")
            for syn in syns:
                _add_to_index(index, syn, concept_id)
        except Exception:
            pass
    return index


def _add_to_index(index: dict, label: str, concept_id: int):
    if label:
        key = label.strip().lower()
        if key:
            index.setdefault(key, []).append(concept_id)


def _lookup_label(text: str, index: dict[str, list[int]]) -> list[int]:
    return index.get(text.strip().lower(), [])


def _find_concept_by_uri(db: Session, uri: str) -> int | None:
    if not uri:
        return None
    row = db.query(Concept.id).filter(Concept.concept_uri == uri[:900]).first()
    return row[0] if row else None


# ────────────────────────────────────────────────────────────────────────────
# Mapping creation
# ────────────────────────────────────────────────────────────────────────────

def _create_mapping(
    db: Session,
    pmid: str,
    concept_id: int,
    match_type: str,
    score: float,
    matched_text: str,
    matched_via: str,
) -> bool:
    """Create a mapping if it doesn't already exist. Returns True if created."""
    existing = (
        db.query(ArticleConceptMapping)
        .filter_by(article_pmid=pmid, concept_id=concept_id, match_type=match_type)
        .first()
    )
    if existing:
        return False

    mapping = ArticleConceptMapping(
        article_pmid=pmid,
        concept_id=concept_id,
        match_type=match_type,
        match_score=score,
        matched_text=matched_text[:400],
        matched_via=matched_via,
    )
    db.add(mapping)
    try:
        db.flush()
        return True
    except Exception:
        db.rollback()
        return False
