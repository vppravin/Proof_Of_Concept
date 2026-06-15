import os
import json
import logging
from datetime import date

from google.cloud import storage
import vertexai
from vertexai.generative_models import GenerativeModel, Part
from extraction_agent.location_risk import enrich_location_risk

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
LOCATION = os.getenv("LOCATION", "us-central1")
BUCKET_NAME = os.getenv("BUCKET_NAME", "underwriting-workbench")

vertexai.init(project=PROJECT_ID, location=LOCATION)
gcs_client = storage.Client(project=PROJECT_ID)
model = GenerativeModel("gemini-2.0-flash-001")

MIME_MAP = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "tiff": "image/tiff",
    "tif": "image/tiff",
    "txt": "text/plain",
}

# ── Type-specific extraction prompts ───────────────────────────────────────

PROMPTS = {
    "ACORD_125": """You are an expert insurance document parser. Extract fields from this ACORD 125 Commercial Insurance Application.
Return ONLY a valid JSON object — no explanation, no markdown.

Fields to extract:
- insured_name (string)
- dba (string)
- mailing_address (string)
- fein (string)
- sic_code (string)
- naics_code (string)
- business_type (string)
- nature_of_business (string)
- years_in_business (number)
- contact_person (string)
- contact_phone (string)
- contact_email (string)
- lob (string) — Line of Business. Must be one of: "Commercial Property", "Workers Compensation", "Cyber", "Commercial Liability", "Marine", "Commercial Auto", "General Liability". Use the closest match from this list.
- broker (string) — broker agency name. Extract the core broker/agency name (e.g. "Aon" not "Aon Broking", "Marsh" not "Marsh Brokers", "AJG" for Arthur J. Gallagher).
- broker_contact (string)
- broker_phone (string)
- broker_email (string)
- broker_license (string)
- effective_date (string, YYYY-MM-DD)
- expiration_date (string, YYYY-MM-DD)
- prior_policy_number (string)
- proposed_carrier (string)
- sum_insured (number) — total insured value if mentioned, otherwise null
- no_of_employees (number) — total employees all locations (full time + part time)
- locations (array of objects with: loc_number, address, city, state, zip, occupancy, total_area_sqft, stories, employees)
- prior_insurance (object with: current_carrier, current_policy, current_premium, non_renewals)
- loss_history (array of objects with: date_of_loss, date_reported, description, paid_amount, reserved_amount, total_incurred, status, subrogation) — extract from the Loss History section on the last page if present
- total_claims (number) — count of claims in loss history
- total_incurred (number) — sum of all loss amounts
- prior_losses_5yr (boolean)

If a field is not found, set to null. Return only JSON.""",

    "ACORD_140": """You are an expert insurance document parser. Extract fields from this ACORD 140 Property Section form.
Return ONLY a valid JSON object — no explanation, no markdown.

Fields to extract:
- insured_name (string) — the applicant/first named insured
- effective_date (string, YYYY-MM-DD)
- expiration_date (string, YYYY-MM-DD)
- broker (string) — agency name
- sum_insured (number) — TOTAL insured value: sum of ALL coverage amounts (Building + Business Personal Property + any other covered amounts). Add them all up into one number.
- locations (array of objects with: loc_number, address, building_description, total_area_sqft, stories, basements, year_built, construction_type, roof_type, fire_alarm, fire_alarm_manufacturer, sprinkler_system, sprinkler_pct, burglar_alarm_type, security_guards, fire_protection_class)
  - IMPORTANT: "PREMISES #" or "LOC #" is the location number, NOT the number of stories. The "# STORIES" field is a separate field — look for it explicitly. Do not confuse premises number with stories count.
  - construction_type: MUST be normalized to one of these canonical values: "Fire-resistive", "Non-Combustible", "Ordinary", "Heavy timber", "Frame". Use your insurance domain knowledge to map:
    * RCC, Reinforced Concrete, Concrete, Steel, Metal, Non-combustible → "Non-Combustible"
    * Jointed Masonry, Masonry, Brick, Block → "Ordinary"
    * Wood Frame, Wood, Light Frame → "Frame"
    * Fire Resistive, Fire-resistive, Type I → "Fire-resistive"
    * Heavy Timber, Mill Construction, Type IV → "Heavy timber"
    * For any other value, use your best insurance knowledge to pick the closest canonical type.
  - year_built: extract as a 4-digit year number (e.g. 2016, 1987)
- coverage (array of objects with: subject_of_insurance, amount, coinsurance_pct, causes_of_loss, deductible, valuation)
- hazards (object with per-location: eq_zone, flood_zone, fema_panel)
  - eq_zone: normalize to one of: "No", "Low", "Medium", "High". If not mentioned or N/A, use "No".
  - flood_zone: normalize to one of: "No", "Low", "Medium", "High". If not mentioned or N/A, use "No".

If a field is not found, set to null. Return only JSON.""",

    "LOSS_RUN": """You are an expert insurance document parser. Extract loss run / claims history from this document.
Return ONLY a valid JSON object — no explanation, no markdown.

Fields to extract:
- insured_name (string)
- reporting_period_start (string, YYYY-MM-DD)
- reporting_period_end (string, YYYY-MM-DD)
- carrier (string)
- policy_numbers (array of strings)
- loss_history (array of objects with: policy_year, date_of_loss, date_reported, location_number, cause_of_loss, description, claim_number, paid_amount, reserved_amount, total_incurred, status, subrogation_recovery)
- total_claims (number)
- total_incurred (number)
- large_losses (array of objects with: claim_number, amount, description — for claims >= $100,000)

If a field is not found, set to null. Return only JSON.""",

    "EMAIL": """You are an expert insurance document parser. Extract key information from this email / communication transcript.
Return ONLY a valid JSON object — no explanation, no markdown.

Fields to extract:
- insured_name (string)
- submission_id (string)
- participants (array of objects with: name, role, email)
- urgency (string — e.g. "High", "Normal")
- key_dates (object with: quote_deadline, bind_deadline, effective_date — all YYYY-MM-DD)
- clarifications (array of objects with: question, answer — any Q&A from the thread)
- additional_context (array of strings — any extra info not in formal documents)
- attachments_referenced (array of strings)

If a field is not found, set to null. Return only JSON.""",
}

GENERIC_PROMPT = """You are an expert insurance document parser. Extract ALL relevant insurance fields from this document.
Return ONLY a valid JSON object — no explanation, no markdown.
Extract any fields related to: insured name, line of business, broker, coverage, locations, loss history, risk details, dates, premiums.
If a field is not found, set to null. Return only JSON."""


def _parse_gcs_path(gcs_uri: str):
    path = gcs_uri.replace("gs://", "")
    return path.split("/", 1)


def _parse_gemini_response(raw_text: str) -> dict:
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()
    return json.loads(raw_text)


# ── Tool functions ─────────────────────────────────────────────────────────

def extract_fields(gcs_uri: str, file_type: str = "UNKNOWN") -> dict:
    """Extracts structured fields from a single submission document using Gemini Flash.

    Uses a type-specific prompt based on the pre-classified document type.

    Args:
        gcs_uri: GCS URI of the file.
        file_type: Pre-classified document type from Classification Agent — one of ACORD, LOSS_RUN, EMAIL, UNKNOWN.

    Returns:
        Dict with extracted_fields JSON and metadata.
    """
    logger.info(f"Tool: extract_fields for {gcs_uri} (type={file_type})")
    try:
        if not gcs_uri.startswith("gs://"):
            return {"error": f"Invalid GCS URI: {gcs_uri}"}

        ext = gcs_uri.lower().rsplit(".", 1)[-1]
        mime_type = MIME_MAP.get(ext, "application/pdf")

        prompt = PROMPTS.get(file_type, GENERIC_PROMPT)
        file_part = Part.from_uri(uri=gcs_uri, mime_type=mime_type)

        logger.info(f"Calling Gemini Flash for {file_type} extraction...")
        response = model.generate_content([file_part, prompt])
        extracted = _parse_gemini_response(response.text)

        logger.info(f"Extraction OK for {gcs_uri}")
        return {"gcs_uri": gcs_uri, "file_type": file_type, "extracted_fields": extracted}

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error for {gcs_uri}: {e}")
        return {"gcs_uri": gcs_uri, "file_type": file_type, "error": f"Non-JSON response: {e}"}
    except Exception as e:
        logger.error(f"Extraction error for {gcs_uri}: {e}")
        return {"gcs_uri": gcs_uri, "file_type": file_type, "error": str(e)}


def process_submission(gcs_folder_uri: str, classifications: str) -> dict:
    """Processes a multi-file insurance submission using pre-classified file types.

    Receives the approved classification map from the Orchestrator (originally from
    the Classification Agent after human approval). Extracts each file using its
    pre-classified type and merges into a unified JSON.

    Args:
        gcs_folder_uri: GCS folder URI e.g. gs://underwriting-workbench/submissions/NB-25-34677/
        classifications: JSON string mapping filename to type e.g. '{"ACORD.pdf": "ACORD", "LossRun.pdf": "LOSS_RUN"}'

    Returns:
        Dict with unified extracted fields merged from all documents.
    """
    logger.info(f"Tool: process_submission for {gcs_folder_uri}")

    try:
        class_map = json.loads(classifications) if isinstance(classifications, str) else classifications
    except json.JSONDecodeError as e:
        return {"error": f"Invalid classifications JSON: {e}"}

    folder = gcs_folder_uri.rstrip("/") + "/"

    extractions = {}
    files_processed = []
    for filename, file_type in class_map.items():
        gcs_uri = f"{folder}{filename}" if not filename.startswith("gs://") else filename
        if file_type == "UNKNOWN":
            files_processed.append({"file": filename, "type": file_type, "status": "skipped"})
            continue
        result = extract_fields(gcs_uri, file_type)
        status = "extracted" if "extracted_fields" in result else "failed"
        files_processed.append({"file": filename, "type": file_type, "status": status})
        if status == "extracted":
            extractions[file_type] = result["extracted_fields"]

    unified = _merge_extractions(extractions, gcs_folder_uri)
    unified["files_processed"] = files_processed

    logger.info(f"Submission processed: {len(files_processed)} files, insured={unified.get('insured_name')}")
    return {"extracted_fields": unified}


# ── Merge helpers ──────────────────────────────────────────────────────────

def _safe_zone(raw) -> str:
    """Return zone value as-is from Gemini (already normalized by prompt), default to 'No'."""
    if not raw or str(raw).strip().lower() in ("none", "n/a", "null", ""):
        return "No"
    return str(raw).strip()


def _extract_submission_id(extractions: dict, gcs_folder_uri: str) -> str:
    """Extract submission/case ID from email data or folder name."""
    email = extractions.get("EMAIL", {})
    sid = email.get("submission_id")
    if sid:
        return sid
    parts = gcs_folder_uri.rstrip("/").split("/")
    return parts[-1] if parts else None


def _merge_extractions(extractions: dict, gcs_folder_uri: str) -> dict:
    """Merges extractions from ACORD_125, ACORD_140, LOSS_RUN, and EMAIL into one unified JSON."""

    submission_id = _extract_submission_id(extractions, gcs_folder_uri)

    acord_125 = extractions.get("ACORD_125", {})
    acord_140 = extractions.get("ACORD_140", {})
    loss_run = extractions.get("LOSS_RUN", {})
    email = extractions.get("EMAIL", {})

    # ACORD 125 is primary for applicant/policy info, ACORD 140 supplements with building details
    effective_date = acord_125.get("effective_date") or acord_140.get("effective_date")
    renewal_days = None
    if effective_date:
        try:
            renewal_days = (date.fromisoformat(effective_date) - date.today()).days
        except ValueError:
            pass

    # Locations: prefer ACORD 140 (detailed building info), fall back to ACORD 125
    locations = acord_140.get("locations") or acord_125.get("locations") or []
    construction_order = {"Fire-resistive": 0, "Non-Combustible": 1, "Ordinary": 2, "Frame": 3, "Heavy timber": 4}

    oldest_year = None
    worst_construction = None
    worst_eq = "No"
    worst_flood = "No"
    eq_order = {"No": 0, "Low": 1, "Medium": 2, "High": 3}

    hazards = acord_140.get("hazards") or acord_125.get("hazards") or {}
    for loc in locations:
        yb = loc.get("year_built")
        if yb and (oldest_year is None or yb < oldest_year):
            oldest_year = yb
        ct = loc.get("construction_type")
        if ct and construction_order.get(ct, 99) > construction_order.get(worst_construction, -1):
            worst_construction = ct
        loc_eq = _safe_zone(loc.get("eq_zone"))
        loc_fl = _safe_zone(loc.get("flood_zone"))
        if eq_order.get(loc_eq, 0) > eq_order.get(worst_eq, 0):
            worst_eq = loc_eq
        if eq_order.get(loc_fl, 0) > eq_order.get(worst_flood, 0):
            worst_flood = loc_fl

    for key, val in hazards.items():
        if isinstance(val, dict):
            eq = _safe_zone(val.get("eq_zone"))
            fl = _safe_zone(val.get("flood_zone"))
            if eq_order.get(eq, 0) > eq_order.get(worst_eq, 0):
                worst_eq = eq
            if eq_order.get(fl, 0) > eq_order.get(worst_flood, 0):
                worst_flood = fl
        elif isinstance(val, str):
            if "eq" in key.lower():
                eq = _safe_zone(val)
                if eq_order.get(eq, 0) > eq_order.get(worst_eq, 0):
                    worst_eq = eq
            if "flood" in key.lower():
                fl = _safe_zone(val)
                if eq_order.get(fl, 0) > eq_order.get(worst_flood, 0):
                    worst_flood = fl

    key_dates = email.get("key_dates") or {}

    # Enrich EQ/flood zones from federal APIs if not found in documents
    location_risk_data = []
    if worst_eq == "No" and worst_flood == "No" and locations:
        for loc in locations:
            addr = loc.get("address")
            if not addr:
                continue
            risk = enrich_location_risk(addr)
            location_risk_data.append(risk)
            if risk.get("geocoded"):
                enriched_eq = risk.get("eq_zone", "No")
                enriched_fl = risk.get("flood_zone", "No")
                if eq_order.get(enriched_eq, 0) > eq_order.get(worst_eq, 0):
                    worst_eq = enriched_eq
                if eq_order.get(enriched_fl, 0) > eq_order.get(worst_flood, 0):
                    worst_flood = enriched_fl

    # Sum insured: prefer ACORD 140 (has coverage line items), fall back to 125
    sum_insured = acord_140.get("sum_insured") or acord_125.get("sum_insured")

    return {
        "submission_id": submission_id,
        "insured_name": acord_125.get("insured_name") or acord_140.get("insured_name") or loss_run.get("insured_name") or email.get("insured_name"),
        "lob": acord_125.get("lob"),
        "broker": acord_125.get("broker") or acord_140.get("broker"),
        "effective_date": effective_date,
        "expiration_date": acord_125.get("expiration_date") or acord_140.get("expiration_date"),
        "sum_insured": sum_insured,
        "renewal_days": renewal_days,
        "no_of_employees": acord_125.get("no_of_employees"),

        "year_built": oldest_year,
        "construction_type": worst_construction,
        "eq_zone": worst_eq,
        "flood_zone": worst_flood,
        "roof_type": locations[0].get("roof_type") if locations else None,
        "fire_protection": locations[0].get("fire_alarm") if locations else None,

        "locations": locations,
        "coverage": acord_140.get("coverage") or acord_125.get("coverage"),
        "prior_insurance": acord_125.get("prior_insurance"),

        "loss_history": loss_run.get("loss_history") or acord_125.get("loss_history"),
        "total_claims": loss_run.get("total_claims") or acord_125.get("total_claims"),
        "total_incurred": loss_run.get("total_incurred") or acord_125.get("total_incurred"),
        "large_losses": loss_run.get("large_losses"),

        "additional_context": {
            "urgency": email.get("urgency"),
            "clarifications": email.get("clarifications"),
            "extra_info": email.get("additional_context"),
            "quote_deadline": key_dates.get("quote_deadline"),
            "bind_deadline": key_dates.get("bind_deadline"),
        } if email else None,
        "location_risk_enrichment": location_risk_data if location_risk_data else None,
    }
