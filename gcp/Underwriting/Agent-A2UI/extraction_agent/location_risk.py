"""Location risk enrichment — lookup EQ/flood zone from mock data in GCS by zip code."""

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

# Cache the data after first load
_risk_data_cache = None


def _load_risk_data() -> dict:
    """Load location risk data from GCS (cached after first call)."""
    global _risk_data_cache
    if _risk_data_cache is not None:
        return _risk_data_cache
    try:
        bucket = gcs_client.bucket(BUCKET_NAME)
        blob = bucket.blob(LOCATION_RISK_PATH)
        _risk_data_cache = json.loads(blob.download_as_text())
        logger.info(f"Loaded {len(_risk_data_cache)} location risk entries from GCS")
        return _risk_data_cache
    except Exception as e:
        logger.error(f"Failed to load location risk data: {e}")
        return {}


def _extract_zip(address: str) -> str:
    """Extract zip code (5-digit) from an address string."""
    if not address:
        return None
    match = re.search(r'\b(\d{5})(?:-\d{4})?\b', address)
    return match.group(1) if match else None


def enrich_location_risk(address: str) -> dict:
    """Lookup EQ zone and flood zone from GCS mock data using zip code.

    Args:
        address: US street address containing a zip code.

    Returns:
        Dict with eq_zone, flood_zone, and lookup metadata.
    """
    logger.info(f"Looking up location risk for: {address}")

    zip_code = _extract_zip(address)
    if not zip_code:
        return {
            "address": address,
            "found": False,
            "eq_zone": "No",
            "flood_zone": "No",
            "note": "Could not extract zip code from address"
        }

    data = _load_risk_data()
    entry = data.get(zip_code)

    if not entry:
        return {
            "address": address,
            "zip_code": zip_code,
            "found": False,
            "eq_zone": "No",
            "flood_zone": "No",
            "note": f"Zip code {zip_code} not found in location risk database"
        }

    return {
        "address": address,
        "zip_code": zip_code,
        "found": True,
        "city": entry.get("city"),
        "state": entry.get("state"),
        "eq_zone": entry.get("eq_zone", "No"),
        "flood_zone": entry.get("flood_zone", "No"),
        "source": "GCS location risk database"
    }
