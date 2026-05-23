"""Publications router – search and retrieve PubMed articles."""
from __future__ import annotations
import json
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func

from backend.database import get_db
from backend.models import Article, Author, ArticleAuthor, Concept, ArticleConceptMapping

router = APIRouter(prefix="/api/publications", tags=["publications"])


@router.get("")
def search_publications(
    q: str | None = Query(None, description="Full-text keyword search"),
    author: str | None = Query(None),
    pmid: str | None = Query(None),
    doi: str | None = Query(None),
    year: int | None = Query(None),
    year_from: int | None = Query(None),
    year_to: int | None = Query(None),
    journal: str | None = Query(None),
    cancer_type: str | None = Query(None, description="Filter by cancer type concept"),
    mesh_term: str | None = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(Article)

    if pmid:
        query = query.filter(Article.pmid == pmid.strip())
    if doi:
        query = query.filter(Article.doi.ilike(f"%{doi.strip()}%"))
    if year:
        query = query.filter(Article.pub_year == year)
    if year_from:
        query = query.filter(Article.pub_year >= year_from)
    if year_to:
        query = query.filter(Article.pub_year <= year_to)
    if journal:
        query = query.filter(Article.journal.ilike(f"%{journal}%"))
    if mesh_term:
        query = query.filter(Article.mesh_terms_json.ilike(f"%{mesh_term}%"))

    if q:
        search = f"%{q}%"
        query = query.filter(
            or_(
                Article.title.ilike(search),
                Article.abstract.ilike(search),
                Article.keywords_json.ilike(search),
                Article.mesh_terms_json.ilike(search),
                Article.journal.ilike(search),
            )
        )

    if author:
        # Join through article_authors → authors
        query = (
            query.join(ArticleAuthor, Article.pmid == ArticleAuthor.article_pmid)
            .join(Author, ArticleAuthor.author_id == Author.id)
            .filter(Author.name.ilike(f"%{author}%"))
        )

    if cancer_type:
        # Filter by concept label
        query = (
            query.join(ArticleConceptMapping, Article.pmid == ArticleConceptMapping.article_pmid)
            .join(Concept, ArticleConceptMapping.concept_id == Concept.id)
            .filter(Concept.label.ilike(f"%{cancer_type}%"))
        )

    total = query.count()
    articles = query.order_by(Article.pub_year.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "results": [_article_summary(a) for a in articles],
    }


@router.get("/{pmid}")
def get_publication(pmid: str, db: Session = Depends(get_db)):
    article = db.get(Article, pmid)
    if not article:
        raise HTTPException(status_code=404, detail=f"Article {pmid} not found")

    # Authors
    author_links = (
        db.query(ArticleAuthor, Author)
        .join(Author, ArticleAuthor.author_id == Author.id)
        .filter(ArticleAuthor.article_pmid == pmid)
        .order_by(ArticleAuthor.position)
        .all()
    )
    authors = [a.to_dict() for _, a in author_links]

    # Concept mappings
    mappings = (
        db.query(ArticleConceptMapping, Concept)
        .join(Concept, ArticleConceptMapping.concept_id == Concept.id)
        .filter(ArticleConceptMapping.article_pmid == pmid)
        .all()
    )
    concept_details = []
    for m, c in mappings:
        d = c.to_dict()
        d["match_type"] = m.match_type
        d["match_score"] = m.match_score
        d["matched_text"] = m.matched_text
        d["matched_via"] = m.matched_via
        concept_details.append(d)

    data = article.to_dict()
    data["authors"] = authors
    data["concepts"] = concept_details
    data["pubmed_url"] = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    return data


@router.get("/{pmid}/graph")
def get_article_graph(pmid: str, db: Session = Depends(get_db)):
    """Return D3-ready graph data: nodes and edges for a specific article."""
    article = db.get(Article, pmid)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    nodes = [{"id": f"article_{pmid}", "label": article.title[:60] + "...", "type": "article", "pmid": pmid}]
    edges = []

    mappings = (
        db.query(ArticleConceptMapping, Concept)
        .join(Concept, ArticleConceptMapping.concept_id == Concept.id)
        .filter(ArticleConceptMapping.article_pmid == pmid)
        .all()
    )

    seen_concepts = set()
    concept_ids = []
    for m, c in mappings:
        node_id = f"concept_{c.id}"
        concept_ids.append(c.id)
        if node_id not in seen_concepts:
            nodes.append({
                "id": node_id,
                "label": c.label,
                "type": c.category,
                "concept_id": c.id,
            })
            seen_concepts.add(node_id)
        edges.append({
            "source": f"article_{pmid}",
            "target": node_id,
            "type": "mapped_to",
            "label": m.match_type,
            "score": m.match_score,
        })

    # 2. Author nodes for the article
    author_links = (
        db.query(ArticleAuthor, Author)
        .join(Author, ArticleAuthor.author_id == Author.id)
        .filter(ArticleAuthor.article_pmid == pmid)
        .all()
    )
    for _, auth in author_links:
        node_id = f"author_{auth.id}"
        if not any(n["id"] == node_id for n in nodes):
            nodes.append({
                "id": node_id,
                "label": auth.name,
                "type": "author",
                "author_id": auth.id
            })
        edges.append({
            "source": f"article_{pmid}",
            "target": node_id,
            "type": "written_by"
        })

        # 3. Fetch up to 2 other papers by the same author
        other_papers = (
            db.query(ArticleAuthor, Article)
            .join(Article, ArticleAuthor.article_pmid == Article.pmid)
            .filter(ArticleAuthor.author_id == auth.id, Article.pmid != pmid)
            .limit(2)
            .all()
        )
        for _, other_art in other_papers:
            art_node_id = f"article_{other_art.pmid}"
            if not any(n["id"] == art_node_id for n in nodes):
                nodes.append({
                    "id": art_node_id,
                    "label": other_art.title[:60] + "...",
                    "type": "article",
                    "pmid": other_art.pmid
                })
            edges.append({
                "source": art_node_id,
                "target": node_id,
                "type": "written_by"
            })

    # 4. Concept co-occurrences in other publications
    if len(concept_ids) > 1:
        co_mappings = (
            db.query(ArticleConceptMapping.article_pmid, ArticleConceptMapping.concept_id)
            .filter(ArticleConceptMapping.concept_id.in_(concept_ids))
            .filter(ArticleConceptMapping.article_pmid != pmid)
            .all()
        )
        art_concepts = {}
        for art_pmid, c_id in co_mappings:
            art_concepts.setdefault(art_pmid, []).append(c_id)

        co_counts = {}
        for c_list in art_concepts.values():
            if len(c_list) > 1:
                sorted_c = sorted(list(set(c_list)))
                for i in range(len(sorted_c)):
                    for j in range(i + 1, len(sorted_c)):
                        pair = (sorted_c[i], sorted_c[j])
                        co_counts[pair] = co_counts.get(pair, 0) + 1

        for (c1, c2), count in co_counts.items():
            if count >= 1:
                edges.append({
                    "source": f"concept_{c1}",
                    "target": f"concept_{c2}",
                    "type": "co_occurs_with",
                    "weight": count,
                    "label": f"co-occurs ({count} pub)"
                })

    return {"nodes": nodes, "edges": edges}


def _article_summary(article: Article) -> dict:
    return {
        "pmid": article.pmid,
        "title": article.title,
        "journal": article.journal,
        "pub_year": article.pub_year,
        "pub_date": article.pub_date,
        "doi": article.doi,
        "pub_type": article.pub_type,
        "abstract_snippet": (article.abstract or "")[:250],
    }
