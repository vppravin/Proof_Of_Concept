import os
import io
import json
import logging
import tempfile
from copy import copy

from google.cloud import storage
import openpyxl

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
BUCKET_NAME = os.getenv("BUCKET_NAME", "underwriting-workbench")
RULES_FILE = os.getenv("RULES_FILE", "Rules/UW Workbench_Business Rules.xlsx")

gcs_client = storage.Client(project=PROJECT_ID)

SHEET_MAP = {
    "priority": "Submission Priority Rules",
    "risk_score": "UW Risk Score Rules",
    "assignment": "Submission Assignment Rules",
}

VALID_RULE_TYPES = list(SHEET_MAP.keys())


def _download_workbook():
    """Download the rules Excel from GCS and return an openpyxl Workbook."""
    bucket = gcs_client.bucket(BUCKET_NAME)
    blob = bucket.blob(RULES_FILE)
    data = blob.download_as_bytes()
    return openpyxl.load_workbook(io.BytesIO(data))


def _upload_workbook(wb):
    """Upload an openpyxl Workbook back to GCS."""
    bucket = gcs_client.bucket(BUCKET_NAME)
    blob = bucket.blob(RULES_FILE)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    blob.upload_from_file(buf, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _parse_priority_rules(ws):
    """Parse the Submission Priority Rules sheet into structured JSON."""
    rules = {"lob_rules": [], "override_rules": [], "broker_rules": []}
    # Rule 1: LoB rules (rows 3-8, cols B-C)
    for row in ws.iter_rows(min_row=3, max_row=8, min_col=2, max_col=3, values_only=True):
        if row[0] and row[1]:
            rules["lob_rules"].append({"lob": str(row[0]).strip(), "priority": str(row[1]).strip()})
    # Rule 2: Renewal days (row 3, cols E-F)
    val = ws.cell(row=3, column=5).value
    pri = ws.cell(row=3, column=6).value
    if val and pri:
        rules["override_rules"].append({"condition": "renewal_days_less_than", "value": 5, "priority": str(pri).strip()})
    # Rule 3: Sum insured (row 7, cols E-F)
    val = ws.cell(row=7, column=5).value
    pri = ws.cell(row=7, column=6).value
    if val and pri:
        rules["override_rules"].append({"condition": "sum_insured_greater_than", "value": 10000000, "priority": str(pri).strip()})
    # Rule 4: Broker rules (rows 3-5, cols H-I)
    for row in ws.iter_rows(min_row=3, max_row=5, min_col=8, max_col=9, values_only=True):
        if row[0] and row[1]:
            rules["broker_rules"].append({"broker": str(row[0]).strip(), "priority": str(row[1]).strip()})
    return rules


def _parse_risk_score_rules(ws):
    """Parse the UW Risk Score Rules sheet into structured JSON."""
    rules = {"year_built": [], "eq_zone": [], "flood_zone": [], "construction_type": []}
    # Rule 1: Year built (rows 3-7, cols B-C)
    for row in ws.iter_rows(min_row=3, max_row=7, min_col=2, max_col=3, values_only=True):
        if row[0] and row[1] is not None:
            rules["year_built"].append({"range": str(row[0]).strip(), "score": str(row[1]).strip()})
    # Rule 2: EQ zone (rows 3-6, cols E-F)
    for row in ws.iter_rows(min_row=3, max_row=6, min_col=5, max_col=6, values_only=True):
        if row[0] and row[1] is not None:
            rules["eq_zone"].append({"zone": str(row[0]).strip(), "score": str(row[1]).strip()})
    # Rule 3: Flood zone (rows 3-6, cols H-I)
    for row in ws.iter_rows(min_row=3, max_row=6, min_col=8, max_col=9, values_only=True):
        if row[0] and row[1] is not None:
            rules["flood_zone"].append({"zone": str(row[0]).strip(), "score": str(row[1]).strip()})
    # Rule 4: Construction type (rows 3-6, cols K-L)
    for row in ws.iter_rows(min_row=3, max_row=6, min_col=11, max_col=12, values_only=True):
        if row[0] and row[1] is not None:
            rules["construction_type"].append({"type": str(row[0]).strip(), "score": str(row[1]).strip()})
    return rules


def _parse_assignment_rules(ws):
    """Parse the Submission Assignment Rules sheet into structured JSON."""
    rules = {"underwriters": [], "assignment_rules": []}
    # Underwriter list (rows 3-14, cols B-C)
    for row in ws.iter_rows(min_row=3, max_row=14, min_col=2, max_col=3, values_only=True):
        if row[0] and row[1]:
            rules["underwriters"].append({"lob": str(row[0]).strip(), "underwriter": str(row[1]).strip()})
    # Assignment rules (rows 3-14, cols E-F)
    for row in ws.iter_rows(min_row=3, max_row=14, min_col=5, max_col=6, values_only=True):
        if row[0] and row[1]:
            rules["assignment_rules"].append({"condition": str(row[0]).strip(), "underwriter": str(row[1]).strip()})
    return rules


PARSERS = {
    "priority": _parse_priority_rules,
    "risk_score": _parse_risk_score_rules,
    "assignment": _parse_assignment_rules,
}


# ── Tool functions ─────────────────────────────────────────────────────────

def get_rules(rule_type: str) -> dict:
    """Reads the current business rules from the Excel file in GCS.

    Fetches the rules Excel file from GCS and parses the specified rule sheet
    into structured JSON.

    Args:
        rule_type: One of 'priority', 'risk_score', or 'assignment'.

    Returns:
        Dict with the parsed rules for the specified type.
    """
    logger.info(f"Tool: get_rules for {rule_type}")
    if rule_type not in VALID_RULE_TYPES:
        return {"error": f"Invalid rule_type: {rule_type}. Must be one of {VALID_RULE_TYPES}"}
    try:
        wb = _download_workbook()
        sheet_name = SHEET_MAP[rule_type]
        ws = wb[sheet_name]
        rules = PARSERS[rule_type](ws)
        return {"rule_type": rule_type, "sheet": sheet_name, "rules": rules}
    except Exception as e:
        logger.error(f"Error reading rules: {e}")
        return {"error": str(e)}


def get_all_rules() -> dict:
    """Reads all business rules (priority, risk score, assignment) from the Excel file in GCS.

    Downloads the Excel file once and parses all three rule sheets into a single
    structured JSON response.

    Returns:
        Dict with all three rule sets: priority, risk_score, and assignment.
    """
    logger.info("Tool: get_all_rules")
    try:
        wb = _download_workbook()
        all_rules = {}
        for rule_type, sheet_name in SHEET_MAP.items():
            ws = wb[sheet_name]
            all_rules[rule_type] = PARSERS[rule_type](ws)
        return {"rules": all_rules}
    except Exception as e:
        logger.error(f"Error reading all rules: {e}")
        return {"error": str(e)}


def update_rules(rule_type: str, updated_rules_json: str) -> dict:
    """Updates business rules in the Excel file in GCS.

    Validates the new rules, downloads the current Excel, updates the relevant
    sheet, and uploads back to GCS.

    Args:
        rule_type: One of 'priority', 'risk_score', or 'assignment'.
        updated_rules_json: JSON string with the updated rules matching the schema
                           returned by get_rules.

    Returns:
        Dict with status and before/after comparison.
    """
    logger.info(f"Tool: update_rules for {rule_type}")
    if rule_type not in VALID_RULE_TYPES:
        return {"error": f"Invalid rule_type: {rule_type}. Must be one of {VALID_RULE_TYPES}"}

    try:
        new_rules = json.loads(updated_rules_json) if isinstance(updated_rules_json, str) else updated_rules_json
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}

    validation = validate_rules(rule_type, updated_rules_json)
    if not validation.get("valid", False):
        return {"error": f"Validation failed: {validation.get('reason', 'unknown')}"}

    try:
        wb = _download_workbook()
        sheet_name = SHEET_MAP[rule_type]
        ws = wb[sheet_name]

        # Get current rules for before/after
        before = PARSERS[rule_type](ws)

        # Write updated rules back to the sheet
        if rule_type == "priority":
            _write_priority_rules(ws, new_rules)
        elif rule_type == "risk_score":
            _write_risk_score_rules(ws, new_rules)
        elif rule_type == "assignment":
            _write_assignment_rules(ws, new_rules)

        _upload_workbook(wb)
        after = new_rules

        return {"status": "updated", "rule_type": rule_type, "before": before, "after": after}
    except Exception as e:
        logger.error(f"Error updating rules: {e}")
        return {"error": str(e)}


def validate_rules(rule_type: str, rules_json: str) -> dict:
    """Validates that the rules JSON matches the expected schema for the rule type.

    Args:
        rule_type: One of 'priority', 'risk_score', or 'assignment'.
        rules_json: JSON string with rules to validate.

    Returns:
        Dict with 'valid' boolean and 'reason' if invalid.
    """
    logger.info(f"Tool: validate_rules for {rule_type}")
    if rule_type not in VALID_RULE_TYPES:
        return {"valid": False, "reason": f"Invalid rule_type: {rule_type}"}

    try:
        rules = json.loads(rules_json) if isinstance(rules_json, str) else rules_json
    except json.JSONDecodeError as e:
        return {"valid": False, "reason": f"Invalid JSON: {e}"}

    if rule_type == "priority":
        required = {"lob_rules", "override_rules", "broker_rules"}
        if not required.issubset(rules.keys()):
            return {"valid": False, "reason": f"Missing keys. Required: {required}"}
        for r in rules["lob_rules"]:
            if "lob" not in r or "priority" not in r:
                return {"valid": False, "reason": "Each lob_rule must have 'lob' and 'priority'"}

    elif rule_type == "risk_score":
        required = {"year_built", "eq_zone", "flood_zone", "construction_type"}
        if not required.issubset(rules.keys()):
            return {"valid": False, "reason": f"Missing keys. Required: {required}"}

    elif rule_type == "assignment":
        required = {"underwriters", "assignment_rules"}
        if not required.issubset(rules.keys()):
            return {"valid": False, "reason": f"Missing keys. Required: {required}"}
        for r in rules["assignment_rules"]:
            if "condition" not in r or "underwriter" not in r:
                return {"valid": False, "reason": "Each assignment_rule must have 'condition' and 'underwriter'"}

    return {"valid": True, "rule_type": rule_type}


# ── Write helpers ──────────────────────────────────────────────────────────

def _write_priority_rules(ws, rules):
    """Write priority rules back to the sheet."""
    # Clear LoB rules area and rewrite
    for i, r in enumerate(rules.get("lob_rules", []), start=3):
        ws.cell(row=i, column=2, value=r["lob"])
        ws.cell(row=i, column=3, value=r["priority"])
    # Clear broker rules area and rewrite
    for i, r in enumerate(rules.get("broker_rules", []), start=3):
        ws.cell(row=i, column=8, value=r["broker"])
        ws.cell(row=i, column=9, value=r["priority"])


def _write_risk_score_rules(ws, rules):
    """Write risk score rules back to the sheet."""
    for i, r in enumerate(rules.get("year_built", []), start=3):
        ws.cell(row=i, column=2, value=r["range"])
        ws.cell(row=i, column=3, value=r["score"])
    for i, r in enumerate(rules.get("eq_zone", []), start=3):
        ws.cell(row=i, column=5, value=r["zone"])
        ws.cell(row=i, column=6, value=r["score"])
    for i, r in enumerate(rules.get("flood_zone", []), start=3):
        ws.cell(row=i, column=8, value=r["zone"])
        ws.cell(row=i, column=9, value=r["score"])
    for i, r in enumerate(rules.get("construction_type", []), start=3):
        ws.cell(row=i, column=11, value=r["type"])
        ws.cell(row=i, column=12, value=r["score"])


def _write_assignment_rules(ws, rules):
    """Write assignment rules back to the sheet."""
    for i, r in enumerate(rules.get("underwriters", []), start=3):
        ws.cell(row=i, column=2, value=r["lob"])
        ws.cell(row=i, column=3, value=r["underwriter"])
    for i, r in enumerate(rules.get("assignment_rules", []), start=3):
        ws.cell(row=i, column=5, value=r["condition"])
        ws.cell(row=i, column=6, value=r["underwriter"])
