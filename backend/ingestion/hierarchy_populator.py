"""
Hierarchy Populator: fetches concept parent-child relationships from BioPortal
and stores them in the local database.
"""
from __future__ import annotations
import logging
import urllib.parse
import time
import requests
from sqlalchemy.orm import Session
from backend.database import SessionLocal
from backend.models import Concept, Ontology, ConceptHierarchy, ArticleConceptMapping
from backend.config import get_bioportal_headers, BIOPORTAL_BASE_URL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger("hierarchy_populator")

def run_hierarchy_population():
    db = SessionLocal()
    try:
        # Find concepts with active article mappings
        mapped_concept_ids = [
            r[0] for r in db.query(ArticleConceptMapping.concept_id).distinct().all()
        ]
        
        # Query all concepts
        all_concepts = db.query(Concept, Ontology).join(Ontology, Concept.ontology_id == Ontology.id).all()
        uri_to_id = {c.concept_uri: c.id for c, _ in all_concepts}
        
        # Target concepts: either mapped concepts or concepts containing "breast"
        target_concepts = []
        for c, o in all_concepts:
            is_target = (
                c.id in mapped_concept_ids or
                "breast" in c.label.lower() or
                "colorectal" in c.label.lower() or
                "leukemia" in c.label.lower()
            )
            if is_target:
                target_concepts.append((c, o))
                
        logger.info(f"Targeting {len(target_concepts)} core oncology concepts for hierarchy ingestion.")
        
        headers = get_bioportal_headers()
        added = 0
        checked = 0
        
        for concept, ontology in target_concepts:
            checked += 1
            if checked % 10 == 0:
                logger.info(f"Checked {checked}/{len(target_concepts)} concepts, added {added} hierarchy edges.")
                db.commit()
                
            # Fetch parents
            encoded_uri = urllib.parse.quote(concept.concept_uri, safe="")
            url = f"{BIOPORTAL_BASE_URL}/ontologies/{ontology.acronym}/classes/{encoded_uri}/parents"
            
            try:
                time.sleep(0.2)  # BioPortal friendly delay
                resp = requests.get(url, headers=headers, timeout=12)
                if resp.status_code == 200:
                    data = resp.json()
                    collection = data if isinstance(data, list) else data.get("collection", [])
                    for parent_item in collection:
                        parent_uri = parent_item.get("@id") or parent_item.get("id")
                        if parent_uri and parent_uri in uri_to_id:
                            parent_id = uri_to_id[parent_uri]
                            
                            # Check for duplicate
                            exists = (
                                db.query(ConceptHierarchy)
                                .filter_by(parent_concept_id=parent_id, child_concept_id=concept.id)
                                .first()
                            )
                            if not exists:
                                edge = ConceptHierarchy(
                                    parent_concept_id=parent_id,
                                    child_concept_id=concept.id
                                )
                                db.add(edge)
                                added += 1
                elif resp.status_code == 429:
                    logger.warning("BioPortal Rate limited. Waiting 5s...")
                    time.sleep(5)
            except Exception as e:
                logger.debug(f"Error fetching parents for {concept.label}: {e}")
                
        db.commit()
        logger.info(f"Hierarchy population complete. Added {added} hierarchical links.")
    finally:
        db.close()

if __name__ == "__main__":
    run_hierarchy_population()
