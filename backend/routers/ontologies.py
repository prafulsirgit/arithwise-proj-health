"""Ontologies router – browse concepts and hierarchies."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.database import get_db
from backend.models import Ontology, Concept, ConceptHierarchy, ArticleConceptMapping, Article

router = APIRouter(prefix="/api/ontologies", tags=["ontologies"])


@router.get("")
def list_ontologies(db: Session = Depends(get_db)):
    ontologies = db.query(Ontology).order_by(Ontology.acronym).all()
    result = []
    for ont in ontologies:
        d = ont.to_dict()
        d["concept_count"] = db.query(Concept).filter_by(ontology_id=ont.id).count()
        result.append(d)
    return {"ontologies": result, "total": len(result)}


@router.get("/concepts")
def search_concepts(
    q: str | None = Query(None, description="Label / synonym search"),
    ontology: str | None = Query(None, description="Ontology acronym filter"),
    category: str | None = Query(None, description="disease|drug|biomarker|gene|general"),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(Concept)

    if ontology:
        ont_obj = db.query(Ontology).filter_by(acronym=ontology.upper()).first()
        if not ont_obj:
            return {"total": 0, "results": []}
        query = query.filter(Concept.ontology_id == ont_obj.id)

    if category:
        query = query.filter(Concept.category == category.lower())

    if q:
        search = f"%{q}%"
        query = query.filter(
            or_(
                Concept.label.ilike(search),
                Concept.synonyms_json.ilike(search),
                Concept.definition.ilike(search),
            )
        )

    total = query.count()
    concepts = query.order_by(Concept.label).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "results": [c.to_dict() for c in concepts],
    }


@router.get("/concepts/{concept_id}")
def get_concept(concept_id: int, db: Session = Depends(get_db)):
    concept = db.get(Concept, concept_id)
    if not concept:
        raise HTTPException(status_code=404, detail="Concept not found")

    data = concept.to_dict()

    # Parents
    parent_ids = [e.parent_concept_id for e in concept.parent_edges]
    parents = db.query(Concept).filter(Concept.id.in_(parent_ids)).all() if parent_ids else []
    data["parents"] = [{"id": p.id, "label": p.label, "category": p.category} for p in parents]

    # Children
    child_ids = [e.child_concept_id for e in concept.child_edges]
    children = db.query(Concept).filter(Concept.id.in_(child_ids)).all() if child_ids else []
    data["children"] = [{"id": c.id, "label": c.label, "category": c.category} for c in children]

    # Article count
    data["article_count"] = (
        db.query(ArticleConceptMapping)
        .filter_by(concept_id=concept_id)
        .count()
    )

    # BioPortal URL
    data["bioportal_url"] = concept.concept_uri

    return data


@router.get("/concepts/{concept_id}/articles")
def get_concept_articles(
    concept_id: int,
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    concept = db.get(Concept, concept_id)
    if not concept:
        raise HTTPException(status_code=404, detail="Concept not found")

    total = db.query(ArticleConceptMapping).filter_by(concept_id=concept_id).count()
    rows = (
        db.query(ArticleConceptMapping, Article)
        .join(Article, ArticleConceptMapping.article_pmid == Article.pmid)
        .filter(ArticleConceptMapping.concept_id == concept_id)
        .offset(offset)
        .limit(limit)
        .all()
    )

    results = []
    for mapping, article in rows:
        d = {
            "pmid": article.pmid,
            "title": article.title,
            "journal": article.journal,
            "pub_year": article.pub_year,
            "doi": article.doi,
            "match_type": mapping.match_type,
            "match_score": mapping.match_score,
        }
        results.append(d)

    return {
        "concept": {"id": concept.id, "label": concept.label, "category": concept.category},
        "total": total,
        "offset": offset,
        "limit": limit,
        "articles": results,
    }


@router.get("/concepts/{concept_id}/graph")
def get_concept_graph(concept_id: int, db: Session = Depends(get_db)):
    """Return D3-ready knowledge graph centered on a concept."""
    from sqlalchemy import func
    from backend.models import Author, ArticleAuthor
    concept = db.get(Concept, concept_id)
    if not concept:
        raise HTTPException(status_code=404, detail="Concept not found")

    nodes = [{"id": f"concept_{concept_id}", "label": concept.label, "type": concept.category, "concept_id": concept_id}]
    edges = []

    # Parent/child hierarchy edges
    for edge in concept.parent_edges:
        parent = db.get(Concept, edge.parent_concept_id)
        if parent:
            nid = f"concept_{parent.id}"
            if not any(n["id"] == nid for n in nodes):
                nodes.append({"id": nid, "label": parent.label, "type": parent.category, "concept_id": parent.id})
            edges.append({"source": nid, "target": f"concept_{concept_id}", "type": "parent_of"})

    for edge in concept.child_edges[:10]:   # limit to 10 children for graph clarity
        child = db.get(Concept, edge.child_concept_id)
        if child:
            nid = f"concept_{child.id}"
            if not any(n["id"] == nid for n in nodes):
                nodes.append({"id": nid, "label": child.label, "type": child.category, "concept_id": child.id})
            edges.append({"source": f"concept_{concept_id}", "target": nid, "type": "child_of"})

    # Linked articles (up to 10)
    mappings = (
        db.query(ArticleConceptMapping, Article)
        .join(Article, ArticleConceptMapping.article_pmid == Article.pmid)
        .filter(ArticleConceptMapping.concept_id == concept_id)
        .limit(10)
        .all()
    )
    article_pmids = []
    for m, a in mappings:
        nid = f"article_{a.pmid}"
        article_pmids.append(a.pmid)
        if not any(n["id"] == nid for n in nodes):
            nodes.append({"id": nid, "label": a.title[:60] + "...", "type": "article", "pmid": a.pmid})
        edges.append({
            "source": f"concept_{concept_id}",
            "target": nid,
            "type": "mapped_to",
            "label": m.match_type,
            "score": m.match_score
        })

        # Authors of those articles
        author_links = (
            db.query(ArticleAuthor, Author)
            .join(Author, ArticleAuthor.author_id == Author.id)
            .filter(ArticleAuthor.article_pmid == a.pmid)
            .limit(3)
            .all()
        )
        for _, auth in author_links:
            auth_nid = f"author_{auth.id}"
            if not any(n["id"] == auth_nid for n in nodes):
                nodes.append({
                    "id": auth_nid,
                    "label": auth.name,
                    "type": "author",
                    "author_id": auth.id
                })
            edges.append({
                "source": nid,
                "target": auth_nid,
                "type": "written_by"
            })

    # Co-occurring Concepts: Concepts that map to the same articles
    if article_pmids:
        co_occurring = (
            db.query(Concept, func.count(ArticleConceptMapping.id).label("co_count"))
            .join(ArticleConceptMapping, Concept.id == ArticleConceptMapping.concept_id)
            .filter(ArticleConceptMapping.article_pmid.in_(article_pmids))
            .filter(Concept.id != concept_id)
            .group_by(Concept.id)
            .order_by(func.count(ArticleConceptMapping.id).desc())
            .limit(8)
            .all()
        )
        for co_concept, count in co_occurring:
            nid = f"concept_{co_concept.id}"
            if not any(n["id"] == nid for n in nodes):
                nodes.append({
                    "id": nid,
                    "label": co_concept.label,
                    "type": co_concept.category,
                    "concept_id": co_concept.id
                })
            edges.append({
                "source": f"concept_{concept_id}",
                "target": nid,
                "type": "co_occurs_with",
                "weight": count,
                "label": f"co-occurs ({count} pub)"
            })

    # ── Semantic Text Similarity Fallback ──────────────────────────────────
    STOP_WORDS = {"of", "the", "and", "or", "in", "to", "a", "an", "for", "with", "by", "at", "on", "obsolete"}

    def get_clean_words(text: str) -> set[str]:
        words = []
        for word in text.lower().replace("-", " ").replace("/", " ").split():
            clean = "".join(char for char in word if char.isalnum())
            if clean and clean not in STOP_WORDS:
                words.append(clean)
        return set(words)

    target_words = get_clean_words(concept.label)
    if target_words:
        all_other_concepts = db.query(Concept).filter(Concept.id != concept_id).all()
        scored_concepts = []
        for oc in all_other_concepts:
            oc_words = get_clean_words(oc.label)
            intersection = target_words & oc_words
            if intersection:
                score = len(intersection) / len(target_words | oc_words)
                boost_terms = {"breast", "colorectal", "melanoma", "lung", "prostate", "leukemia", "lymphoma", "cancer", "carcinoma", "neoplasm", "tumor"}
                if intersection & boost_terms:
                    score += 0.35
                scored_concepts.append((oc, score))

        scored_concepts.sort(key=lambda x: x[1], reverse=True)
        sem_related = [oc for oc, score in scored_concepts if score >= 0.35][:6]
        
        for sem_concept in sem_related:
            nid = f"concept_{sem_concept.id}"
            if not any(n["id"] == nid for n in nodes):
                nodes.append({
                    "id": nid,
                    "label": sem_concept.label,
                    "type": sem_concept.category,
                    "concept_id": sem_concept.id
                })
            edge_exists = any(
                (e["source"] == f"concept_{concept_id}" and e["target"] == nid) or
                (e["source"] == nid and e["target"] == f"concept_{concept_id}")
                for e in edges
            )
            if not edge_exists:
                edges.append({
                    "source": f"concept_{concept_id}",
                    "target": nid,
                    "type": "co_occurs_with",
                    "label": "semantically related"
                })

    return {"nodes": nodes, "edges": edges}
