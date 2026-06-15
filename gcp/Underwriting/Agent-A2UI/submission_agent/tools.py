"""Submission Record Agent — persists underwriting submissions to BigQuery."""

import os
import re
import json
import logging
from datetime import datetime, timezone

from google.cloud import bigquery, storage
import openpyxl
import io

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
DATASET_ID = os.getenv("BQ_DATASET", "underwriting_workbench")
TABLE_ID = f"{PROJECT_ID}.{DATASET_ID}.submissions"
BUCKET_NAME = os.getenv("BUCKET_NAME", "underwriting-workbench")
RULES_FILE = os.getenv("RULES_FILE", "Rules/UW Workbench_Business Rules.xlsx")

bq_client = bigquery.Client(project=PROJECT_ID)


def _generate_case_id() -> str:
    """Generate next Case ID in NB-YY-NNNNN format by querying max existing ID."""
    year = datetime.now(timezone.utc).strftime("%y")
    prefix = f"NB-{year}-"
    query = f"SELECT MAX(case_id) as max_id FROM `{TABLE_ID}` WHERE case_id LIKE '{prefix}%'"
    try:
        result = list(bq_client.query(query).result())
        max_id = result[0].max_id if result and result[0].max_id else None
        if max_id:
            seq = int(max_id.split("-")[-1]) + 1
        else:
            seq = 34677  # Start from the sample data sequence
        return f"{prefix}{seq:05d}"
    except Exception:
        return f"{prefix}{int(datetime.now(timezone.utc).timestamp()) % 100000:05d}"


def create_submission(extracted_fields_json: str, uw_result_json: str, gcs_folder: str = "") -> dict:
    """Creates a new submission record in BigQuery after UW rules evaluation.

    Auto-generates a Case ID and saves all extracted data + evaluation results.
    Initial status is set to 'Assigned'.

    Args:
        extracted_fields_json: JSON string with extracted submission fields.
        uw_result_json: JSON string with UW rules evaluation result (priority, risk score, assignment).
        gcs_folder: GCS folder URI where the submission documents are stored.

    Returns:
        Dict with case_id, status, and assigned_to.
    """
    logger.info("Tool: create_submission")

    try:
        fields = json.loads(extracted_fields_json) if isinstance(extracted_fields_json, str) else extracted_fields_json
        uw = json.loads(uw_result_json) if isinstance(uw_result_json, str) else uw_result_json
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}

    case_id = _generate_case_id()
    now = datetime.now(timezone.utc).isoformat()

    status = "Declined" if uw.get("auto_decline") else "Assigned"

    def _to_int(val):
        if val is None:
            return None
        try:
            return int(float(str(val).strip()))
        except (ValueError, TypeError):
            return None

    def _to_float(val):
        if val is None:
            return None
        try:
            return float(str(val).strip().replace(",", ""))
        except (ValueError, TypeError):
            return None

    row = {
        "case_id": case_id,
        "created_on": now,
        "updated_on": now,
        "insured_name": fields.get("insured_name"),
        "mailing_address": fields.get("mailing_address"),
        "fein": fields.get("fein"),
        "sic_code": fields.get("sic_code"),
        "lob": fields.get("lob"),
        "effective_date": fields.get("effective_date"),
        "expiration_date": fields.get("expiration_date"),
        "renewal_days": _to_int(fields.get("renewal_days")),
        "broker": fields.get("broker"),
        "proposed_carrier": fields.get("proposed_carrier"),
        "sum_insured": _to_float(fields.get("sum_insured")),
        "no_of_employees": _to_int(fields.get("no_of_employees")),
        "year_built": _to_int(fields.get("year_built")),
        "construction_type": fields.get("construction_type"),
        "eq_zone": fields.get("eq_zone"),
        "flood_zone": fields.get("flood_zone"),
        "risk_score": _to_int(uw.get("risk_score")),
        "risk_level": uw.get("risk_level"),
        "priority": uw.get("priority"),
        "override_reasons": json.dumps(uw.get("override_reasons", [])),
        "assigned_to": uw.get("assigned_to"),
        "status": status,
        "auto_decline": bool(uw.get("auto_decline", False)),
        "decline_reason": uw.get("decline_reason"),
        "extracted_json": json.dumps(fields),
        "uw_result_json": json.dumps(uw),
        "gcs_folder": gcs_folder,
    }

    try:
        # Use INSERT DML instead of streaming insert so row is immediately updatable
        columns = ", ".join(row.keys())
        values_params = []
        query_params = []
        for k, v in row.items():
            param_name = f"p_{k}"
            values_params.append(f"@{param_name}")
            # Determine BigQuery type based on column name
            float_cols = {"sum_insured"}
            int_cols = {"renewal_days", "no_of_employees", "year_built", "risk_score", "retry_count"}
            bool_cols = {"auto_decline"}

            if k in float_cols:
                query_params.append(bigquery.ScalarQueryParameter(param_name, "FLOAT64", float(v) if v is not None else None))
            elif k in int_cols:
                query_params.append(bigquery.ScalarQueryParameter(param_name, "INT64", int(v) if v is not None else None))
            elif k in bool_cols:
                query_params.append(bigquery.ScalarQueryParameter(param_name, "BOOL", bool(v) if v is not None else None))
            else:
                query_params.append(bigquery.ScalarQueryParameter(param_name, "STRING", str(v) if v is not None else None))

        query = f"INSERT INTO `{TABLE_ID}` ({columns}) VALUES ({', '.join(values_params)})"
        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        bq_client.query(query, job_config=job_config).result()

        logger.info(f"Submission created: {case_id}, status={status}, assigned={uw.get('assigned_to')}")
        return {
            "case_id": case_id,
            "status": status,
            "assigned_to": uw.get("assigned_to"),
            "created_on": now,
        }
    except Exception as e:
        logger.error(f"Error creating submission: {e}")
        return {"error": str(e)}


def update_submission_decision(case_id: str, decision: str, decision_by: str = "Underwriter") -> dict:
    """Records the underwriter's accept or decline decision on a submission.

    Updates the status to 'Complete' (accept) or 'Declined' (decline).

    Args:
        case_id: The submission Case ID e.g. NB-26-34677
        decision: Either 'accept' or 'decline'
        decision_by: Name of the underwriter making the decision.

    Returns:
        Dict with updated case_id, status, and decision timestamp.
    """
    logger.info(f"Tool: update_submission_decision for {case_id} -> {decision}")

    decision = decision.strip().lower()
    if decision not in ("accept", "decline"):
        return {"error": "Decision must be 'accept' or 'decline'"}

    new_status = "Complete" if decision == "accept" else "Declined"
    now = datetime.now(timezone.utc).isoformat()

    query = f"""
        UPDATE `{TABLE_ID}`
        SET status = @status, decision = @decision, decision_by = @decision_by,
            decision_at = @decision_at, updated_on = @updated_on
        WHERE case_id = @case_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("status", "STRING", new_status),
            bigquery.ScalarQueryParameter("decision", "STRING", decision),
            bigquery.ScalarQueryParameter("decision_by", "STRING", decision_by),
            bigquery.ScalarQueryParameter("decision_at", "TIMESTAMP", now),
            bigquery.ScalarQueryParameter("updated_on", "TIMESTAMP", now),
            bigquery.ScalarQueryParameter("case_id", "STRING", case_id),
        ]
    )

    try:
        result = bq_client.query(query, job_config=job_config).result()
        logger.info(f"Decision recorded: {case_id} -> {decision} by {decision_by}")
        return {"case_id": case_id, "status": new_status, "decision": decision, "decision_by": decision_by, "decision_at": now}
    except Exception as e:
        logger.error(f"Error updating decision: {e}")
        return {"error": str(e)}


def get_submission(case_id: str) -> dict:
    """Retrieves a submission record by Case ID.

    Args:
        case_id: The submission Case ID e.g. NB-26-34677

    Returns:
        Dict with all submission fields, or not_found.
    """
    logger.info(f"Tool: get_submission for {case_id}")
    query = f"SELECT * FROM `{TABLE_ID}` WHERE case_id = @case_id"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("case_id", "STRING", case_id)]
    )
    try:
        rows = list(bq_client.query(query, job_config=job_config).result())
        if not rows:
            return {"status": "not_found", "case_id": case_id}
        row = dict(rows[0])
        for k, v in row.items():
            if hasattr(v, 'isoformat'):
                row[k] = v.isoformat()
        return row
    except Exception as e:
        return {"error": str(e)}


EDITABLE_FIELDS = {
    "insured_name", "mailing_address", "fein", "sic_code", "lob",
    "effective_date", "expiration_date", "renewal_days", "broker", "proposed_carrier",
    "sum_insured", "no_of_employees", "year_built", "construction_type",
    "eq_zone", "flood_zone", "risk_score", "risk_level", "priority",
    "override_reasons", "assigned_to", "status", "auto_decline", "decline_reason",
    "extracted_json", "uw_result_json",
}


def update_submission(case_id: str, updates_json: str) -> dict:
    """Updates specific fields on an existing submission record.

    Allows the underwriter to correct extracted data before making a decision.

    Args:
        case_id: The Case ID e.g. NB-26-34677
        updates_json: JSON string with fields to update e.g. '{"fein": "58-1234567", "sic_code": "5812"}'

    Returns:
        Dict with case_id and list of updated fields.
    """
    logger.info(f"Tool: update_submission for {case_id}")

    try:
        updates = json.loads(updates_json) if isinstance(updates_json, str) else updates_json
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}

    invalid = set(updates.keys()) - EDITABLE_FIELDS
    if invalid:
        return {"error": f"Cannot edit fields: {invalid}. Editable: {EDITABLE_FIELDS}"}

    if not updates:
        return {"error": "No fields to update"}

    set_clauses = []
    params = [bigquery.ScalarQueryParameter("case_id", "STRING", case_id),
              bigquery.ScalarQueryParameter("updated_on", "TIMESTAMP", datetime.now(timezone.utc).isoformat())]

    for field, value in updates.items():
        param_name = f"f_{field}"
        set_clauses.append(f"{field} = @{param_name}")
        if field in ("sum_insured",):
            params.append(bigquery.ScalarQueryParameter(param_name, "FLOAT64", float(value) if value is not None else None))
        elif field in ("no_of_employees", "year_built", "risk_score", "renewal_days"):
            params.append(bigquery.ScalarQueryParameter(param_name, "INT64", int(value) if value is not None else None))
        elif field in ("auto_decline",):
            params.append(bigquery.ScalarQueryParameter(param_name, "BOOL", bool(value) if value is not None else None))
        else:
            params.append(bigquery.ScalarQueryParameter(param_name, "STRING", str(value) if value is not None else None))

    set_clauses.append("updated_on = @updated_on")
    query = f"UPDATE `{TABLE_ID}` SET {', '.join(set_clauses)} WHERE case_id = @case_id"

    try:
        bq_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
        logger.info(f"Updated {case_id}: {list(updates.keys())}")
        return {"case_id": case_id, "updated_fields": list(updates.keys()), "status": "updated"}
    except Exception as e:
        logger.error(f"Error updating submission: {e}")
        return {"error": str(e)}


def list_submissions(status: str = "", assigned_to: str = "", limit: int = 20) -> dict:
    """Lists submission records with optional filters.

    Args:
        status: Filter by status (Assigned, In-Progress, Hold, Declined, Complete). Empty for all.
        assigned_to: Filter by underwriter name. Empty for all.
        limit: Max records to return (default 20).

    Returns:
        Dict with list of submissions.
    """
    logger.info(f"Tool: list_submissions (status={status}, assigned_to={assigned_to})")

    conditions = []
    params = []
    if status:
        conditions.append("status = @status")
        params.append(bigquery.ScalarQueryParameter("status", "STRING", status))
    if assigned_to:
        conditions.append("assigned_to = @assigned_to")
        params.append(bigquery.ScalarQueryParameter("assigned_to", "STRING", assigned_to))

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT case_id, created_on, insured_name, lob, effective_date, broker, priority, risk_score, risk_level, assigned_to, status, decision FROM `{TABLE_ID}` {where} ORDER BY created_on DESC LIMIT {limit}"

    job_config = bigquery.QueryJobConfig(query_parameters=params)
    try:
        rows = list(bq_client.query(query, job_config=job_config).result())
        submissions = []
        for row in rows:
            r = dict(row)
            for k, v in r.items():
                if hasattr(v, 'isoformat'):
                    r[k] = v.isoformat()
            submissions.append(r)
        return {"count": len(submissions), "submissions": submissions}
    except Exception as e:
        return {"error": str(e)}


# ── Justification Tool ─────────────────────────────────────────────────────

def _load_rules_from_gcs() -> dict:
    """Load and parse business rules from Excel in GCS."""
    gcs = storage.Client(project=PROJECT_ID)
    bucket = gcs.bucket(BUCKET_NAME)
    blob = bucket.blob(RULES_FILE)
    wb = openpyxl.load_workbook(io.BytesIO(blob.download_as_bytes()))

    # Parse priority rules
    ws = wb["Submission Priority Rules"]
    lob_rules = []
    for row in ws.iter_rows(min_row=3, max_row=8, min_col=2, max_col=3, values_only=True):
        if row[0] and row[1]:
            lob_rules.append({"lob": str(row[0]).strip(), "priority": str(row[1]).strip()})
    override_rules = []
    val = ws.cell(row=3, column=5).value
    if val:
        override_rules.append({"condition": "renewal_days_less_than", "value": 5, "priority": "P0", "label": "Renewal days < 5"})
    val = ws.cell(row=7, column=5).value
    if val:
        override_rules.append({"condition": "sum_insured_greater_than", "value": 10000000, "priority": "P0", "label": "Sum insured > $10M"})
    broker_rules = []
    for row in ws.iter_rows(min_row=3, max_row=5, min_col=8, max_col=9, values_only=True):
        if row[0] and row[1]:
            broker_rules.append({"broker": str(row[0]).strip(), "priority": str(row[1]).strip()})

    # Parse risk score rules
    ws2 = wb["UW Risk Score Rules"]
    year_rules = []
    for row in ws2.iter_rows(min_row=3, max_row=7, min_col=2, max_col=3, values_only=True):
        if row[0] and row[1] is not None:
            year_rules.append({"range": str(row[0]).strip(), "score": str(row[1]).strip()})
    eq_rules = []
    for row in ws2.iter_rows(min_row=3, max_row=6, min_col=5, max_col=6, values_only=True):
        if row[0] and row[1] is not None:
            eq_rules.append({"zone": str(row[0]).strip(), "score": str(row[1]).strip()})
    flood_rules = []
    for row in ws2.iter_rows(min_row=3, max_row=6, min_col=8, max_col=9, values_only=True):
        if row[0] and row[1] is not None:
            flood_rules.append({"zone": str(row[0]).strip(), "score": str(row[1]).strip()})
    construction_rules = []
    for row in ws2.iter_rows(min_row=3, max_row=6, min_col=11, max_col=12, values_only=True):
        if row[0] and row[1] is not None:
            construction_rules.append({"type": str(row[0]).strip(), "score": str(row[1]).strip()})

    # Parse assignment rules
    ws3 = wb["Submission Assignment Rules"]
    assignment_rules = []
    for row in ws3.iter_rows(min_row=3, max_row=14, min_col=5, max_col=6, values_only=True):
        if row[0] and row[1]:
            assignment_rules.append({"condition": str(row[0]).strip(), "underwriter": str(row[1]).strip()})

    return {
        "lob_rules": lob_rules,
        "override_rules": override_rules,
        "broker_rules": broker_rules,
        "year_rules": year_rules,
        "eq_rules": eq_rules,
        "flood_rules": flood_rules,
        "construction_rules": construction_rules,
        "assignment_rules": assignment_rules,
    }


def _normalize(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'[^a-z0-9\s]', '', text.lower().strip())


def justify_submission(case_id: str) -> dict:
    """Generates a deterministic justification for every decision made on a submission.

    Re-runs the exact same business rules against the stored extracted data
    and traces each step to explain WHY each decision was made.

    Args:
        case_id: The Case ID e.g. NB-26-34705

    Returns:
        Dict with detailed justification for priority, risk score, assignment, and auto-decline.
    """
    logger.info(f"Tool: justify_submission for {case_id}")

    # 1. Get submission from BigQuery
    query = f"SELECT * FROM `{TABLE_ID}` WHERE case_id = @case_id"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("case_id", "STRING", case_id)]
    )
    rows = list(bq_client.query(query, job_config=job_config).result())
    if not rows:
        return {"error": f"Submission {case_id} not found"}

    row = dict(rows[0])
    extracted = json.loads(row.get("extracted_json", "{}"))

    # 2. Load current business rules from GCS
    rules = _load_rules_from_gcs()

    # 3. Trace priority decision
    lob = extracted.get("lob", "")
    broker = extracted.get("broker", "")
    sum_insured = extracted.get("sum_insured")
    renewal_days = extracted.get("renewal_days")

    priority_trace = {"base_rule": None, "overrides_evaluated": [], "final_priority": row.get("priority")}

    # Base LoB match
    matched_lob = False
    for rule in rules["lob_rules"]:
        n_lob = _normalize(lob)
        n_rule = _normalize(rule["lob"])
        if n_rule in n_lob or n_lob in n_rule:
            priority_trace["base_rule"] = f"LoB '{lob}' matched rule '{rule['lob']}' → {rule['priority']}"
            matched_lob = True
            break
    if not matched_lob:
        for rule in rules["lob_rules"]:
            if "rest" in rule["lob"].lower():
                priority_trace["base_rule"] = f"LoB '{lob}' did not match any specific rule, using '{rule['lob']}' → {rule['priority']}"
                break

    # Override: renewal days
    if renewal_days is not None:
        triggered = 0 < renewal_days < 5
        priority_trace["overrides_evaluated"].append({
            "rule": "Renewal days < 5",
            "value": renewal_days,
            "triggered": triggered,
            "reason": f"Renewal days {renewal_days} {'is between 0-5 → P0' if triggered else 'is not between 0 and 5 — not triggered'}"
        })

    # Override: sum insured
    if sum_insured is not None:
        triggered = sum_insured > 10000000
        priority_trace["overrides_evaluated"].append({
            "rule": "Sum insured > $10M",
            "value": sum_insured,
            "triggered": triggered,
            "reason": f"${sum_insured:,.0f} {'> $10,000,000 → P0' if triggered else 'is not greater than $10,000,000 — not triggered'}"
        })

    # Override: broker
    broker_matched = False
    for rule in rules["broker_rules"]:
        n_broker = _normalize(broker)
        n_rule_broker = _normalize(rule["broker"])
        if n_rule_broker in n_broker or n_broker in n_rule_broker:
            priority_trace["overrides_evaluated"].append({
                "rule": f"Broker in priority list",
                "value": broker,
                "triggered": True,
                "reason": f"'{broker}' matched '{rule['broker']}' → {rule['priority']}"
            })
            broker_matched = True
            break
    if not broker_matched:
        priority_trace["overrides_evaluated"].append({
            "rule": "Broker in priority list",
            "value": broker,
            "triggered": False,
            "reason": f"'{broker}' did not match any priority broker ({', '.join(r['broker'] for r in rules['broker_rules'])})"
        })

    # 4. Trace risk score
    year_built = extracted.get("year_built")
    eq_zone = extracted.get("eq_zone", "No")
    flood_zone = extracted.get("flood_zone", "No")
    construction = extracted.get("construction_type", "")

    risk_trace = {"factors": [], "total_score": 0, "risk_level": ""}

    # Year built
    yb_score = 0
    yb_reason = "No year built data"
    yb_decline = False
    if year_built:
        for rule in rules["year_rules"]:
            range_text = rule["range"].lower()
            score = rule["score"]
            if "after" in range_text:
                threshold = int(re.search(r'\d{4}', range_text).group())
                if year_built > threshold:
                    yb_score = 0 if score == "Decline" else int(score)
                    yb_reason = f"{year_built} > {threshold} → matched '{rule['range']}' → Score {score}"
                    yb_decline = score == "Decline"
                    break
            elif "before" in range_text:
                threshold = int(re.search(r'\d{4}', range_text).group())
                if year_built < threshold:
                    yb_score = 0
                    yb_reason = f"{year_built} < {threshold} → matched '{rule['range']}' → DECLINE"
                    yb_decline = True
                    break
            elif "between" in range_text or "-" in range_text:
                years = re.findall(r'\d{4}', range_text)
                if len(years) == 2 and int(years[0]) <= year_built <= int(years[1]):
                    yb_score = int(score)
                    yb_reason = f"{year_built} is between {years[0]}-{years[1]} → matched '{rule['range']}' → Score {score}"
                    break

    risk_trace["factors"].append({"factor": "Year Built", "value": year_built, "score": yb_score, "reason": yb_reason})

    # EQ zone
    eq_score = 0
    eq_reason = f"'{eq_zone}' — no matching rule, defaulting to 0"
    for rule in rules["eq_rules"]:
        if _normalize(eq_zone) == _normalize(rule["zone"]):
            eq_score = int(rule["score"])
            eq_reason = f"'{eq_zone}' matched '{rule['zone']}' → Score {rule['score']}"
            break
    risk_trace["factors"].append({"factor": "EQ Zone", "value": eq_zone, "score": eq_score, "reason": eq_reason})

    # Flood zone
    fl_score = 0
    fl_reason = f"'{flood_zone}' — no matching rule, defaulting to 0"
    for rule in rules["flood_rules"]:
        if _normalize(flood_zone) == _normalize(rule["zone"]):
            fl_score = int(rule["score"])
            fl_reason = f"'{flood_zone}' matched '{rule['zone']}' → Score {rule['score']}"
            break
    risk_trace["factors"].append({"factor": "Flood Zone", "value": flood_zone, "score": fl_score, "reason": fl_reason})

    # Construction
    ct_score = 0
    ct_reason = f"'{construction}' — no matching rule, defaulting to 0"
    for rule in rules["construction_rules"]:
        if _normalize(construction) == _normalize(rule["type"]):
            ct_score = int(rule["score"])
            ct_reason = f"'{construction}' matched '{rule['type']}' → Score {rule['score']}"
            break
    risk_trace["factors"].append({"factor": "Construction Type", "value": construction, "score": ct_score, "reason": ct_reason})

    total = yb_score + eq_score + fl_score + ct_score
    risk_trace["total_score"] = total
    risk_trace["calculation"] = f"{yb_score} + {eq_score} + {fl_score} + {ct_score} = {total}"
    risk_trace["risk_level"] = "Low Risk (≤3)" if total <= 3 else "Medium Risk (≤6)" if total <= 6 else "High Risk (≤9)" if total <= 9 else "Very High Risk (>9)"

    # 5. Trace assignment
    assigned = row.get("assigned_to")
    assignment_trace = {"assigned_to": assigned, "rule_matched": None, "other_options": []}
    priority = row.get("priority", "")
    for rule in rules["assignment_rules"]:
        parts = rule["condition"].split(" - ", 1)
        if len(parts) == 2:
            pri_part = parts[0].strip()
            lob_part = parts[1].strip()
            is_rest = "rest" in lob_part.lower()
            lob_match = _normalize(lob_part) in _normalize(lob) or _normalize(lob) in _normalize(lob_part)
            if lob_match and not is_rest:
                if pri_part == priority:
                    assignment_trace["rule_matched"] = f"'{rule['condition']}' → {rule['underwriter']}"
                elif "to" in pri_part:
                    assignment_trace["other_options"].append(f"If {pri_part}: {rule['underwriter']}")
                else:
                    assignment_trace["other_options"].append(f"If {pri_part}: {rule['underwriter']}")
    # Fallback to Rest of LoB if no specific match
    if not assignment_trace["rule_matched"]:
        for rule in rules["assignment_rules"]:
            parts = rule["condition"].split(" - ", 1)
            if len(parts) == 2 and "rest" in parts[1].lower():
                if parts[0].strip() == priority:
                    assignment_trace["rule_matched"] = f"'{rule['condition']}' → {rule['underwriter']} (fallback — no specific LoB rule)"

    # 6. Trace auto-decline
    decline_trace = {"declined": row.get("auto_decline", False), "checks": []}
    is_marine = "marine" in _normalize(lob)
    decline_trace["checks"].append({
        "rule": "Marine LoB → Decline",
        "triggered": is_marine,
        "reason": f"LoB is '{lob}'" + (" → DECLINE" if is_marine else " — not Marine")
    })
    decline_trace["checks"].append({
        "rule": "Year Built before 1970 → Decline",
        "triggered": yb_decline,
        "reason": f"Year built {year_built}" + (" → DECLINE" if yb_decline else " — not before 1970")
    })

    return {
        "case_id": case_id,
        "insured_name": extracted.get("insured_name"),
        "priority_justification": priority_trace,
        "risk_score_justification": risk_trace,
        "assignment_justification": assignment_trace,
        "auto_decline_justification": decline_trace,
    }


# ── Smart Prioritization & Workload Tools ──────────────────────────────────

def get_prioritized_workload(assigned_to: str = "") -> dict:
    """Gets submissions sorted by smart priority score for an underwriter.

    Ranking algorithm:
    1. Priority level (P0=100, P1=80, P2=60, P3=40, P4=20)
    2. Effective date urgency (closer deadline = higher score, max +50)
    3. Risk score (higher risk = higher urgency, max +12)
    4. Client history (existing client = +10 bonus)
    5. Sum insured (higher value = higher priority, max +10)

    Only shows Assigned/Pending submissions (not Complete/Declined).

    Args:
        assigned_to: Underwriter name. Empty for all underwriters.

    Returns:
        Dict with ranked submissions and workload summary.
    """
    logger.info(f"Tool: get_prioritized_workload for '{assigned_to}'")

    conditions = ["status IN ('Assigned')"]
    params = []
    if assigned_to:
        conditions.append("assigned_to = @assigned_to")
        params.append(bigquery.ScalarQueryParameter("assigned_to", "STRING", assigned_to))

    where = f"WHERE {' AND '.join(conditions)}"
    query = f"SELECT * FROM `{TABLE_ID}` {where} ORDER BY created_on DESC"
    job_config = bigquery.QueryJobConfig(query_parameters=params)

    rows = list(bq_client.query(query, job_config=job_config).result())

    priority_scores = {"P0": 100, "P1": 80, "P2": 60, "P3": 40, "P4": 20}

    ranked = []
    for row in rows:
        r = dict(row)
        score = 0

        # 1. Priority level
        score += priority_scores.get(r.get("priority", ""), 0)

        # 2. Effective date urgency
        eff = r.get("effective_date")
        if eff:
            try:
                from datetime import date
                if isinstance(eff, str):
                    eff_date = date.fromisoformat(eff) if "-" in eff else None
                else:
                    eff_date = eff
                if eff_date:
                    days_left = (eff_date - date.today()).days
                    if days_left < 0:
                        urgency = 50  # Already past — most urgent
                    elif days_left <= 3:
                        urgency = 45
                    elif days_left <= 10:
                        urgency = 30
                    elif days_left <= 30:
                        urgency = 15
                    else:
                        urgency = 0
                    score += urgency
                    r["days_to_effective"] = days_left
                    r["rag_status"] = "Red" if days_left < 3 else "Amber" if days_left < 10 else "Green"
            except (ValueError, TypeError):
                pass

        # 3. Risk score
        rs = r.get("risk_score")
        if rs and isinstance(rs, (int, float)):
            score += min(int(rs), 12)

        # 4. Sum insured (higher = more important)
        si = r.get("sum_insured")
        if si and isinstance(si, (int, float)):
            if si > 5000000:
                score += 10
            elif si > 1000000:
                score += 7
            elif si > 500000:
                score += 5
            else:
                score += 2

        r["urgency_score"] = score
        r["review_status"] = r.get("review_status") or "Pending"

        # Clean datetime fields
        for k, v in r.items():
            if hasattr(v, 'isoformat'):
                r[k] = v.isoformat()

        ranked.append(r)

    # Sort by urgency score descending
    ranked.sort(key=lambda x: x.get("urgency_score", 0), reverse=True)

    # Add rank
    for i, r in enumerate(ranked):
        r["rank"] = i + 1

    # Summary
    summary = {
        "total_pending": len(ranked),
        "p0_count": sum(1 for r in ranked if r.get("priority") == "P0"),
        "p1_count": sum(1 for r in ranked if r.get("priority") == "P1"),
        "high_risk_count": sum(1 for r in ranked if (r.get("risk_score") or 0) > 6),
        "urgent_count": sum(1 for r in ranked if r.get("rag_status") == "Red"),
    }

    return {
        "assigned_to": assigned_to or "All",
        "summary": summary,
        "submissions": [
            {
                "rank": r["rank"],
                "case_id": r.get("case_id"),
                "insured_name": r.get("insured_name"),
                "priority": r.get("priority"),
                "risk_score": r.get("risk_score"),
                "sum_insured": r.get("sum_insured"),
                "effective_date": r.get("effective_date"),
                "days_to_effective": r.get("days_to_effective"),
                "rag_status": r.get("rag_status"),
                "broker": r.get("broker"),
                "urgency_score": r.get("urgency_score"),
                "review_status": r.get("review_status"),
            }
            for r in ranked
        ],
        "recommendation": f"Start with {ranked[0]['case_id']} ({ranked[0]['insured_name']}) — highest urgency score ({ranked[0]['urgency_score']})" if ranked else "No pending submissions"
    }


def update_review_status(case_id: str, review_status: str) -> dict:
    """Updates the review status of a submission.

    Args:
        case_id: The Case ID.
        review_status: One of 'Pending', 'In Review', 'Reviewed', 'Complete'.

    Returns:
        Dict with updated status.
    """
    logger.info(f"Tool: update_review_status {case_id} → {review_status}")

    valid = {"Pending", "In Review", "Reviewed", "Complete"}
    if review_status not in valid:
        return {"error": f"Invalid review_status. Must be one of: {valid}"}

    now = datetime.now(timezone.utc).isoformat()
    query = f"UPDATE `{TABLE_ID}` SET review_status = @status, updated_on = @updated_on WHERE case_id = @case_id"
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("status", "STRING", review_status),
        bigquery.ScalarQueryParameter("updated_on", "TIMESTAMP", now),
        bigquery.ScalarQueryParameter("case_id", "STRING", case_id),
    ])
    try:
        bq_client.query(query, job_config=job_config).result()
        return {"case_id": case_id, "review_status": review_status, "updated_on": now}
    except Exception as e:
        return {"error": str(e)}


def _auto_resolve_errors(gcs_folder: str):
    """Auto-resolve any unresolved errors for this folder after successful processing."""
    from datetime import datetime, timezone
    try:
        now = datetime.now(timezone.utc).isoformat()
        query = f"""
        UPDATE `{PROJECT_ID}.{DATASET_ID}.processing_errors`
        SET resolved = TRUE, resolved_at = @now, resolved_by = 'System (auto-resolved on retry success)'
        WHERE gcs_folder = @gcs_folder AND resolved = FALSE
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                bigquery.ScalarQueryParameter("gcs_folder", "STRING", gcs_folder),
            ]
        )
        bq_client.query(query, job_config=job_config).result()
    except Exception:
        pass  # Don't fail the main flow if resolve fails


def log_processing_error(gcs_folder: str, error_step: str, error_message: str, last_successful_step: str = "none", partial_data: str = "{}") -> dict:
    """Logs a processing error to BigQuery.

    Args:
        gcs_folder: GCS folder URI that failed.
        error_step: Step that failed (classification, extraction, fetch_rules, client_history, evaluate_uw_rules, save).
        error_message: The error message.
        last_successful_step: Last step that completed successfully.
        partial_data: JSON string of any data collected before failure.

    Returns:
        Dict with error_id and confirmation.
    """
    import uuid
    from datetime import datetime, timezone

    error_id = f"ERR-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc).isoformat()

    query = f"""
    INSERT INTO `{PROJECT_ID}.{DATASET_ID}.processing_errors`
    (error_id, gcs_folder, error_step, error_message, last_successful_step, partial_data, retry_count, created_on, resolved)
    VALUES
    (@error_id, @gcs_folder, @error_step, @error_message, @last_successful_step, @partial_data, 0, @created_on, FALSE)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("error_id", "STRING", error_id),
            bigquery.ScalarQueryParameter("gcs_folder", "STRING", gcs_folder),
            bigquery.ScalarQueryParameter("error_step", "STRING", error_step),
            bigquery.ScalarQueryParameter("error_message", "STRING", error_message),
            bigquery.ScalarQueryParameter("last_successful_step", "STRING", last_successful_step),
            bigquery.ScalarQueryParameter("partial_data", "STRING", partial_data),
            bigquery.ScalarQueryParameter("created_on", "TIMESTAMP", now),
        ]
    )
    try:
        bq_client.query(query, job_config=job_config).result()
        return {"error_id": error_id, "gcs_folder": gcs_folder, "error_step": error_step, "logged": True}
    except Exception as e:
        return {"error": f"Failed to log error: {e}"}


def get_processing_errors(resolved: bool = False) -> dict:
    """Lists processing errors from BigQuery.

    Args:
        resolved: If True, show resolved errors. If False, show unresolved.

    Returns:
        Dict with list of errors.
    """
    query = f"SELECT * FROM `{PROJECT_ID}.{DATASET_ID}.processing_errors` WHERE resolved = @resolved ORDER BY created_on DESC LIMIT 20"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("resolved", "BOOL", resolved)]
    )
    rows = list(bq_client.query(query, job_config=job_config).result())
    return {"errors": [dict(r) for r in rows], "count": len(rows)}


def resolve_processing_error(error_id: str, resolved_by: str = "System") -> dict:
    """Marks a processing error as resolved.

    Args:
        error_id: The error ID to resolve.
        resolved_by: Who resolved it.

    Returns:
        Dict with confirmation.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    query = f"""
    UPDATE `{PROJECT_ID}.{DATASET_ID}.processing_errors`
    SET resolved = TRUE, resolved_at = @resolved_at, resolved_by = @resolved_by
    WHERE error_id = @error_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("error_id", "STRING", error_id),
            bigquery.ScalarQueryParameter("resolved_at", "TIMESTAMP", now),
            bigquery.ScalarQueryParameter("resolved_by", "STRING", resolved_by),
        ]
    )
    try:
        bq_client.query(query, job_config=job_config).result()
        return {"error_id": error_id, "resolved": True, "resolved_by": resolved_by}
    except Exception as e:
        return {"error": str(e)}


def save_pending_classification(gcs_folder: str, classification_results: str) -> dict:
    """Saves a partial submission with status 'Pending Classification' when confidence is low.

    Args:
        gcs_folder: GCS folder URI.
        classification_results: JSON string with classification results including confidence scores.

    Returns:
        Dict with case_id and status.
    """
    import random
    from datetime import datetime, timezone

    case_id = f"NB-26-{random.randint(10000, 99999)}"
    now = datetime.now(timezone.utc).isoformat()

    query = f"""
    INSERT INTO `{TABLE_ID}`
    (case_id, created_on, updated_on, status, gcs_folder, extracted_json)
    VALUES
    (@case_id, @now, @now, 'Pending Classification', @gcs_folder, @classification_results)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("case_id", "STRING", case_id),
            bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
            bigquery.ScalarQueryParameter("gcs_folder", "STRING", gcs_folder),
            bigquery.ScalarQueryParameter("classification_results", "STRING", classification_results),
        ]
    )
    try:
        bq_client.query(query, job_config=job_config).result()
        return {"case_id": case_id, "status": "Pending Classification", "gcs_folder": gcs_folder}
    except Exception as e:
        return {"error": str(e)}
