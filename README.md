# Integrated Oncology Knowledge Repository

A full-stack platform combining **PubMed** publications and **NCBO BioPortal** ontologies into a unified searchable knowledge base.

## Quick Start

### 1. Prerequisites
- Python 3.11+
- API keys (see below)

### 2. Set Up API Keys

```bash
copy .env.example .env
```

Edit `.env` and fill in:
```
NCBI_EMAIL=your.email@example.com
NCBI_API_KEY=your_ncbi_key          # optional but recommended
BIOPORTAL_API_KEY=your_bioportal_key   # REQUIRED
```

- **BioPortal key**: https://bioportal.bioontology.org/account → API Key tab
- **NCBI key**: https://www.ncbi.nlm.nih.gov/account/ → API Keys

### 3. Install & Run

```bash
cd proj-ariths
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r backend/requirements.txt
python -m backend.main
```

Open **http://localhost:8000**

### 4. First Data Ingestion

From the **Data Management** tab in the dashboard:
1. Click **▶ Start PubMed Ingestion** — fetches oncology articles
2. Click **▶ Start BioPortal Ingestion** — fetches ontology concepts
3. Click **▶ Start Mapping** — links articles to concepts

## Architecture

- **Backend**: FastAPI + SQLAlchemy + SQLite
- **PubMed**: Biopython Entrez API
- **BioPortal**: REST API (search + annotator)
- **Frontend**: Vanilla JS + D3.js + Chart.js

## API Docs

Interactive docs at: http://localhost:8000/api/docs
