"""
NCBO BioPortal ingestor.

Fetches ontology metadata and concept hierarchies for the configured ontologies
and stores them in the local database.
"""
from __future__ import annotations
import logging
import time
from datetime import datetime
from typing import Any

import requests
from sqlalchemy.orm import Session

from backend.config import (
    BIOPORTAL_BASE_URL, DEFAULT_ONTOLOGIES, get_bioportal_headers, is_bioportal_configured
)
from backend.models import Ontology, Concept, ConceptHierarchy, DiseaseEntity, DrugEntity, BiomarkerEntity, IngestionJob

logger = logging.getLogger(__name__)

_RATE_LIMIT_DELAY = 0.2   # 200ms between requests to be polite

# ── Keyword sets for category classification ───────────────────────────────
_DISEASE_KEYWORDS = {
    "cancer", "carcinoma", "sarcoma", "lymphoma", "leukemia", "melanoma",
    "tumor", "tumour", "neoplasm", "neoplasms", "malignancy", "malignant",
    "adenocarcinoma", "glioma", "myeloma", "mesothelioma", "hepatocellular",
}
_DRUG_KEYWORDS = {
    "drug", "therapy", "inhibitor", "antibody", "chemotherapy", "agent",
    "treatment", "vaccine", "immunotherapy", "kinase", "monoclonal",
    "pharmaceutical", "medicine", "medication", "therapeutic",
}
_BIOMARKER_KEYWORDS = {
    "gene", "mutation", "biomarker", "protein", "expression", "marker",
    "receptor", "antigen", "snp", "variant", "locus", "allele",
    "chromosome", "genomic", "mrna", "rna", "dna", "methylation",
}


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────

def run_bioportal_ingestion(
    db: Session,
    ontology_acronyms: list[str] | None = None,
    max_concepts_per_ontology: int = 500,
    job: IngestionJob | None = None,
) -> dict:
    """
    Main entry point for BioPortal ingestion.
    Fetches ontology metadata, then root classes and their children up to a depth limit.
    """
    if not is_bioportal_configured():
        raise ValueError(
            "BioPortal API key not configured. "
            "Set BIOPORTAL_API_KEY in your .env file."
        )

    acronyms = ontology_acronyms or DEFAULT_ONTOLOGIES
    logger.info(f"BioPortal ingestion started | ontologies={acronyms}")

    if job:
        job.status = "running"
        job.query = ",".join(acronyms)
        db.commit()

    stats = {"processed": 0, "new": 0, "skipped": 0, "errors": 0}

    try:
        for acronym in acronyms:
            try:
                _ingest_ontology(db, acronym, max_concepts_per_ontology, stats)
            except Exception as exc:
                logger.error(f"Error ingesting ontology {acronym}: {exc}", exc_info=True)
                stats["errors"] += 1
            if job:
                job.records_processed = stats["processed"]
                job.records_new = stats["new"]
                db.commit()

        if job:
            job.status = "completed"
            job.records_processed = stats["processed"]
            job.records_new = stats["new"]
            job.records_skipped = stats["skipped"]
            job.completed_at = datetime.utcnow()
            db.commit()

        logger.info(f"BioPortal ingestion complete: {stats}")
        return stats

    except Exception as exc:
        logger.error(f"BioPortal ingestion failed: {exc}", exc_info=True)
        if job:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.utcnow()
            db.commit()
        raise


# ────────────────────────────────────────────────────────────────────────────
# Per-ontology ingestion
# ────────────────────────────────────────────────────────────────────────────

def _ingest_ontology(db: Session, acronym: str, max_concepts: int, stats: dict):
    headers = get_bioportal_headers()

    # ── 1. Fetch / update ontology metadata ──────────────────────────────
    ont_data = _get_ontology_metadata(acronym, headers)
    ontology = _upsert_ontology(db, acronym, ont_data)
    logger.info(f"Ontology [{acronym}] id={ontology.id}")

    # ── 2. Fetch concepts via search API (cancer-relevant terms) ─────────
    # We use the BioPortal search endpoint filtering by ontology for oncology terms
    concepts_fetched = 0
    oncology_queries = [
        "cancer", "tumor", "neoplasm", "carcinoma", "lymphoma",
        "leukemia", "melanoma", "drug", "biomarker", "gene", "mutation"
    ]

    for query_term in oncology_queries:
        if concepts_fetched >= max_concepts:
            break
        page = 1
        while concepts_fetched < max_concepts:
            data = _search_concepts(query_term, acronym, page, headers)
            if not data:
                break
            collection = data.get("collection", [])
            if not collection:
                break

            for item in collection:
                if concepts_fetched >= max_concepts:
                    break
                try:
                    concept = _upsert_concept(db, ontology.id, item)
                    if concept:
                        concepts_fetched += 1
                        stats["new"] += 1
                    else:
                        stats["skipped"] += 1
                    stats["processed"] += 1
                except Exception as exc:
                    logger.debug(f"Concept upsert error: {exc}")
                    stats["errors"] += 1

            next_page = data.get("nextPage")
            if not next_page or page >= 5:   # limit to 5 pages per term
                break
            page += 1
            time.sleep(_RATE_LIMIT_DELAY)

        time.sleep(_RATE_LIMIT_DELAY)

    db.commit()
    logger.info(f"[{acronym}] ingested {concepts_fetched} concepts")


# ────────────────────────────────────────────────────────────────────────────
# BioPortal REST calls
# ────────────────────────────────────────────────────────────────────────────

def _get_ontology_metadata(acronym: str, headers: dict) -> dict:
    url = f"{BIOPORTAL_BASE_URL}/ontologies/{acronym}"
    resp = _get(url, headers, params={"display_links": "false", "display_context": "false"})
    return resp or {}


def _search_concepts(query: str, ontology: str, page: int, headers: dict) -> dict | None:
    url = f"{BIOPORTAL_BASE_URL}/search"
    params = {
        "q": query,
        "ontologies": ontology,
        "page": page,
        "pagesize": 50,
        "display_links": "false",
        "display_context": "false",
        "include": "prefLabel,synonym,definition",
    }
    return _get(url, headers, params=params)


def _get_class_children(ontology: str, class_id: str, headers: dict, page: int = 1) -> dict | None:
    """Fetch paginated children of a class."""
    import urllib.parse
    encoded = urllib.parse.quote(class_id, safe="")
    url = f"{BIOPORTAL_BASE_URL}/ontologies/{ontology}/classes/{encoded}/children"
    params = {"page": page, "pagesize": 50, "display_links": "false", "display_context": "false"}
    return _get(url, headers, params=params)


def _get(url: str, headers: dict, params: dict | None = None, retries: int = 2) -> dict | None:
    for attempt in range(retries + 1):
        try:
            time.sleep(_RATE_LIMIT_DELAY)
            resp = requests.get(url, headers=headers, params=params, timeout=20)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                logger.warning(f"Rate limited by BioPortal. Waiting 5s...")
                time.sleep(5)
            elif resp.status_code == 404:
                logger.debug(f"404 for {url}")
                return None
            else:
                logger.warning(f"BioPortal {resp.status_code} for {url}: {resp.text[:200]}")
                return None
        except requests.RequestException as exc:
            if attempt == retries:
                logger.error(f"Request failed for {url}: {exc}")
                return None
            time.sleep(1)
    return None


# ────────────────────────────────────────────────────────────────────────────
# Database helpers
# ────────────────────────────────────────────────────────────────────────────

def _upsert_ontology(db: Session, acronym: str, data: dict) -> Ontology:
    ontology = db.query(Ontology).filter_by(acronym=acronym).first()
    if not ontology:
        ontology = Ontology(acronym=acronym)
        db.add(ontology)

    ontology.name = _safe(data.get("name", acronym))
    summary = data.get("summaryOnly", {})
    ontology.description = _safe(data.get("description") or "")
    if isinstance(data.get("version"), str):
        ontology.version = data["version"]
    ontology.portal_url = f"https://bioportal.bioontology.org/ontologies/{acronym}"
    db.flush()
    return ontology


def _upsert_concept(db: Session, ontology_id: int, item: dict) -> Concept | None:
    """Upsert a concept from BioPortal search result item."""
    uri = item.get("@id", "") or item.get("id", "")
    if not uri:
        return None

    label = _safe(item.get("prefLabel", "")) or _safe(item.get("label", ""))
    if not label:
        return None

    existing = db.query(Concept).filter_by(ontology_id=ontology_id, concept_uri=uri).first()
    if existing:
        return None  # already stored, count as skip

    # Synonyms
    raw_syns = item.get("synonym", []) or []
    synonyms = [_safe(s) for s in raw_syns if _safe(s)][:10]

    # Definition
    defs = item.get("definition", []) or []
    definition = _safe(defs[0]) if defs else ""

    # Category
    category = _classify_concept(label, synonyms, definition)

    concept = Concept(
        ontology_id=ontology_id,
        concept_uri=uri[:900],
        label=label[:400],
        definition=definition[:2000],
        category=category,
    )
    concept.synonyms = synonyms
    db.add(concept)
    db.flush()

    # Create domain-specific entity record
    _create_entity_record(db, concept)

    return concept


def _classify_concept(label: str, synonyms: list[str], definition: str) -> str:
    """Classify concept into disease | drug | biomarker | gene | general."""
    text = (label + " " + " ".join(synonyms) + " " + definition).lower()
    words = set(text.split())

    if words & _DISEASE_KEYWORDS:
        return "disease"
    if words & _DRUG_KEYWORDS:
        return "drug"
    if words & _BIOMARKER_KEYWORDS:
        return "biomarker"
    return "general"


def _create_entity_record(db: Session, concept: Concept):
    """Create disease/drug/biomarker sub-record if applicable."""
    if concept.category == "disease":
        entity = DiseaseEntity(concept_id=concept.id, cancer_type=concept.label)
        db.add(entity)
    elif concept.category == "drug":
        entity = DrugEntity(concept_id=concept.id, drug_class="oncology")
        db.add(entity)
    elif concept.category == "biomarker":
        entity = BiomarkerEntity(concept_id=concept.id, biomarker_type="general")
        db.add(entity)


def _safe(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value).strip()
