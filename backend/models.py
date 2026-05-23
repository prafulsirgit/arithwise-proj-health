"""
SQLAlchemy ORM models for the Oncology Knowledge Repository.
"""
from __future__ import annotations
import json
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Text, DateTime, Boolean,
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from backend.database import Base


# ────────────────────────────────────────────────────────────────────────────
# Helper – JSON-serialisable list stored as TEXT
# ────────────────────────────────────────────────────────────────────────────
class _ListColumn(Text):
    """Thin wrapper: store Python list as JSON string in SQLite TEXT column."""


def list_to_json(value: list | None) -> str:
    return json.dumps(value or [])


def json_to_list(value: str | None) -> list:
    if not value:
        return []
    try:
        return json.loads(value)
    except Exception:
        return []


# ────────────────────────────────────────────────────────────────────────────
# Articles
# ────────────────────────────────────────────────────────────────────────────
class Article(Base):
    __tablename__ = "articles"

    pmid = Column(String(20), primary_key=True)
    title = Column(Text, nullable=False, default="")
    abstract = Column(Text, default="")
    doi = Column(String(200), nullable=True, index=True)
    journal = Column(String(500), default="")
    pub_date = Column(String(20), default="")   # stored as YYYY-MM-DD or YYYY
    pub_year = Column(Integer, nullable=True, index=True)
    pub_type = Column(String(100), default="")
    # stored as JSON arrays
    keywords_json = Column(Text, default="[]")
    mesh_terms_json = Column(Text, default="[]")
    full_text_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    article_authors = relationship("ArticleAuthor", back_populates="article", cascade="all, delete-orphan")
    concept_mappings = relationship("ArticleConceptMapping", back_populates="article", cascade="all, delete-orphan")

    @property
    def keywords(self) -> list[str]:
        return json_to_list(self.keywords_json)

    @keywords.setter
    def keywords(self, value: list[str]):
        self.keywords_json = list_to_json(value)

    @property
    def mesh_terms(self) -> list[str]:
        return json_to_list(self.mesh_terms_json)

    @mesh_terms.setter
    def mesh_terms(self, value: list[str]):
        self.mesh_terms_json = list_to_json(value)

    def to_dict(self):
        return {
            "pmid": self.pmid,
            "title": self.title,
            "abstract": self.abstract,
            "doi": self.doi,
            "journal": self.journal,
            "pub_date": self.pub_date,
            "pub_year": self.pub_year,
            "pub_type": self.pub_type,
            "keywords": self.keywords,
            "mesh_terms": self.mesh_terms,
            "full_text_url": self.full_text_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ────────────────────────────────────────────────────────────────────────────
# Authors
# ────────────────────────────────────────────────────────────────────────────
class Author(Base):
    __tablename__ = "authors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(300), nullable=False, index=True)
    affiliation = Column(Text, default="")
    orcid = Column(String(50), nullable=True)

    article_authors = relationship("ArticleAuthor", back_populates="author")

    __table_args__ = (
        UniqueConstraint("name", "affiliation", name="uq_author_name_affil"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "affiliation": self.affiliation,
            "orcid": self.orcid,
        }


class ArticleAuthor(Base):
    __tablename__ = "article_authors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_pmid = Column(String(20), ForeignKey("articles.pmid", ondelete="CASCADE"), nullable=False)
    author_id = Column(Integer, ForeignKey("authors.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, default=0)   # author order in the paper

    article = relationship("Article", back_populates="article_authors")
    author = relationship("Author", back_populates="article_authors")

    __table_args__ = (
        UniqueConstraint("article_pmid", "author_id", name="uq_article_author"),
    )


# ────────────────────────────────────────────────────────────────────────────
# Ontologies
# ────────────────────────────────────────────────────────────────────────────
class Ontology(Base):
    __tablename__ = "ontologies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    acronym = Column(String(50), nullable=False, unique=True, index=True)
    name = Column(String(500), default="")
    description = Column(Text, default="")
    version = Column(String(50), default="")
    portal_url = Column(String(500), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    concepts = relationship("Concept", back_populates="ontology", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "acronym": self.acronym,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "portal_url": self.portal_url,
        }


# ────────────────────────────────────────────────────────────────────────────
# Concepts
# ────────────────────────────────────────────────────────────────────────────
class Concept(Base):
    __tablename__ = "concepts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ontology_id = Column(Integer, ForeignKey("ontologies.id", ondelete="CASCADE"), nullable=False)
    concept_uri = Column(String(1000), nullable=False, index=True)
    label = Column(String(500), nullable=False, index=True)
    synonyms_json = Column(Text, default="[]")
    definition = Column(Text, default="")
    category = Column(String(100), default="general")   # disease | drug | biomarker | gene | general
    is_root = Column(Boolean, default=False)
    depth = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    ontology = relationship("Ontology", back_populates="concepts")
    article_mappings = relationship("ArticleConceptMapping", back_populates="concept", cascade="all, delete-orphan")
    parent_edges = relationship("ConceptHierarchy", foreign_keys="ConceptHierarchy.child_concept_id",
                                back_populates="child_concept", cascade="all, delete-orphan")
    child_edges = relationship("ConceptHierarchy", foreign_keys="ConceptHierarchy.parent_concept_id",
                               back_populates="parent_concept", cascade="all, delete-orphan")
    disease = relationship("DiseaseEntity", back_populates="concept", uselist=False, cascade="all, delete-orphan")
    drug = relationship("DrugEntity", back_populates="concept", uselist=False, cascade="all, delete-orphan")
    biomarker = relationship("BiomarkerEntity", back_populates="concept", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("ontology_id", "concept_uri", name="uq_concept_uri"),
        Index("ix_concept_label_lower", "label"),
    )

    @property
    def synonyms(self) -> list[str]:
        return json_to_list(self.synonyms_json)

    @synonyms.setter
    def synonyms(self, value: list[str]):
        self.synonyms_json = list_to_json(value)

    def to_dict(self, include_ontology=True):
        d = {
            "id": self.id,
            "concept_uri": self.concept_uri,
            "label": self.label,
            "synonyms": self.synonyms,
            "definition": self.definition,
            "category": self.category,
            "is_root": self.is_root,
            "depth": self.depth,
        }
        if include_ontology and self.ontology:
            d["ontology"] = {"id": self.ontology.id, "acronym": self.ontology.acronym, "name": self.ontology.name}
        return d


# ────────────────────────────────────────────────────────────────────────────
# Concept Hierarchy
# ────────────────────────────────────────────────────────────────────────────
class ConceptHierarchy(Base):
    __tablename__ = "concept_hierarchy"

    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_concept_id = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    child_concept_id = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)

    parent_concept = relationship("Concept", foreign_keys=[parent_concept_id], back_populates="child_edges")
    child_concept = relationship("Concept", foreign_keys=[child_concept_id], back_populates="parent_edges")

    __table_args__ = (
        UniqueConstraint("parent_concept_id", "child_concept_id", name="uq_hierarchy"),
    )


# ────────────────────────────────────────────────────────────────────────────
# Article ↔ Concept Mappings
# ────────────────────────────────────────────────────────────────────────────
class ArticleConceptMapping(Base):
    __tablename__ = "article_concept_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_pmid = Column(String(20), ForeignKey("articles.pmid", ondelete="CASCADE"), nullable=False)
    concept_id = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    match_type = Column(String(50), default="annotator")   # annotator | mesh | keyword
    match_score = Column(Float, default=1.0)
    matched_text = Column(String(500), default="")
    matched_via = Column(String(50), default="abstract")   # title | abstract | mesh | keyword
    created_at = Column(DateTime, default=datetime.utcnow)

    article = relationship("Article", back_populates="concept_mappings")
    concept = relationship("Concept", back_populates="article_mappings")

    __table_args__ = (
        UniqueConstraint("article_pmid", "concept_id", "match_type", name="uq_mapping"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "article_pmid": self.article_pmid,
            "concept_id": self.concept_id,
            "match_type": self.match_type,
            "match_score": self.match_score,
            "matched_text": self.matched_text,
            "matched_via": self.matched_via,
        }


# ────────────────────────────────────────────────────────────────────────────
# Disease, Drug, Biomarker entity sub-tables
# ────────────────────────────────────────────────────────────────────────────
class DiseaseEntity(Base):
    __tablename__ = "diseases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    concept_id = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), unique=True, nullable=False)
    cancer_type = Column(String(200), default="")
    icd_code = Column(String(20), nullable=True)
    stage_info = Column(String(200), default="")

    concept = relationship("Concept", back_populates="disease")


class DrugEntity(Base):
    __tablename__ = "drugs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    concept_id = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), unique=True, nullable=False)
    drug_class = Column(String(200), default="")
    mechanism = Column(Text, default="")
    approval_status = Column(String(100), default="")

    concept = relationship("Concept", back_populates="drug")


class BiomarkerEntity(Base):
    __tablename__ = "biomarkers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    concept_id = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), unique=True, nullable=False)
    gene_symbol = Column(String(50), default="")
    biomarker_type = Column(String(100), default="")   # mutation | expression | protein | snp
    associated_cancer = Column(String(200), default="")

    concept = relationship("Concept", back_populates="biomarker")


# ────────────────────────────────────────────────────────────────────────────
# Ingestion Job Log
# ────────────────────────────────────────────────────────────────────────────
class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_type = Column(String(50), nullable=False)   # pubmed | bioportal | mapping | embeddings
    status = Column(String(20), default="pending")  # pending | running | completed | failed
    query = Column(Text, default="")
    records_processed = Column(Integer, default=0)
    records_new = Column(Integer, default=0)
    records_skipped = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "job_type": self.job_type,
            "status": self.status,
            "query": self.query,
            "records_processed": self.records_processed,
            "records_new": self.records_new,
            "records_skipped": self.records_skipped,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# ────────────────────────────────────────────────────────────────────────────
# Semantic Embeddings (SQLite-compatible: stored as JSON TEXT)
# ────────────────────────────────────────────────────────────────────────────
class ArticleEmbedding(Base):
    """Stores the sentence-transformer embedding for an article (384-dim)."""
    __tablename__ = "article_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_pmid = Column(String(20), ForeignKey("articles.pmid", ondelete="CASCADE"),
                          nullable=False, unique=True, index=True)
    embedding_json = Column(Text, nullable=False)          # JSON-serialised list[float]
    model_name = Column(String(100), default="all-MiniLM-L6-v2")
    created_at = Column(DateTime, default=datetime.utcnow)

    article = relationship("Article", backref="embedding")

    @property
    def embedding(self) -> list[float]:
        try:
            return json.loads(self.embedding_json)
        except Exception:
            return []

    @embedding.setter
    def embedding(self, value: list[float]):
        self.embedding_json = json.dumps(value)


# ────────────────────────────────────────────────────────────────────────────
# AI-generated publication summaries (Groq cache)
# ────────────────────────────────────────────────────────────────────────────
class AIPublicationSummary(Base):
    """Caches Groq-generated summaries so we don't re-query the LLM on every page load."""
    __tablename__ = "ai_publication_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_pmid = Column(String(20), ForeignKey("articles.pmid", ondelete="CASCADE"),
                          nullable=False, unique=True, index=True)
    summary_text = Column(Text, nullable=False)
    model_used = Column(String(100), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    article = relationship("Article", backref="ai_summary")

    def to_dict(self):
        return {
            "article_pmid": self.article_pmid,
            "summary_text": self.summary_text,
            "model_used": self.model_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
