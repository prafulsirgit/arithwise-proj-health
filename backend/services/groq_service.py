"""
Groq AI Service — generates structured oncology publication summaries.

Uses Groq's fast-inference API with llama-3.1-8b-instant.
Degrades gracefully when GROQ_API_KEY is not configured.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def is_available() -> bool:
    from backend.config import is_groq_configured
    return is_groq_configured()


def summarize_publication(
    title: str,
    abstract: str,
    mesh_terms: list[str] | None = None,
    concept_labels: list[str] | None = None,
    pmid: str = "",
) -> dict:
    """
    Generate a structured AI summary for an oncology publication.
    Returns a dict with keys: success, summary, model, error.
    """
    from backend.config import GROQ_API_KEY, GROQ_MODEL, is_groq_configured

    if not is_groq_configured():
        return {
            "success": False,
            "summary": None,
            "model": None,
            "error": "Groq API key not configured. Add GROQ_API_KEY to your .env file.",
        }

    mesh_str = ", ".join((mesh_terms or [])[:10]) or "N/A"
    concepts_str = ", ".join((concept_labels or [])[:10]) or "N/A"
    abstract_trimmed = (abstract or "")[:3000]

    prompt = f"""You are an expert oncology research analyst. Analyze this oncology publication and provide a concise, structured summary for researchers.

Title: {title}
Abstract: {abstract_trimmed}
MeSH Terms: {mesh_str}
Key Concepts: {concepts_str}

Provide a structured summary with exactly these sections (use the exact headers):

**Background & Objective**
[1-2 sentences on study context and goal]

**Key Findings**
[2-3 bullet points of the most important results]

**Clinical Significance**
[1-2 sentences on why this matters for oncology practice or research]

**Related Concepts**
[List 3-5 key biomedical entities (diseases, genes, drugs, biomarkers) central to this paper]

Keep the entire summary under 250 words. Be precise and clinically relevant."""

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert oncology research analyst who creates concise, accurate summaries of medical publications."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=600,
        )
        summary_text = response.choices[0].message.content.strip()
        return {
            "success": True,
            "summary": summary_text,
            "model": response.model,
            "error": None,
        }
    except Exception as exc:
        logger.error(f"Groq summarize failed for PMID {pmid}: {exc}")
        return {
            "success": False,
            "summary": None,
            "model": None,
            "error": str(exc),
        }
