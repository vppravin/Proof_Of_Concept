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
    """Normalize text for comparison — lowercase, strip business suffixes, remove special chars."""
    if not text:
        return ""
    s = text.lower().strip()
    for suffix in ['llc', 'inc', 'inc.', 'ltd', 'ltd.', 'l.l.c.', 'corporation', 'corp',
                    'corp.', 'company', 'co.', 'group', 'holdings']:
        s = re.sub(rf'\s+{re.escape(suffix)}\s*$', '', s)
    s = re.sub(r'[^a-z0-9\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _filename_to_name(filename: str) -> str:
    """Convert filename like 'greenfield-manufacturing.json' to 'greenfield manufacturing'."""
    return filename.replace('.json', '').replace('-', ' ')


def _name_to_slug(name: str) -> str:
    """Convert a client name to a filename slug."""
    return _normalize(name).replace(' ', '-')


def _fuzzy_match(input_name: str, filename: str) -> bool:
    """Check if input client name fuzzy-matches a filename."""
    norm_input = _normalize(input_name)
    norm_file = _filename_to_name(filename)
    if not norm_input or not norm_file:
        return False
    if norm_input == norm_file:
        return True
    if norm_input in norm_file or norm_file in norm_input:
        return True
    input_words = set(norm_input.split())
    file_words = set(norm_file.split())
    if input_words.issubset(file_words) or file_words.issubset(input_words):
        return True
    overlap = input_words & file_words
    if len(overlap) >= max(1, min(len(input_words), len(file_words)) - 1):
        return True
    return False


def _confirm_with_identifiers(file_data: dict, identifiers: dict) -> dict:
    """Confirm a candidate matches using unique identifiers from extracted data."""
    matches = {}
    checks = 0

    for key in ['fein', 'mailing_address', 'sic_code', 'broker', 'contact_person']:
        id_val = identifiers.get(key)
        file_val = file_data.get(key)
        if id_val and file_val:
            checks += 1
            matches[key] = _normalize(str(id_val)) == _normalize(str(file_val))

    matched_count = sum(1 for v in matches.values() if v)
    if matched_count >= 2:
        confidence = "high"
    elif matched_count == 1:
        confidence = "medium"
    elif checks > 0:
        confidence = "low"
    else:
        confidence = "name_only"

    return {"matched_fields": matches, "matched_count": matched_count, "total_checks": checks, "confidence": confidence}


# ── Tool functions ─────────────────────────────────────────────────────────

def get_client_history(client_name: str, identifiers: str = "{}") -> dict:
    """Fetches client history using a two-step lookup.

    Step 1: Lists all files in Client_history/, fuzzy-matches filenames against client_name.
    Step 2: Opens only the candidate files, checks identifiers (FEIN, address, SIC, broker,
            contact) to confirm the match. Returns the best confirmed match.

    Args:
        client_name: The insured company name e.g. "Greenfield Manufacturing LLC"
        identifiers: Optional JSON string with extracted identifiers for confirmation.
                     Supported keys: fein, mailing_address, sic_code, broker, contact_person

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

        # Step 1: List files and fuzzy match filenames
        blobs = list(bucket.list_blobs(prefix=CLIENT_DATA_PREFIX))
        candidates = []
        for blob in blobs:
            filename = blob.name.split("/")[-1]
            if not filename.endswith(".json") or not filename:
                continue
            if _fuzzy_match(client_name, filename):
                candidates.append(blob)
                logger.info(f"Step 1 — filename match: '{filename}'")

        if not candidates:
            logger.info(f"No filename matches for '{client_name}'")
            return {
                "client_name": client_name,
                "status": "not_found",
                "message": f"No client history found for '{client_name}'. This is a new client.",
            }

        # Step 2: Open candidates, confirm with identifiers
        best_match = None
        best_confirmation = None

        for blob in candidates:
            data = json.loads(blob.download_as_text())
            confirmation = _confirm_with_identifiers(data, id_data)
            logger.info(f"Step 2 — '{blob.name}': confidence={confirmation['confidence']}, matches={confirmation['matched_fields']}")

            if best_match is None or confirmation["matched_count"] > best_confirmation["matched_count"]:
                best_match = data
                best_confirmation = confirmation

        # If identifiers were provided but none confirmed, flag as uncertain
        if best_confirmation["confidence"] == "low":
            logger.info(f"Identifiers provided but did not confirm — returning uncertain")
            return {
                "client_name": client_name,
                "status": "uncertain",
                "match_confidence": "low",
                "matched_fields": best_confirmation["matched_fields"],
                "message": f"Found a name match but identifiers did not confirm. Possible match: '{best_match.get('client_name')}'. Needs human verification.",
                "history": best_match,
            }

        return {
            "client_name": client_name,
            "status": "found",
            "match_confidence": best_confirmation["confidence"],
            "matched_fields": best_confirmation["matched_fields"],
            "history": best_match,
        }

    except Exception as e:
        logger.error(f"Error fetching client history: {e}")
        return {"error": str(e)}


def create_client_history(client_data_json: str) -> dict:
    """Creates a new client history record in GCS.

    Filename is derived from the client name (lowercase, hyphenated slug).

    Args:
        client_data_json: JSON string with the new client data. Must include 'client_name'.

    Returns:
        Dict with status and the GCS path of the created file.
    """
    logger.info("Tool: create_client_history")
    try:
        data = json.loads(client_data_json) if isinstance(client_data_json, str) else client_data_json
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}

    client_name = data.get("client_name")
    if not client_name:
        return {"error": "client_name is required"}

    filename = f"{_name_to_slug(client_name)}.json"
    blob_path = f"{CLIENT_DATA_PREFIX}{filename}"

    try:
        bucket = gcs_client.bucket(BUCKET_NAME)
        blob = bucket.blob(blob_path)

        if blob.exists():
            return {"error": f"Client history already exists at {blob_path}. Use update_client_history instead."}

        if "status" not in data:
            data["status"] = "Active"

        blob.upload_from_string(json.dumps(data, indent=2), content_type="application/json")
        logger.info(f"Created client history: {blob_path}")
        return {"status": "created", "filename": filename, "gcs_path": f"gs://{BUCKET_NAME}/{blob_path}"}

    except Exception as e:
        logger.error(f"Error creating client history: {e}")
        return {"error": str(e)}


def update_client_history(client_name: str, updates_json: str) -> dict:
    """Updates an existing client history record in GCS.

    Finds the client file by fuzzy filename match, merges updates, writes back.

    Args:
        client_name: The insured company name.
        updates_json: JSON string with fields to update/merge into the existing record.

    Returns:
        Dict with status and the updated fields.
    """
    logger.info(f"Tool: update_client_history for '{client_name}'")
    try:
        updates = json.loads(updates_json) if isinstance(updates_json, str) else updates_json
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}

    try:
        bucket = gcs_client.bucket(BUCKET_NAME)
        blobs = list(bucket.list_blobs(prefix=CLIENT_DATA_PREFIX))

        for blob in blobs:
            filename = blob.name.split("/")[-1]
            if not filename.endswith(".json"):
                continue
            if _fuzzy_match(client_name, filename):
                existing = json.loads(blob.download_as_text())
                existing.update(updates)
                blob.upload_from_string(json.dumps(existing, indent=2), content_type="application/json")
                logger.info(f"Updated: {blob.name}")
                return {"status": "updated", "filename": filename, "updated_fields": list(updates.keys())}

        return {"error": f"No existing history for '{client_name}'. Use create_client_history first."}

    except Exception as e:
        logger.error(f"Error updating client history: {e}")
        return {"error": str(e)}
