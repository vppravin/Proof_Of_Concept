"""Location risk enrichment — lookup EQ/flood zone from GCS by zip code."""

import os
import re
import json
import logging

from google.cloud import storage

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
BUCKET_NAME = os.getenv("BUCKET_NAME", "underwriting-workbench")
LOCATION_RISK_PATH = os.getenv("LOCATION_RISK_PATH", "location_risk/location_risk_data.json")

gcs_client = storage.Client(project=PROJECT_ID)
_risk_data_cache = None


def _load_risk_data() -> dict:
    global _risk_data_cache
    if _risk_data_cache is not None:
        return _risk_data_cache
    try:
        blob = gcs_client.bucket(BUCKET_NAME).blob(LOCATION_RISK_PATH)
        _risk_data_cache = json.loads(blob.download_as_text())
        return _risk_data_cache
    except Exception as e:
        logger.error(f"Failed to load location risk data: {e}")
        return {}


def enrich_location_risk(address: str) -> dict:
    """Looks up EQ zone and flood zone for a US address using zip code.

    Args:
        address: US street address containing a zip code.

    Returns:
        Dict with eq_zone, flood_zone, and whether a match was found.
    """
    logger.info(f"Tool: enrich_location_risk for {address}")
    zip_match = re.search(r'\b(\d{5})(?:-\d{4})?\b', address or "")
    if not zip_match:
        return {"address": address, "found": False, "eq_zone": "No", "flood_zone": "No", "note": "No zip code found"}

    zip_code = zip_match.group(1)
    data = _load_risk_data()
    entry = data.get(zip_code)

    if not entry:
        return {"address": address, "zip_code": zip_code, "found": False, "eq_zone": "No", "flood_zone": "No"}

    return {
        "address": address, "zip_code": zip_code, "found": True,
        "city": entry.get("city"), "state": entry.get("state"),
        "eq_zone": entry.get("eq_zone", "No"), "flood_zone": entry.get("flood_zone", "No"),
    }
