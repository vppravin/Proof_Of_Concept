import logging
import json
import time
import os
import re
from datetime import datetime, timezone
from google.cloud import storage
from vertexai import agent_engines
from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
BUCKET_NAME = os.getenv("BUCKET_NAME", "underwriting-workbench")
gcs_client = storage.Client(project=PROJECT_ID)

# Deployed Agent Engine IDs
CLASSIFICATION_AGENT_ID = "projects/146646146609/locations/us-central1/reasoningEngines/2783005217145225216"
EXTRACTION_AGENT_ID = "projects/146646146609/locations/us-central1/reasoningEngines/8617150253566525440"
RULES_UPDATE_AGENT_ID = "projects/146646146609/locations/us-central1/reasoningEngines/855464576630652928"
CLIENT_HISTORY_AGENT_ID = "projects/146646146609/locations/us-central1/reasoningEngines/5943406255652470784"
UW_RULES_AGENT_ID = "projects/146646146609/locations/us-central1/reasoningEngines/4573186069024997376"
SUBMISSION_AGENT_ID = "projects/146646146609/locations/us-central1/reasoningEngines/5466728382592974848"


def _extract_file_from_context(tool_context) -> list:
    """Extract all uploaded file bytes from ADK tool context.

    Returns list of (file_bytes, file_name) tuples.
    """
    files = []

    def _from_parts(parts):
        if not parts:
            return
        for part in parts:
            # inline_data (ADK UI / small files)
            if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                if len(part.inline_data.data) > 100:
                    name = getattr(part.inline_data, "display_name", None) or "document.pdf"
                    files.append((part.inline_data.data, name))

            # file_data (Gemini Enterprise / large files)
            if hasattr(part, "file_data") and part.file_data and part.file_data.file_uri:
                uri = part.file_data.file_uri
                name = getattr(part.file_data, "display_name", None)
                if not name:
                    name = uri.split("/")[-1] if "/" in uri else "document.pdf"

                file_bytes = None
                if uri.startswith("gs://"):
                    uri_parts = uri.replace("gs://", "").split("/", 1)
                    blob = gcs_client.bucket(uri_parts[0]).blob(uri_parts[1])
                    file_bytes = blob.download_as_bytes()
                else:
                    import google.auth
                    import google.auth.transport.requests
                    import httpx
                    creds, _ = google.auth.default()
                    creds.refresh(google.auth.transport.requests.Request())
                    resp = httpx.get(uri, headers={"Authorization": f"Bearer {creds.token}"}, timeout=300)
                    resp.raise_for_status()
                    file_bytes = resp.content

                if file_bytes and len(file_bytes) > 100:
                    files.append((file_bytes, name))

    # Check current turn
    uc = tool_context.user_content
    if uc and uc.parts:
        _from_parts(uc.parts)

    # Search session history
    if not files:
        try:
            for event in reversed(tool_context.session.events):
                if event.author == "user" and event.content and event.content.parts:
                    _from_parts(event.content.parts)
                    if files:
                        break
        except Exception as e:
            logger.warning(f"Session scan failed: {e}")

    return files


async def receive_submission(tool_context: ToolContext, submission_name: str = "") -> dict:
    """Receives uploaded submission files from Gemini Enterprise UI and saves to GCS.

    Call this when the user uploads files directly in the chat.
    Files are saved to a new GCS folder and the folder URI is returned.

    Args:
        tool_context: ADK tool context (automatically provided, contains uploaded files).
        submission_name: Optional name for the submission folder. Auto-generated if empty.

    Returns:
        Dict with gcs_folder_uri and list of saved files.
    """
    logger.info("Tool: receive_submission")

    files = _extract_file_from_context(tool_context)
    if not files:
        return {"error": "No files found. Please upload PDF files directly in the chat."}

    # Generate folder name
    if not submission_name:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        submission_name = f"SUB-{timestamp}"

    folder_path = f"submissions/{submission_name}"
    bucket = gcs_client.bucket(BUCKET_NAME)

    saved_files = []
    for file_bytes, file_name in files:
        blob_path = f"{folder_path}/{file_name}"
        blob = bucket.blob(blob_path)
        mime = "application/pdf" if file_name.lower().endswith(".pdf") else "application/octet-stream"
        blob.upload_from_string(file_bytes, content_type=mime)
        saved_files.append({"filename": file_name, "gcs_uri": f"gs://{BUCKET_NAME}/{blob_path}", "size_bytes": len(file_bytes)})
        logger.info(f"Saved: {blob_path} ({len(file_bytes)} bytes)")

    gcs_folder_uri = f"gs://{BUCKET_NAME}/{folder_path}/"
    logger.info(f"Submission saved to {gcs_folder_uri} ({len(saved_files)} files)")

    return {
        "gcs_folder_uri": gcs_folder_uri,
        "submission_name": submission_name,
        "files_saved": saved_files,
        "file_count": len(saved_files),
    }


def call_sub_agent(agent_id: str, prompt: str, max_retries: int = 3) -> dict:
    """Call a deployed Vertex AI Agent Engine and return its response."""
    for attempt in range(max_retries):
        try:
            logger.info(f"Calling agent {agent_id.split('/')[-1]} (attempt {attempt + 1})")
            remote_agent = agent_engines.get(agent_id)
            full_response = []
            for event in remote_agent.stream_query(message=prompt, user_id="uw-orchestrator"):
                content = event.get("content", {})
                for part in content.get("parts", []):
                    if "text" in part:
                        full_response.append(part["text"])
            result = "".join(full_response)
            logger.info(f"Agent responded: {len(result)} chars")
            return {"result": result if result else "No response received"}
        except Exception as e:
            logger.error(f"Error calling agent (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                return {"error": str(e)}
    return {"error": "Maximum retries exceeded"}


def _gcs_path(gcs_folder_uri: str, filename: str) -> str:
    """Build GCS blob path from folder URI and filename."""
    prefix = gcs_folder_uri.replace(f"gs://{BUCKET_NAME}/", "").strip("/")
    return f"{prefix}/{filename}"


def _save_to_gcs(gcs_folder_uri: str, filename: str, data: dict):
    """Save JSON data to GCS."""
    blob_path = _gcs_path(gcs_folder_uri, filename)
    bucket = gcs_client.bucket(BUCKET_NAME)
    blob = bucket.blob(blob_path)
    blob.upload_from_string(json.dumps(data, indent=2), content_type="application/json")
    logger.info(f"Saved to gs://{BUCKET_NAME}/{blob_path}")


def _load_from_gcs(gcs_folder_uri: str, filename: str) -> dict:
    """Load JSON data from GCS."""
    blob_path = _gcs_path(gcs_folder_uri, filename)
    bucket = gcs_client.bucket(BUCKET_NAME)
    blob = bucket.blob(blob_path)
    return json.loads(blob.download_as_text())


def _extract_json_from_response(text: str) -> dict:
    """Extract JSON from agent response text (may be wrapped in markdown code blocks)."""
    text = text.strip()
    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if match:
        text = match.group(1).strip()
    # Fix Python booleans/None in response
    text = text.replace(": True", ": true").replace(": False", ": false").replace(": None", ": null")
    try:
        parsed = json.loads(text)
        # Handle wrapped responses like {"process_submission_response": {...}}
        if isinstance(parsed, dict) and len(parsed) == 1:
            key = list(parsed.keys())[0]
            if key.endswith("_response"):
                return parsed[key]
        return parsed
    except json.JSONDecodeError:
        return {"raw_text": text}


def _log_error(gcs_folder: str, step: str, error: str, last_step: str = "none"):
    """Auto-log processing error to BigQuery."""
    try:
        from submission_agent.tools import log_processing_error
        log_processing_error(gcs_folder, step, error, last_step)
    except Exception:
        logger.error(f"Failed to log error: {step} — {error}")


def classify_submission(gcs_folder_uri: str) -> dict:
    """Classifies insurance submission documents in a GCS folder.

    Args:
        gcs_folder_uri: GCS folder URI e.g. gs://underwriting-workbench/Sample 1/

    Returns:
        Dict with classification results.
    """
    try:
        result = call_sub_agent(CLASSIFICATION_AGENT_ID, f"Classify the documents in {gcs_folder_uri}")
        if isinstance(result, dict) and "error" in result:
            _log_error(gcs_folder_uri, "classification", str(result["error"]))
        return result
    except Exception as e:
        _log_error(gcs_folder_uri, "classification", str(e))
        return {"error": str(e)}


def extract_submission(gcs_folder_uri: str, classifications_json: str) -> dict:
    """Extracts structured fields from pre-classified submission documents.
    The deployed Extraction Agent saves results directly to GCS (_extracted_fields.json).

    Args:
        gcs_folder_uri: GCS folder URI.
        classifications_json: JSON string mapping filename to type.

    Returns:
        Dict with extraction result.
    """
    try:
        result = call_sub_agent(EXTRACTION_AGENT_ID, f"Process this submission. Folder: {gcs_folder_uri}  Classifications: {classifications_json}")

        # Verify the file was saved to GCS by the agent
        try:
            extracted = _load_from_gcs(gcs_folder_uri, "_extracted_fields.json")
            logger.info(f"Verified _extracted_fields.json in GCS: insured={extracted.get('insured_name')}")
        except Exception:
            # Fallback: parse from response and save (in case agent didn't save)
            logger.warning("Agent didn't save to GCS, parsing response and saving...")
            parsed = _extract_json_from_response(result.get("result", ""))
            extracted = parsed.get("extracted_fields", parsed)

            # Enrichment fallback
            eq_order = {"No": 0, "Low": 1, "Medium": 2, "High": 3}
            if eq_order.get(extracted.get("flood_zone") or "No", 0) == 0:
                from extraction_agent.location_risk import enrich_location_risk
                addr = extracted.get("premises_address") or extracted.get("mailing_address")
                locations = extracted.get("locations") or []
                if not addr and locations:
                    addr = locations[0].get("address")
                if addr:
                    risk = enrich_location_risk(addr)
                    if risk.get("found"):
                        extracted["eq_zone"] = risk.get("eq_zone", "No")
                        extracted["flood_zone"] = risk.get("flood_zone", "No")
                        extracted["location_risk_enrichment"] = [risk]

            _save_to_gcs(gcs_folder_uri, "_extracted_fields.json", extracted)

        return {"result": result.get("result", ""), "saved_to_gcs": True}
    except Exception as e:
        _log_error(gcs_folder_uri, "extraction", str(e), "classification")
        return {"error": str(e)}


def fetch_rules() -> dict:
    """Fetches all underwriting business rules from GCS.

    Returns:
        Dict with priority, risk_score, and assignment rules.
    """
    try:
        from rules_update_agent.tools import get_all_rules as _get
        result = _get()
        return json.loads(result) if isinstance(result, str) else result
    except Exception as e:
        _log_error("", "fetch_rules", str(e), "extraction")
        return {"error": str(e)}


def fetch_client_history(client_name: str, identifiers: str = "{}") -> dict:
    """Fetches client history by fuzzy-matching the client name.

    Args:
        client_name: The insured company name.
        identifiers: Optional JSON string with identifiers for confirmation.

    Returns:
        Dict with client history and match confidence.
    """
    return call_sub_agent(CLIENT_HISTORY_AGENT_ID, f"Look up client history for '{client_name}' with identifiers: {identifiers}")


def evaluate_uw_rules(gcs_folder_uri: str, rules_json: str = "", client_history_json: str = "{}") -> dict:
    """Applies underwriting rules to extracted submission fields.
    Reads extracted fields from GCS, fetches rules directly if not provided.

    Args:
        gcs_folder_uri: GCS folder URI.
        rules_json: JSON string with all rules from fetch_rules. If empty, fetches directly.
        client_history_json: Optional JSON string with client history.

    Returns:
        Dict with priority, risk_score, risk_level, assigned_to, auto_decline.
    """
    from uw_rules_agent.tools import apply_uw_rules as _apply

    try:
        extracted = _load_from_gcs(gcs_folder_uri, "_extracted_fields.json")

        # Apply enrichment
        enrichment = extracted.get("location_risk_enrichment") or []
        eq_order = {"No": 0, "Low": 1, "Medium": 2, "High": 3}
        for loc_risk in enrichment:
            if loc_risk.get("found"):
                if eq_order.get(loc_risk.get("eq_zone", "No"), 0) > eq_order.get(extracted.get("eq_zone", "No"), 0):
                    extracted["eq_zone"] = loc_risk["eq_zone"]
                if eq_order.get(loc_risk.get("flood_zone", "No"), 0) > eq_order.get(extracted.get("flood_zone", "No"), 0):
                    extracted["flood_zone"] = loc_risk["flood_zone"]

        # Parse rules — handle dict, string, or fetch directly if empty/invalid
        rules_parsed = None
        if rules_json:
            if isinstance(rules_json, dict):
                rules_parsed = rules_json
            else:
                rules_parsed = _extract_json_from_response(rules_json)
        # Validate rules have actual content
        if not rules_parsed or not rules_parsed.get("rules", rules_parsed).get("risk_score"):
            from rules_update_agent.tools import get_all_rules as _get_rules
            rules_raw = _get_rules()
            rules_parsed = json.loads(rules_raw) if isinstance(rules_raw, str) else rules_raw

        rules_str = json.dumps(rules_parsed)

        # Direct Python call — always correct
        result = _apply(json.dumps(extracted), rules_str, client_history_json)

        # Save to GCS
        _save_to_gcs(gcs_folder_uri, "_uw_result.json", result)

        return result
    except Exception as e:
        _log_error(gcs_folder_uri, "evaluate_uw_rules", str(e), "client_history")
        return {"error": str(e)}


def save_submission(gcs_folder_uri: str, existing_case_id: str = "") -> dict:
    """Saves the submission record to BigQuery.
    Reads extracted fields and UW result from GCS.
    Automatically detects if a record already exists for this folder and updates it.

    Args:
        gcs_folder_uri: GCS folder URI — reads _extracted_fields.json and _uw_result.json.
        existing_case_id: Optional — if provided, update this case. Otherwise auto-detects.

    Returns:
        Dict with case_id, status, and assigned_to.
    """
    from submission_agent.tools import create_submission as _create, update_submission as _update_sub, _auto_resolve_errors
    from google.cloud import bigquery as _bq
    try:
        extracted = _load_from_gcs(gcs_folder_uri, "_extracted_fields.json")
        uw_result = _load_from_gcs(gcs_folder_uri, "_uw_result.json")

        # Auto-detect existing case for this folder
        if not existing_case_id:
            _client = _bq.Client(project="gbu-demo-playground")
            rows = list(_client.query(
                f"SELECT case_id FROM `gbu-demo-playground.underwriting_workbench.submissions` WHERE gcs_folder = @f AND status = 'Pending Classification' LIMIT 1",
                job_config=_bq.QueryJobConfig(query_parameters=[_bq.ScalarQueryParameter("f", "STRING", gcs_folder_uri)])
            ).result())
            if rows:
                existing_case_id = rows[0].case_id

        if existing_case_id:
            updates = {
                "insured_name": extracted.get("insured_name"),
                "mailing_address": extracted.get("mailing_address"),
                "fein": extracted.get("fein"),
                "sic_code": extracted.get("sic_code"),
                "lob": extracted.get("lob"),
                "effective_date": extracted.get("effective_date"),
                "expiration_date": extracted.get("expiration_date"),
                "renewal_days": extracted.get("renewal_days"),
                "broker": extracted.get("broker"),
                "proposed_carrier": extracted.get("proposed_carrier"),
                "sum_insured": extracted.get("sum_insured"),
                "no_of_employees": extracted.get("no_of_employees"),
                "year_built": extracted.get("year_built"),
                "construction_type": extracted.get("construction_type"),
                "eq_zone": extracted.get("eq_zone"),
                "flood_zone": extracted.get("flood_zone"),
                "risk_score": uw_result.get("risk_score"),
                "risk_level": uw_result.get("risk_level"),
                "priority": uw_result.get("priority"),
                "override_reasons": json.dumps(uw_result.get("override_reasons", [])),
                "assigned_to": uw_result.get("assigned_to"),
                "status": "Assigned",
                "auto_decline": uw_result.get("auto_decline", False),
                "decline_reason": uw_result.get("decline_reason"),
                "extracted_json": json.dumps(extracted),
                "uw_result_json": json.dumps(uw_result),
            }
            _update_sub(existing_case_id, json.dumps(updates))
            _auto_resolve_errors(gcs_folder_uri)
            return {"case_id": existing_case_id, "status": "Assigned", "assigned_to": uw_result.get("assigned_to")}
        else:
            result = _create(json.dumps(extracted), json.dumps(uw_result), gcs_folder_uri)
            if "case_id" in result:
                _auto_resolve_errors(gcs_folder_uri)
            elif "error" in result:
                _log_error(gcs_folder_uri, "save", str(result["error"]), "evaluate_uw_rules")
            return result
    except Exception as e:
        _log_error(gcs_folder_uri, "save", str(e), "evaluate_uw_rules")
        return {"error": str(e)}


def record_decision(case_id: str, decision: str, decision_by: str = "Underwriter") -> dict:
    """Records the underwriter's accept or decline decision.

    Args:
        case_id: The Case ID e.g. NB-26-34677
        decision: 'accept' or 'decline'
        decision_by: Name of the underwriter.

    Returns:
        Dict with updated status and decision timestamp.
    """
    from submission_agent.tools import update_submission_decision as _update
    return _update(case_id, decision, decision_by)


def get_submission(case_id: str) -> dict:
    """Retrieves a submission record by Case ID.

    Args:
        case_id: The Case ID e.g. NB-26-34677

    Returns:
        Dict with all submission fields.
    """
    from submission_agent.tools import get_submission as _get
    return _get(case_id)


def update_submission(case_id: str, updates_json: str) -> dict:
    """Updates specific fields on a submission record.

    Args:
        case_id: The Case ID e.g. NB-26-34677
        updates_json: JSON string with fields to update.

    Returns:
        Dict with case_id and list of updated fields.
    """
    from submission_agent.tools import update_submission as _update
    return _update(case_id, updates_json)


def list_submissions(status: str = "", assigned_to: str = "", limit: int = 20) -> dict:
    """Lists submission records with optional filters.

    Args:
        status: Filter by status. Empty for all.
        assigned_to: Filter by underwriter name. Empty for all.
        limit: Max records to return.

    Returns:
        Dict with list of submissions.
    """
    from submission_agent.tools import list_submissions as _list
    return _list(status, assigned_to, limit)


def justify_submission(case_id: str) -> dict:
    """Generates a deterministic justification for every decision made on a submission.

    Args:
        case_id: The Case ID e.g. NB-26-34705

    Returns:
        Dict with detailed justification for priority, risk score, assignment, and auto-decline.
    """
    from submission_agent.tools import justify_submission as _justify
    return _justify(case_id)


def get_prioritized_workload(assigned_to: str = "") -> dict:
    """Gets submissions ranked by smart urgency score for an underwriter.

    Considers: priority level, effective date urgency, risk score, sum insured.
    Only shows pending/assigned submissions.

    Args:
        assigned_to: Underwriter name. Empty for all.

    Returns:
        Dict with ranked submissions, summary stats, and recommendation.
    """
    from submission_agent.tools import get_prioritized_workload as _get
    return _get(assigned_to)


def update_review_status(case_id: str, review_status: str) -> dict:
    """Updates the review status of a submission (Pending/In Review/Reviewed/Complete).

    Args:
        case_id: The Case ID.
        review_status: One of Pending, In Review, Reviewed, Complete.

    Returns:
        Dict with updated status.
    """
    from submission_agent.tools import update_review_status as _update
    return _update(case_id, review_status)


def log_processing_error(gcs_folder: str, error_step: str, error_message: str, last_successful_step: str = "none", partial_data: str = "{}") -> dict:
    """Logs a processing error to BigQuery when any pipeline step fails.

    Args:
        gcs_folder: GCS folder URI that failed.
        error_step: Step that failed (classification, extraction, fetch_rules, client_history, evaluate_uw_rules, save).
        error_message: The error message.
        last_successful_step: Last step that completed successfully.
        partial_data: JSON string of any data collected before failure.

    Returns:
        Dict with error_id and confirmation.
    """
    from submission_agent.tools import log_processing_error as _log
    return _log(gcs_folder, error_step, error_message, last_successful_step, partial_data)


def get_processing_errors(resolved: bool = False) -> dict:
    """Lists processing errors — failed submissions that need attention.

    Args:
        resolved: If True, show resolved errors. If False (default), show unresolved.

    Returns:
        Dict with list of errors and count.
    """
    from submission_agent.tools import get_processing_errors as _get
    return _get(resolved)


def resolve_processing_error(error_id: str, resolved_by: str = "System") -> dict:
    """Marks a processing error as resolved after retry or manual fix.

    Args:
        error_id: The error ID to resolve.
        resolved_by: Who resolved it.

    Returns:
        Dict with confirmation.
    """
    from submission_agent.tools import resolve_processing_error as _resolve
    return _resolve(error_id, resolved_by)


def save_pending_classification(gcs_folder: str, classification_results: str) -> dict:
    """Saves a partial submission with status 'Pending Classification' when confidence < 80.

    Args:
        gcs_folder: GCS folder URI.
        classification_results: JSON string with file classifications and confidence scores.

    Returns:
        Dict with case_id and status.
    """
    from submission_agent.tools import save_pending_classification as _save
    return _save(gcs_folder, classification_results)
