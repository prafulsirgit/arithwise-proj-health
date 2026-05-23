"""
PubMed data ingestor using NCBI E-utilities REST API directly (no Biopython).
Uses requests + xml.etree.ElementTree to fetch and parse oncology articles.
"""
from __future__ import annotations
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Generator

import requests
from sqlalchemy.orm import Session

from backend.config import NCBI_EMAIL, NCBI_API_KEY, DEFAULT_PUBMED_QUERY, DEFAULT_MAX_ARTICLES
from backend.models import Article, Author, ArticleAuthor, IngestionJob

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_RATE_DELAY = 0.11 if (NCBI_API_KEY and NCBI_API_KEY != "your_ncbi_api_key_here") else 0.4


def _base_params() -> dict:
    p = {"email": NCBI_EMAIL, "tool": "oncology-repo"}
    if NCBI_API_KEY and NCBI_API_KEY != "your_ncbi_api_key_here":
        p["api_key"] = NCBI_API_KEY
    return p


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────

def run_pubmed_ingestion(
    db: Session,
    query: str = DEFAULT_PUBMED_QUERY,
    max_results: int = DEFAULT_MAX_ARTICLES,
    job: IngestionJob | None = None,
) -> dict:
    logger.info(f"PubMed ingestion | query='{query}' max={max_results}")
    if job:
        job.status = "running"; job.query = query; db.commit()

    try:
        pmids = _esearch(query, max_results)
        logger.info(f"Found {len(pmids)} PMIDs")

        existing = {r[0] for r in db.query(Article.pmid).filter(Article.pmid.in_(pmids)).all()}
        new_pmids = [p for p in pmids if p not in existing]
        stats = {"processed": 0, "new": 0, "skipped": len(existing), "errors": 0}
        logger.info(f"Already stored: {len(existing)} | New: {len(new_pmids)}")

        for batch in _chunked(new_pmids, 100):
            articles = _efetch_parse(batch)
            for art in articles:
                try:
                    _upsert_article(db, art)
                    stats["new"] += 1
                except Exception as exc:
                    logger.debug(f"Upsert error {art.get('pmid')}: {exc}")
                    stats["errors"] += 1
                stats["processed"] += 1
            if job:
                job.records_processed = stats["processed"]
                job.records_new = stats["new"]
                job.records_skipped = stats["skipped"]
                db.commit()

        if job:
            job.status = "completed"; job.completed_at = datetime.utcnow()
            job.records_processed = stats["processed"]
            job.records_new = stats["new"]; job.records_skipped = stats["skipped"]
            db.commit()

        logger.info(f"Done: {stats}")
        return stats

    except Exception as exc:
        logger.error(f"PubMed ingestion failed: {exc}", exc_info=True)
        if job:
            job.status = "failed"; job.error_message = str(exc)
            job.completed_at = datetime.utcnow(); db.commit()
        raise


# ────────────────────────────────────────────────────────────────────────────
# NCBI E-utilities
# ────────────────────────────────────────────────────────────────────────────

def _esearch(query: str, max_results: int) -> list[str]:
    time.sleep(_RATE_DELAY)
    params = {**_base_params(), "db": "pubmed", "term": query,
              "retmax": max_results, "retmode": "xml", "usehistory": "n"}
    r = requests.get(f"{EUTILS_BASE}/esearch.fcgi", params=params, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    return [e.text.strip() for e in root.findall(".//Id") if e.text]


def _efetch_parse(pmids: list[str]) -> list[dict]:
    time.sleep(_RATE_DELAY)
    params = {**_base_params(), "db": "pubmed", "id": ",".join(pmids),
              "rettype": "xml", "retmode": "xml"}
    r = requests.get(f"{EUTILS_BASE}/efetch.fcgi", params=params, timeout=60)
    r.raise_for_status()
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        logger.error(f"XML parse error: {e}")
        return []

    results = []
    for elem in root.findall(".//PubmedArticle"):
        try:
            d = _parse_article(elem)
            if d:
                results.append(d)
        except Exception as exc:
            logger.debug(f"Parse error: {exc}")
    return results


def _parse_article(elem: ET.Element) -> dict | None:
    medline = elem.find(".//MedlineCitation")
    if medline is None:
        return None
    pmid_elem = medline.find("PMID")
    if pmid_elem is None:
        return None
    pmid = pmid_elem.text.strip()

    art = medline.find("Article")
    if art is None:
        return None

    title = _txt(art.find(".//ArticleTitle"))
    abstract = " ".join(_txt(p) for p in art.findall(".//AbstractText") if _txt(p))
    journal = _txt(art.find(".//Journal/Title"))
    pub_date_str, pub_year = _pub_date(art)

    doi = None
    for id_e in elem.findall(".//ArticleId"):
        if id_e.get("IdType") == "doi":
            doi = id_e.text.strip() if id_e.text else None; break

    full_text_url = None
    for id_e in elem.findall(".//ArticleId"):
        if id_e.get("IdType") == "pmc":
            pmc = id_e.text.strip() if id_e.text else None
            if pmc:
                full_text_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc}/"; break

    pub_type = "; ".join(_txt(pt) for pt in art.findall(".//PublicationType") if _txt(pt))
    authors = _authors(art)
    keywords = [_txt(k) for k in medline.findall(".//KeywordList/Keyword") if _txt(k)]
    mesh = [_txt(m.find("DescriptorName")) for m in medline.findall(".//MeshHeading")
            if m.find("DescriptorName") is not None and _txt(m.find("DescriptorName"))]

    return {"pmid": pmid, "title": title, "abstract": abstract, "doi": doi,
            "journal": journal, "pub_date": pub_date_str, "pub_year": pub_year,
            "pub_type": pub_type, "keywords": keywords, "mesh_terms": mesh,
            "full_text_url": full_text_url, "authors": authors}


def _authors(art: ET.Element) -> list[dict]:
    result = []
    for i, a in enumerate(art.findall(".//AuthorList/Author")):
        last = _txt(a.find("LastName")); fore = _txt(a.find("ForeName"))
        if not last and not fore:
            name = _txt(a.find("CollectiveName")) or "Unknown"
        else:
            name = f"{last}, {fore}".strip(", ")
        affil = _txt(a.find(".//AffiliationInfo/Affiliation"))
        result.append({"name": name, "affiliation": affil, "position": i})
    return result


def _pub_date(art: ET.Element) -> tuple[str, int | None]:
    pd = art.find(".//Journal/JournalIssue/PubDate")
    if pd is not None:
        yr = _txt(pd.find("Year")); mo = _txt(pd.find("Month")) or "01"; dy = _txt(pd.find("Day")) or "01"
        if yr:
            try:
                return f"{yr}-{_mon(mo):02d}-{dy.zfill(2)}", int(yr)
            except ValueError:
                pass
    ad = art.find(".//ArticleDate")
    if ad is not None:
        yr = _txt(ad.find("Year")); mo = _txt(ad.find("Month")) or "01"; dy = _txt(ad.find("Day")) or "01"
        if yr:
            try:
                return f"{yr}-{mo.zfill(2)}-{dy.zfill(2)}", int(yr)
            except ValueError:
                pass
    return "", None


def _mon(m: str) -> int:
    table = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,"Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
    try: return int(m)
    except ValueError: return table.get(m, 1)


def _txt(e: ET.Element | None) -> str:
    if e is None: return ""
    parts = [e.text or ""]
    for c in e:
        parts.append(c.text or "")
        parts.append(c.tail or "")
    return " ".join(parts).strip()


def _chunked(lst: list, n: int) -> Generator:
    for i in range(0, len(lst), n):
        yield lst[i:i+n]


# ────────────────────────────────────────────────────────────────────────────
# DB helpers
# ────────────────────────────────────────────────────────────────────────────

def _upsert_article(db: Session, data: dict) -> Article:
    art = db.get(Article, data["pmid"])
    if art is None:
        art = Article(pmid=data["pmid"]); db.add(art)
    art.title = data.get("title",""); art.abstract = data.get("abstract","")
    art.doi = data.get("doi"); art.journal = data.get("journal","")
    art.pub_date = data.get("pub_date",""); art.pub_year = data.get("pub_year")
    art.pub_type = data.get("pub_type","")
    art.keywords = data.get("keywords", []); art.mesh_terms = data.get("mesh_terms", [])
    art.full_text_url = data.get("full_text_url")
    db.flush()
    for ad in data.get("authors", []):
        author = db.query(Author).filter_by(name=ad["name"], affiliation=ad["affiliation"]).first()
        if not author:
            author = Author(name=ad["name"], affiliation=ad["affiliation"]); db.add(author); db.flush()
        if not db.query(ArticleAuthor).filter_by(article_pmid=art.pmid, author_id=author.id).first():
            db.add(ArticleAuthor(article_pmid=art.pmid, author_id=author.id, position=ad["position"]))
    db.commit()
    return art
