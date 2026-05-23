"""
Configuration module - loads settings from .env file.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=False)

# Also try .env.example as fallback for demo mode
if not env_path.exists():
    example_path = Path(__file__).parent.parent / ".env.example"
    load_dotenv(dotenv_path=example_path, override=False)

# ── NCBI / PubMed ──────────────────────────────────────────
NCBI_EMAIL: str = os.getenv("NCBI_EMAIL", "demo@oncology-platform.local")
NCBI_API_KEY: str | None = os.getenv("NCBI_API_KEY") or None

# ── BioPortal ──────────────────────────────────────────────
BIOPORTAL_API_KEY: str | None = os.getenv("BIOPORTAL_API_KEY") or None
BIOPORTAL_BASE_URL: str = "https://data.bioontology.org"

# ── Database ───────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./oncology.db")

# ── Server ─────────────────────────────────────────────────
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))
DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

# ── Ingestion defaults ─────────────────────────────────────
DEFAULT_MAX_ARTICLES: int = int(os.getenv("DEFAULT_MAX_ARTICLES", "200"))
DEFAULT_ONTOLOGIES: list[str] = [
    o.strip()
    for o in os.getenv("DEFAULT_ONTOLOGIES", "NCIT,DOID,CHEBI,GO").split(",")
    if o.strip()
]
DEFAULT_PUBMED_QUERY: str = os.getenv(
    "DEFAULT_PUBMED_QUERY",
    "cancer[Title/Abstract] OR oncology[Title/Abstract] OR neoplasm[MeSH Terms]",
)

# ── Groq AI ─────────────────────────────────────────────────
GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY") or None
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

# ── Embeddings ───────────────────────────────────────────────
EMBEDDING_MODEL_NAME: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_DIM: int = 384


def get_bioportal_headers() -> dict:
    if not BIOPORTAL_API_KEY or BIOPORTAL_API_KEY == "your_bioportal_api_key_here":
        raise ValueError(
            "BioPortal API key not configured. "
            "Please set BIOPORTAL_API_KEY in your .env file. "
            "Get a free key at https://bioportal.bioontology.org/account"
        )
    return {"Authorization": f"apikey token={BIOPORTAL_API_KEY}"}


def is_bioportal_configured() -> bool:
    return bool(BIOPORTAL_API_KEY) and BIOPORTAL_API_KEY != "your_bioportal_api_key_here"


def is_ncbi_configured() -> bool:
    return bool(NCBI_API_KEY) and NCBI_API_KEY != "your_ncbi_api_key_here"


def is_groq_configured() -> bool:
    return bool(GROQ_API_KEY) and GROQ_API_KEY not in ("your_groq_api_key_here", "")
