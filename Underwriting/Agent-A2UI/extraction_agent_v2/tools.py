"""Extraction Agent v2 — Uses Document AI Form Parser for ACORD forms, Gemini Flash for others."""

import os
import json
import re
import logging
from datetime import date

from google.cloud import storage, documentai_v1 as documentai
import vertexai
from vertexai.generative_models import GenerativeModel, Part

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
LOCATION = os.getenv("LOCATION", "us-central1")
BUCKET_NAME = os.getenv("BUCKET_NAME", "underwriting-workbench")
DOCAI_PROCESSOR = os.getenv("DOCAI_PROCESSOR", "projects/146646146609/locations/us/processors/5580fe010b37636d")

vertexai.init(project=PROJECT_ID, location=LOCATION)
gcs_client = storage.Client(project=PROJECT_ID)
docai_client = documentai.DocumentProcessorServiceClient()
gemini_model = GenerativeModel("gemini-2.0-flash-001")

# Field name mappings: Document AI field name → our schema field name
ACORD_125_FIELD_MAP = {
    "FEIN OR SOC SEC #": "fein",
    "SIC": "sic_code",
    "NAICS": "naics_code",
    "BUSINESS PHONE #:": "contact_phone",
    "PROPOSED EFF DATE": "effective_date",
    "PROPOSED EXP DATE": "expiration_date",
    "CARRIER": "proposed_carrier",
    "NAIC CODE": "naic_code",
    "WEBSITE ADDRESS": "website",
    "TOTAL LOSSES:": "total_incurred",
    "CONTACT NAME:": "contact_person",
    "PRIMARY E-MAIL ADDRESS:": "contact_email",
    "DATE BUSINESS STARTED (MM/DD/YYYY)": "date_business_started",
}

ACORD_140_FIELD_MAP = {
    "YR BUILT": "year_built",
    "CONSTRUCTION TYPE": "construction_type",
    "ROOF TYPE": "roof_type",
    "% SPRNK": "sprinkler_pct",
    "# GUARDS/WATCHMEN": "security_guards",
    "BURGLAR ALARM TYPE": "burglar_alarm_type",
    "FIRE ALARM MANUFACTURER": "fire_alarm_manufacturer",
    "PROT CL #": "fire_protection_class",
    "TOTAL": "total_area",
}


def _extract_with_docai(pdf_content: bytes) -> tuple:
    """Extract form fields from a PDF using Document AI Form Parser.
    Returns (fields_dict, fields_list) — dict for unique lookups, list for duplicates like employees."""
    raw_document = documentai.RawDocument(content=pdf_content, mime_type="application/pdf")
    request = documentai.ProcessRequest(name=DOCAI_PROCESSOR, raw_document=raw_document)
    result = docai_client.process_document(request=request)

    fields = {}
    fields_list = []
    for page in result.document.pages:
        for field in page.form_fields:
            name = field.field_name.text_anchor.content.strip().replace("\n", " ") if field.field_name.text_anchor else ""
            value = field.field_value.text_anchor.content.strip().replace("\n", " ") if field.field_value.text_anchor else ""
            confidence = field.field_name.confidence
            if name and value and confidence > 0.4:
                fields[name] = {"value": value, "confidence": confidence}
                fields_list.append({"name": name, "value": value, "confidence": confidence})
    return fields, fields_list, result.document.text


def _parse_acord_125(fields: dict, fields_list: list) -> dict:
    """Map Document AI fields to our ACORD 125 schema."""
    result = {}

    # Direct field mappings
    for docai_name, our_name in ACORD_125_FIELD_MAP.items():
        for field_name, field_data in fields.items():
            if docai_name.lower() in field_name.lower():
                result[our_name] = field_data["value"]
                break

    # Special parsing: Insured name + mailing address
    for field_name, field_data in fields.items():
        if "First Named Insured" in field_name:
            parts = field_data["value"].split("\n") if "\n" in field_data["value"] else field_data["value"].split("  ")
            if len(parts) >= 2:
                result["insured_name"] = parts[0].strip()
                result["mailing_address"] = " ".join(parts[1:]).strip()
            else:
                val = field_data["value"]
                match = re.search(r'(\d+\s+\w+)', val)
                if match:
                    result["insured_name"] = val[:match.start()].strip()
                    result["mailing_address"] = val[match.start():].strip()
                else:
                    result["insured_name"] = val
            break

    # Agency/Broker — extract the agency name, trim address if present
    for field_name, field_data in fields.items():
        if field_name == "AGENCY" and len(field_data["value"]) > 5:
            broker_val = field_data["value"].split("\n")[0].strip()
            # Remove address portion (number followed by street name)
            addr_match = re.search(r'\s+\d+\s+\w+', broker_val)
            if addr_match:
                broker_val = broker_val[:addr_match.start()].strip()
            result["broker"] = broker_val
            break

    # LoB
    for field_name, field_data in fields.items():
        if "COMMERCIAL PROPERTY" in field_name and field_data["value"] == "☑":
            result["lob"] = "Commercial Property"
            break
        elif "COMPANY POLICY OR PROGRAM NAME" in field_name:
            result["lob"] = field_data["value"]
            break

    # Employees - sum ALL FT and PT from fields_list (handles duplicates)
    ft_total = 0
    pt_total = 0
    for f in fields_list:
        if "FULL TIME EMPL" in f["name"]:
            try:
                ft_total += int(f["value"])
            except ValueError:
                pass
        elif "PART TIME EMPL" in f["name"]:
            try:
                pt_total += int(f["value"])
            except ValueError:
                pass
    if ft_total or pt_total:
        result["no_of_employees"] = ft_total + pt_total

    # Loss total from form fields
    for field_name, field_data in fields.items():
        if "TOTAL LOSSES" in field_name:
            val = field_data["value"].replace("$", "").replace(",", "").strip()
            try:
                result["total_incurred"] = float(val)
            except ValueError:
                pass

    return result


def _parse_acord_125_losses(raw_text: str) -> list:
    """Extract individual loss history claims from ACORD 125 raw text."""
    losses = []
    # Pattern: date (MM/DD/YYYY), line type, description, claim date, amount paid, amount reserved
    loss_section = raw_text[raw_text.find("LOSS HISTORY"):] if "LOSS HISTORY" in raw_text else ""
    if not loss_section:
        return losses

    # Find all date patterns (MM/DD/YYYY) that start a claim entry
    claim_pattern = re.findall(
        r'(\d{2}/\d{2}/\d{4})\n'   # date of occurrence
        r'(\w+)\n'                   # line (PROPERT, etc)
        r'(.+?)\n'                   # description
        r'(\d{2}/\d{2}/\d{4})\n'   # date of claim
        r'\$?([\d,]+)\n'            # amount paid
        r'\$?([\d,]+)',             # amount reserved
        loss_section
    )

    for match in claim_pattern:
        date_occur, line, desc, date_claim, paid, reserved = match
        # Convert date to YYYY-MM-DD
        parts = date_occur.split("/")
        if len(parts) == 3:
            date_iso = f"{parts[2]}-{parts[0]}-{parts[1]}"
        else:
            date_iso = date_occur

        losses.append({
            "date_of_loss": date_iso,
            "date_reported": date_claim,
            "description": desc.strip(),
            "paid_amount": int(paid.replace(",", "")),
            "reserved_amount": int(reserved.replace(",", "")),
            "total_incurred": int(paid.replace(",", "")) + int(reserved.replace(",", "")),
        })

    return losses


def _parse_acord_140(fields: dict, raw_text: str = "") -> dict:
    """Map Document AI fields to our ACORD 140 schema."""
    result = {}

    for field_name, field_data in fields.items():
        fl = field_name.lower()
        val = field_data["value"]

        if "yr built" in fl:
            match = re.search(r'(\d{4})', val)
            if match:
                result["year_built"] = int(match.group(1))

        elif "construction type" in fl:
            result["construction_type_raw"] = val
            vl = val.lower()
            if "jointed masonry" in vl or "masonry" in vl or "brick" in vl:
                result["construction_type"] = "Ordinary"
            elif "rcc" in vl or "reinforced" in vl or "non-combustible" in vl or "non combustible" in vl or "steel" in vl or "metal" in vl:
                result["construction_type"] = "Non-Combustible"
            elif "fire-resistive" in vl or "fire resistive" in vl:
                result["construction_type"] = "Fire-resistive"
            elif "heavy timber" in vl or "mill" in vl:
                result["construction_type"] = "Heavy timber"
            elif "frame" in vl or "wood" in vl:
                result["construction_type"] = "Frame"
            else:
                result["construction_type"] = val

        elif "roof type" in fl:
            result["roof_type"] = val

        elif "% sprnk" in fl:
            match = re.search(r'(\d+)', val)
            if match:
                result["sprinkler_pct"] = int(match.group(1))

        elif "guards" in fl or "watchmen" in fl:
            match = re.search(r'(\d+)', val)
            if match:
                result["security_guards"] = int(match.group(1))

        elif "burglar alarm type" in fl:
            result["burglar_alarm_type"] = val

        elif "fire alarm manufacturer" in fl:
            result["fire_alarm_manufacturer"] = val

        elif "prot cl" in fl:
            match = re.search(r'(\d+)', val)
            if match:
                result["fire_protection_class"] = int(match.group(1))

        elif "street address" in fl:
            if val and len(val) > 5:
                result["premises_address"] = val

    # Extract from raw text: stories, sum insured, total area, premises address
    if raw_text:
        # Stories and area: parse the structured section between CONSTRUCTION TYPE labels and values
        # Pattern: after construction_type value, next lines are: hydrant_dist, STORIES, fire_stat, prot_cl, basements, year, FT, area
        section_match = re.search(
            r'# STORIES # BASM.TS\nYR BUILT\nTOTAL AREA\n'
            r'[^\n]+\n'          # construction type value
            r'(\d+)\n'           # hydrant distance
            r'(\d+)\n'           # STORIES ← this is what we want
            r'[^\n]+\n'          # fire stat + district
            r'(\d+)\n'           # prot cl
            r'(\d+)\n'           # basements
            r'(\d{4})\n'         # year built
            r'[^\n]*\n'          # FT
            r'(\d+)',            # total area
            raw_text
        )
        if section_match:
            result["stories"] = int(section_match.group(2))
            result["total_area_sqft"] = int(section_match.group(6))

        # Sum insured: find all dollar amounts >= $10,000
        amounts = re.findall(r'\$(\d+(?:,\d{3})*)', raw_text)
        if amounts:
            numeric_amounts = [int(a.replace(",", "")) for a in amounts if int(a.replace(",", "")) >= 10000]
            if numeric_amounts:
                result["sum_insured"] = sum(numeric_amounts[:2])  # First two = Building + BPP

        # Premises address
        addr_match = re.search(r'STREET ADDRESS:\s*(.+?)(?:\n|$)', raw_text)
        if addr_match:
            result["premises_address"] = addr_match.group(1).strip()

    return result


def extract_acord_125(gcs_uri: str) -> dict:
    """Extract fields from ACORD 125 using Document AI."""
    logger.info(f"DocAI extracting ACORD 125: {gcs_uri}")
    bucket_name, blob_path = gcs_uri.replace("gs://", "").split("/", 1)
    bucket = gcs_client.bucket(bucket_name)
    pdf_content = bucket.blob(blob_path).download_as_bytes()

    fields, fields_list, raw_text = _extract_with_docai(pdf_content)
    logger.info(f"DocAI found {len(fields_list)} form fields")

    parsed = _parse_acord_125(fields, fields_list)

    # Parse loss history from raw text
    losses = _parse_acord_125_losses(raw_text)
    if losses:
        parsed["loss_history"] = losses
        parsed["total_claims"] = len(losses)
        if not parsed.get("total_incurred"):
            parsed["total_incurred"] = sum(l.get("total_incurred", 0) for l in losses)

    # Extract contact phone from raw text (page 2 contact section — more accurate than form field)
    contact_phone_match = re.search(r'CONTACT NAME.*?(\d{3}-\d{3}-\d{4})', raw_text, re.DOTALL)
    if contact_phone_match:
        parsed["contact_phone"] = contact_phone_match.group(1)

    parsed["_docai_field_count"] = len(fields_list)
    parsed["_source"] = "Document AI Form Parser"
    return parsed


def extract_acord_140(gcs_uri: str) -> dict:
    """Extract fields from ACORD 140 using Document AI."""
    logger.info(f"DocAI extracting ACORD 140: {gcs_uri}")
    bucket_name, blob_path = gcs_uri.replace("gs://", "").split("/", 1)
    bucket = gcs_client.bucket(bucket_name)
    pdf_content = bucket.blob(blob_path).download_as_bytes()

    fields, fields_list, raw_text = _extract_with_docai(pdf_content)
    logger.info(f"DocAI found {len(fields_list)} form fields")

    parsed = _parse_acord_140(fields, raw_text)
    parsed["_docai_field_count"] = len(fields_list)
    parsed["_source"] = "Document AI Form Parser"
    return parsed


def process_submission_v2(gcs_folder_uri: str, classifications: str) -> dict:
    """Process a submission using Document AI for ACORD forms.

    Args:
        gcs_folder_uri: GCS folder URI.
        classifications: JSON string mapping filename to type.

    Returns:
        Dict with unified extracted fields.
    """
    logger.info(f"Extraction v2: {gcs_folder_uri}")

    try:
        class_map = json.loads(classifications) if isinstance(classifications, str) else classifications
    except json.JSONDecodeError as e:
        return {"error": f"Invalid classifications JSON: {e}"}

    folder = gcs_folder_uri.rstrip("/") + "/"
    acord_125_data = {}
    acord_140_data = {}

    for filename, file_type in class_map.items():
        gcs_uri = f"gs://{BUCKET_NAME}/{folder.replace(f'gs://{BUCKET_NAME}/', '')}{filename}"
        if file_type == "ACORD_125":
            acord_125_data = extract_acord_125(gcs_uri)
        elif file_type == "ACORD_140":
            acord_140_data = extract_acord_140(gcs_uri)

    # Merge: 125 primary for applicant/policy, 140 primary for building
    effective_date = acord_125_data.get("effective_date")
    renewal_days = None
    if effective_date:
        try:
            # Handle MM/DD/YYYY format
            if "/" in effective_date:
                parts = effective_date.split("/")
                if len(parts) == 3:
                    m, d, y = parts
                    if len(y) == 2:
                        y = "20" + y
                    effective_date = f"{y}-{m}-{d}"
            renewal_days = (date.fromisoformat(effective_date) - date.today()).days
        except ValueError:
            pass

    unified = {
        "submission_id": gcs_folder_uri.rstrip("/").split("/")[-1],
        "insured_name": acord_125_data.get("insured_name"),
        "mailing_address": acord_125_data.get("mailing_address"),
        "fein": acord_125_data.get("fein"),
        "sic_code": acord_125_data.get("sic_code"),
        "naics_code": acord_125_data.get("naics_code"),
        "contact_person": acord_125_data.get("contact_person"),
        "contact_phone": acord_125_data.get("contact_phone"),
        "contact_email": acord_125_data.get("contact_email"),
        "lob": acord_125_data.get("lob"),
        "broker": acord_125_data.get("broker"),
        "proposed_carrier": acord_125_data.get("proposed_carrier") or acord_140_data.get("proposed_carrier"),
        "effective_date": effective_date,
        "expiration_date": acord_125_data.get("expiration_date"),
        "renewal_days": renewal_days,
        "sum_insured": acord_140_data.get("sum_insured"),
        "no_of_employees": acord_125_data.get("no_of_employees"),
        "year_built": acord_140_data.get("year_built"),
        "construction_type": acord_140_data.get("construction_type"),
        "construction_type_raw": acord_140_data.get("construction_type_raw"),
        "roof_type": acord_140_data.get("roof_type"),
        "stories": acord_140_data.get("stories"),
        "total_area_sqft": acord_140_data.get("total_area_sqft"),
        "sprinkler_pct": acord_140_data.get("sprinkler_pct"),
        "security_guards": acord_140_data.get("security_guards"),
        "burglar_alarm_type": acord_140_data.get("burglar_alarm_type"),
        "fire_alarm_manufacturer": acord_140_data.get("fire_alarm_manufacturer"),
        "fire_protection_class": acord_140_data.get("fire_protection_class"),
        "eq_zone": "No",
        "flood_zone": "No",
        "premises_address": acord_140_data.get("premises_address"),
        "loss_history": acord_125_data.get("loss_history"),
        "total_claims": acord_125_data.get("total_claims"),
        "total_incurred": acord_125_data.get("total_incurred"),
        "_extraction_method": "Document AI Form Parser",
    }

    # Location risk enrichment — lookup EQ/flood zone from GCS by zip code
    from extraction_agent.location_risk import enrich_location_risk
    premises_addr = unified.get("premises_address") or unified.get("mailing_address")
    if premises_addr:
        risk = enrich_location_risk(premises_addr)
        if risk.get("found"):
            unified["eq_zone"] = risk.get("eq_zone", "No")
            unified["flood_zone"] = risk.get("flood_zone", "No")
            unified["location_risk_enrichment"] = [risk]

    # Save to GCS — this happens INSIDE the agent tool, before LLM touches the response
    blob_path = gcs_folder_uri.replace(f"gs://{BUCKET_NAME}/", "").strip("/") + "/_extracted_fields.json"
    bucket = gcs_client.bucket(BUCKET_NAME)
    blob = bucket.blob(blob_path)
    blob.upload_from_string(json.dumps(unified, indent=2), content_type="application/json")
    logger.info(f"Saved extracted fields to gs://{BUCKET_NAME}/{blob_path}")

    return {"extracted_fields": unified, "saved_to_gcs": f"gs://{BUCKET_NAME}/{blob_path}"}
