"""
Embedding Service — generates and stores sentence-transformer embeddings for articles.

Uses all-MiniLM-L6-v2 (384-dim). Falls back gracefully to TF-IDF cosine similarity
if sentence-transformers/numpy are not installed.
"""
from __future__ import annotations
import json
import logging
import math
from typing import Any

from sqlalchemy.orm import Session

from backend.models import Article, ArticleEmbedding

logger = logging.getLogger(__name__)

# ── Lazy singleton for the embedding model ────────────────────────────────
_model = None
_model_loaded = False
_USE_TFIDF_FALLBACK = False


def _get_model():
    global _model, _model_loaded, _USE_TFIDF_FALLBACK
    if _model_loaded:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
        from backend.config import EMBEDDING_MODEL_NAME
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL_NAME}")
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        logger.info("Embedding model loaded ✓")
    except Exception as exc:
        logger.warning(f"Could not load SentenceTransformer ({exc}). Using TF-IDF fallback.")
        _USE_TFIDF_FALLBACK = True
        _model = None
    _model_loaded = True
    return _model


def is_available() -> bool:
    """Return True if the embedding model (or fallback) is usable."""
    _get_model()
    return not _USE_TFIDF_FALLBACK or True   # TF-IDF fallback always available


# ── Cosine similarity (pure-Python, no numpy dependency at module level) ──
def _cosine_sim(a: list[float], b: list[float]) -> float:
    try:
        import numpy as np
        va = np.array(a, dtype="float32")
        vb = np.array(b, dtype="float32")
        denom = (np.linalg.norm(va) * np.linalg.norm(vb))
        if denom == 0:
            return 0.0
        return float(np.dot(va, vb) / denom)
    except ImportError:
        # Pure-Python fallback
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)


# ── TF-IDF based similarity fallback ─────────────────────────────────────
def _tfidf_vector(text: str, vocab: dict[str, int], idf: dict[str, float]) -> list[float]:
    """Simple TF-IDF vector for a document given vocab and IDF weights."""
    words = text.lower().split()
    tf: dict[str, float] = {}
    for w in words:
        tf[w] = tf.get(w, 0) + 1
    n = max(len(words), 1)
    vec = [0.0] * len(vocab)
    for w, freq in tf.items():
        if w in vocab:
            vec[vocab[w]] = (freq / n) * idf.get(w, 1.0)
    return vec


def _build_tfidf_index(texts: list[str]) -> tuple[dict[str, int], dict[str, float]]:
    import math as _math
    N = len(texts)
    df: dict[str, int] = {}
    all_words_sets = []
    for t in texts:
        ws = set(t.lower().split())
        all_words_sets.append(ws)
        for w in ws:
            df[w] = df.get(w, 0) + 1
    vocab = {w: i for i, w in enumerate(df)}
    idf = {w: _math.log((N + 1) / (cnt + 1)) + 1 for w, cnt in df.items()}
    return vocab, idf


# ── Public API ────────────────────────────────────────────────────────────

def encode_texts(texts: list[str]) -> list[list[float]]:
    """Encode a batch of texts into embedding vectors."""
    model = _get_model()
    if model is not None:
        try:
            embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
            return [e.tolist() for e in embeddings]
        except Exception as exc:
            logger.warning(f"encode_texts failed: {exc}")
    # TF-IDF fallback: build per-call vocabulary
    vocab, idf = _build_tfidf_index(texts)
    return [_tfidf_vector(t, vocab, idf) for t in texts]


def _article_text(article: Article) -> str:
    """Concatenate title + abstract for embedding."""
    return f"{article.title or ''} {article.abstract or ''}".strip()


def generate_article_embeddings(db: Session, batch_size: int = 50) -> dict:
    """Generate and store embeddings for articles that don't have one yet."""
    from backend.config import EMBEDDING_MODEL_NAME
    model = _get_model()
    model_name = EMBEDDING_MODEL_NAME if model else "tfidf-fallback"

    # Find articles missing embeddings
    existing_pmids = {row[0] for row in db.query(ArticleEmbedding.article_pmid).all()}
    articles = (
        db.query(Article)
        .filter(~Article.pmid.in_(existing_pmids))
        .all()
    )

    stats = {"total": len(articles), "processed": 0, "errors": 0}
    logger.info(f"Generating embeddings for {len(articles)} articles...")

    for i in range(0, len(articles), batch_size):
        batch = articles[i: i + batch_size]
        texts = [_article_text(a) for a in batch]
        try:
            vectors = encode_texts(texts)
            for article, vec in zip(batch, vectors):
                emb = ArticleEmbedding(
                    article_pmid=article.pmid,
                    embedding_json=json.dumps(vec),
                    model_name=model_name,
                )
                db.merge(emb)
            db.commit()
            stats["processed"] += len(batch)
        except Exception as exc:
            logger.error(f"Embedding batch {i} failed: {exc}")
            db.rollback()
            stats["errors"] += len(batch)

    return stats


def find_similar_articles(db: Session, pmid: str, limit: int = 6) -> list[dict]:
    """Return the most semantically similar articles to `pmid`."""
    target_emb_row = db.query(ArticleEmbedding).filter_by(article_pmid=pmid).first()

    if not target_emb_row:
        # Fall back to keyword-based similarity via shared concept mappings
        return _fallback_similar(db, pmid, limit)

    target_vec = target_emb_row.embedding
    if not target_vec:
        return _fallback_similar(db, pmid, limit)

    all_embs = (
        db.query(ArticleEmbedding, Article)
        .join(Article, ArticleEmbedding.article_pmid == Article.pmid)
        .filter(ArticleEmbedding.article_pmid != pmid)
        .all()
    )

    scored = []
    for emb_row, article in all_embs:
        vec = emb_row.embedding
        if vec:
            score = _cosine_sim(target_vec, vec)
            scored.append((score, article))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, art in scored[:limit]:
        results.append({
            "pmid": art.pmid,
            "title": art.title,
            "journal": art.journal,
            "pub_year": art.pub_year,
            "similarity_score": round(score, 4),
            "abstract_snippet": (art.abstract or "")[:200],
        })
    return results


def _fallback_similar(db: Session, pmid: str, limit: int) -> list[dict]:
    """Shared-concept-based similarity when no embeddings exist."""
    from backend.models import ArticleConceptMapping, Article
    from sqlalchemy import func

    concept_ids = [
        row[0] for row in
        db.query(ArticleConceptMapping.concept_id)
        .filter(ArticleConceptMapping.article_pmid == pmid)
        .all()
    ]
    if not concept_ids:
        return []

    rows = (
        db.query(
            ArticleConceptMapping.article_pmid,
            func.count(ArticleConceptMapping.concept_id).label("shared"),
        )
        .filter(
            ArticleConceptMapping.concept_id.in_(concept_ids),
            ArticleConceptMapping.article_pmid != pmid,
        )
        .group_by(ArticleConceptMapping.article_pmid)
        .order_by(func.count(ArticleConceptMapping.concept_id).desc())
        .limit(limit)
        .all()
    )

    results = []
    for other_pmid, shared_count in rows:
        art = db.get(Article, other_pmid)
        if art:
            results.append({
                "pmid": art.pmid,
                "title": art.title,
                "journal": art.journal,
                "pub_year": art.pub_year,
                "similarity_score": round(shared_count / max(len(concept_ids), 1), 4),
                "abstract_snippet": (art.abstract or "")[:200],
            })
    return results
