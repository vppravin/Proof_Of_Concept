"""Client history tools — GCS-based fuzzy matching."""

import os
import re
import json
import logging

from google.cloud import storage

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
BUCKET_NAME = os.getenv("BUCKET_NAME", "underwriting-workbench")
CLIENT_DATA_PREFIX = os.getenv("CLIENT_DATA_PREFIX", "Client_history/")

gcs_client = storage.Client(project=PROJECT_ID)


def _normalize(text: str) -> str:
    if not text:
        return ""
    s = text.lower().strip()
    for suffix in ['llc', 'inc', 'inc.', 'ltd', 'ltd.', 'l.l.c.', 'corporation', 'corp', 'corp.', 'company', 'co.', 'group', 'holdings']:
        s = re.sub(rf'\s+{re.escape(suffix)}\s*$', '', s)
    s = re.sub(r'[^a-z0-9\s]', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def _fuzzy_match(input_name: str, filename: str) -> bool:
    norm_input = _normalize(input_name)
    norm_file = filename.replace('.json', '').replace('-', ' ')
    if not norm_input or not norm_file:
        return False
    if norm_input == norm_file or norm_input in norm_file or norm_file in norm_input:
        return True
    input_words = set(norm_input.split())
    file_words = set(norm_file.split())
    if input_words.issubset(file_words) or file_words.issubset(input_words):
        return True
    overlap = input_words & file_words
    return len(overlap) >= max(1, min(len(input_words), len(file_words)) - 1)


def _confirm_with_identifiers(file_data: dict, identifiers: dict) -> dict:
    matches = {}
    checks = 0
    for key in ['fein', 'mailing_address', 'sic_code', 'broker', 'contact_person']:
        id_val = identifiers.get(key)
        file_val = file_data.get(key)
        if id_val and file_val:
            checks += 1
            matches[key] = _normalize(str(id_val)) == _normalize(str(file_val))

    matched_count = sum(1 for v in matches.values() if v)
    if matched_count >= 2: confidence = "high"
    elif matched_count == 1: confidence = "medium"
    elif checks > 0: confidence = "low"
    else: confidence = "name_only"

    return {"matched_fields": matches, "matched_count": matched_count, "total_checks": checks, "confidence": confidence}


def get_client_history(client_name: str, identifiers: str = "{}") -> dict:
    """Looks up client history by fuzzy-matching the client name against stored records.

    Uses a two-step process: (1) fuzzy match filenames, (2) confirm with identifiers.

    Args:
        client_name: The insured company name e.g. "Greenfield Manufacturing LLC"
        identifiers: Optional JSON string with keys: fein, mailing_address, sic_code, broker, contact_person

    Returns:
        Dict with client history and match confidence, or not_found for new clients.
    """
    logger.info(f"Tool: get_client_history for '{client_name}'")

    try:
        id_data = json.loads(identifiers) if isinstance(identifiers, str) else identifiers
    except json.JSONDecodeError:
        id_data = {}

    try:
        bucket = gcs_client.bucket(BUCKET_NAME)
        blobs = list(bucket.list_blobs(prefix=CLIENT_DATA_PREFIX))
        candidates = []
        for blob in blobs:
            filename = blob.name.split("/")[-1]
            if not filename.endswith(".json"):
                continue
            if _fuzzy_match(client_name, filename):
                candidates.append(blob)

        if not candidates:
            return {"client_name": client_name, "status": "not_found", "message": f"No client history found for '{client_name}'. New client."}

        best_match = None
        best_confirmation = None
        for blob in candidates:
            data = json.loads(blob.download_as_text())
            confirmation = _confirm_with_identifiers(data, id_data)
            if best_match is None or confirmation["matched_count"] > best_confirmation["matched_count"]:
                best_match = data
                best_confirmation = confirmation

        if best_confirmation["confidence"] == "low":
            return {
                "client_name": client_name, "status": "uncertain", "match_confidence": "low",
                "matched_fields": best_confirmation["matched_fields"],
                "message": f"Found name match but identifiers didn't confirm. Possible: '{best_match.get('client_name')}'. Needs human verification.",
                "history": best_match,
            }

        return {
            "client_name": client_name, "status": "found",
            "match_confidence": best_confirmation["confidence"],
            "matched_fields": best_confirmation["matched_fields"],
            "history": best_match,
        }
    except Exception as e:
        return {"error": str(e)}
