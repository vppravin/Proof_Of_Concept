"""Extraction tools — Document AI Form Parser for ACORD forms."""

import os
import re
import json
import logging
from datetime import date

from google.cloud import storage, documentai_v1 as documentai

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
BUCKET_NAME = os.getenv("BUCKET_NAME", "underwriting-workbench")
DOCAI_PROCESSOR = os.getenv("DOCAI_PROCESSOR", "projects/146646146609/locations/us/processors/5580fe010b37636d")

gcs_client = storage.Client(project=PROJECT_ID)
docai_client = documentai.DocumentProcessorServiceClient()

# Field mappings
ACORD_125_FIELD_MAP = {
    "FEIN OR SOC SEC #": "fein",
    "SIC": "sic_code",
    "NAICS": "naics_code",
    "BUSINESS PHONE #:": "contact_phone",
    "PROPOSED EFF DATE": "effective_date",
    "PROPOSED EXP DATE": "expiration_date",
    "CARRIER": "proposed_carrier",
    "CONTACT NAME:": "contact_person",
    "PRIMARY E-MAIL ADDRESS:": "contact_email",
}


def _extract_with_docai(pdf_content: bytes) -> tuple:
    """Extract form fields using Document AI Form Parser."""
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
    """Map Document AI fields to ACORD 125 schema."""
    result = {}

    for docai_name, our_name in ACORD_125_FIELD_MAP.items():
        for field_name, field_data in fields.items():
            if docai_name.lower() in field_name.lower():
                result[our_name] = field_data["value"]
                break

    # Insured name + mailing address
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

    # Broker
    for field_name, field_data in fields.items():
        if field_name == "AGENCY" and len(field_data["value"]) > 5:
            broker_val = field_data["value"].split("\n")[0].strip()
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

    # Employees
    ft_total = pt_total = 0
    for f in fields_list:
        if "FULL TIME EMPL" in f["name"]:
            try: ft_total += int(f["value"])
            except ValueError: pass
        elif "PART TIME EMPL" in f["name"]:
            try: pt_total += int(f["value"])
            except ValueError: pass
    if ft_total or pt_total:
        result["no_of_employees"] = ft_total + pt_total

    return result


def _parse_acord_125_losses(raw_text: str) -> list:
    """Extract loss history from ACORD 125 raw text."""
    losses = []
    loss_section = raw_text[raw_text.find("LOSS HISTORY"):] if "LOSS HISTORY" in raw_text else ""
    if not loss_section:
        return losses

    claim_pattern = re.findall(
        r'(\d{2}/\d{2}/\d{4})\n(\w+)\n(.+?)\n(\d{2}/\d{2}/\d{4})\n\$?([\d,]+)\n\$?([\d,]+)',
        loss_section
    )
    for match in claim_pattern:
        date_occur, line, desc, date_claim, paid, reserved = match
        parts = date_occur.split("/")
        date_iso = f"{parts[2]}-{parts[0]}-{parts[1]}" if len(parts) == 3 else date_occur
        losses.append({
            "date_of_loss": date_iso, "date_reported": date_claim, "description": desc.strip(),
            "paid_amount": int(paid.replace(",", "")), "reserved_amount": int(reserved.replace(",", "")),
            "total_incurred": int(paid.replace(",", "")) + int(reserved.replace(",", "")),
        })
    return losses


def _parse_acord_140(fields: dict, raw_text: str = "") -> dict:
    """Map Document AI fields to ACORD 140 schema."""
    result = {}

    for field_name, field_data in fields.items():
        fl = field_name.lower()
        val = field_data["value"]

        if "yr built" in fl:
            match = re.search(r'(\d{4})', val)
            if match: result["year_built"] = int(match.group(1))
        elif "construction type" in fl:
            vl = val.lower()
            if "masonry" in vl or "brick" in vl: result["construction_type"] = "Ordinary"
            elif "rcc" in vl or "reinforced" in vl or "non-combustible" in vl or "steel" in vl or "metal" in vl: result["construction_type"] = "Non-Combustible"
            elif "fire-resistive" in vl or "fire resistive" in vl: result["construction_type"] = "Fire-resistive"
            elif "frame" in vl or "wood" in vl: result["construction_type"] = "Frame"
            else: result["construction_type"] = val
        elif "roof type" in fl: result["roof_type"] = val
        elif "% sprnk" in fl:
            match = re.search(r'(\d+)', val)
            if match: result["sprinkler_pct"] = int(match.group(1))
        elif "guards" in fl or "watchmen" in fl:
            match = re.search(r'(\d+)', val)
            if match: result["security_guards"] = int(match.group(1))
        elif "burglar alarm type" in fl: result["burglar_alarm_type"] = val
        elif "fire alarm manufacturer" in fl: result["fire_alarm_manufacturer"] = val
        elif "prot cl" in fl:
            match = re.search(r'(\d+)', val)
            if match: result["fire_protection_class"] = int(match.group(1))
        elif "street address" in fl and val and len(val) > 5:
            result["premises_address"] = val

    if raw_text:
        # Stories and area
        section_match = re.search(
            r'# STORIES # BASM.TS\nYR BUILT\nTOTAL AREA\n[^\n]+\n(\d+)\n(\d+)\n[^\n]+\n(\d+)\n(\d+)\n(\d{4})\n[^\n]*\n(\d+)',
            raw_text
        )
        if section_match:
            result["stories"] = int(section_match.group(2))
            result["total_area_sqft"] = int(section_match.group(6))

        # Sum insured
        amounts = re.findall(r'\$(\d+(?:,\d{3})*)', raw_text)
        if amounts:
            numeric_amounts = [int(a.replace(",", "")) for a in amounts if int(a.replace(",", "")) >= 10000]
            if numeric_amounts:
                result["sum_insured"] = sum(numeric_amounts[:2])

    return result


def extract_acord_125(gcs_uri: str) -> dict:
    """Extracts fields from an ACORD 125 PDF using Document AI Form Parser.

    Args:
        gcs_uri: GCS URI of the ACORD 125 PDF file.

    Returns:
        Dict with extracted fields: insured_name, mailing_address, fein, sic_code, lob, broker, etc.
    """
    logger.info(f"Tool: extract_acord_125 for {gcs_uri}")
    try:
        bucket_name, blob_path = gcs_uri.replace("gs://", "").split("/", 1)
        pdf_content = gcs_client.bucket(bucket_name).blob(blob_path).download_as_bytes()

        fields, fields_list, raw_text = _extract_with_docai(pdf_content)
        parsed = _parse_acord_125(fields, fields_list)

        losses = _parse_acord_125_losses(raw_text)
        if losses:
            parsed["loss_history"] = losses
            parsed["total_claims"] = len(losses)
            if not parsed.get("total_incurred"):
                parsed["total_incurred"] = sum(l.get("total_incurred", 0) for l in losses)

        parsed["_source"] = "Document AI Form Parser"
        return parsed
    except Exception as e:
        return {"error": str(e)}


def extract_acord_140(gcs_uri: str) -> dict:
    """Extracts fields from an ACORD 140 PDF using Document AI Form Parser.

    Args:
        gcs_uri: GCS URI of the ACORD 140 PDF file.

    Returns:
        Dict with extracted fields: year_built, construction_type, roof_type, sum_insured, etc.
    """
    logger.info(f"Tool: extract_acord_140 for {gcs_uri}")
    try:
        bucket_name, blob_path = gcs_uri.replace("gs://", "").split("/", 1)
        pdf_content = gcs_client.bucket(bucket_name).blob(blob_path).download_as_bytes()

        fields, fields_list, raw_text = _extract_with_docai(pdf_content)
        parsed = _parse_acord_140(fields, raw_text)
        parsed["_source"] = "Document AI Form Parser"
        return parsed
    except Exception as e:
        return {"error": str(e)}


def save_extracted_fields(gcs_folder_uri: str, extracted_fields_json: str) -> dict:
    """Saves merged extracted fields JSON to GCS for downstream processing.

    Args:
        gcs_folder_uri: GCS folder URI e.g. gs://underwriting-workbench/Input_Files/Sample 1/
        extracted_fields_json: JSON string with all merged extracted fields.

    Returns:
        Dict with confirmation and GCS path.
    """
    logger.info(f"Tool: save_extracted_fields for {gcs_folder_uri}")
    try:
        data = json.loads(extracted_fields_json) if isinstance(extracted_fields_json, str) else extracted_fields_json
        blob_path = gcs_folder_uri.replace(f"gs://{BUCKET_NAME}/", "").strip("/") + "/_extracted_fields.json"
        bucket = gcs_client.bucket(BUCKET_NAME)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(json.dumps(data, indent=2), content_type="application/json")
        return {"saved": True, "gcs_path": f"gs://{BUCKET_NAME}/{blob_path}"}
    except Exception as e:
        return {"error": str(e)}


def save_classification_results(gcs_folder_uri: str, classifications_json: str) -> dict:
    """Saves classification results to GCS so they are available for the UI.

    Call this after classifying all documents in a submission folder.

    Args:
        gcs_folder_uri: GCS folder URI.
        classifications_json: JSON string with array of classification results.
            Each item should have: filename, classified_as, confidence, reason.

    Returns:
        Dict with confirmation.
    """
    logger.info(f"Tool: save_classification_results for {gcs_folder_uri}")
    try:
        data = json.loads(classifications_json) if isinstance(classifications_json, str) else classifications_json
        blob_path = gcs_folder_uri.replace(f"gs://{BUCKET_NAME}/", "").strip("/") + "/_classification_results.json"
        bucket = gcs_client.bucket(BUCKET_NAME)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(json.dumps(data, indent=2), content_type="application/json")
        return {"saved": True, "gcs_path": f"gs://{BUCKET_NAME}/{blob_path}"}
    except Exception as e:
        return {"error": str(e)}
