"""Submission tools — BigQuery CRUD for submission records."""

import os
import re
import io
import json
import uuid
import logging
from datetime import datetime, timezone, date

from google.cloud import bigquery, storage
import openpyxl

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
DATASET_ID = os.getenv("BQ_DATASET", "underwriting_workbench")
TABLE_ID = f"{PROJECT_ID}.{DATASET_ID}.submissions"
BUCKET_NAME = os.getenv("BUCKET_NAME", "underwriting-workbench")
RULES_FILE = os.getenv("RULES_FILE", "Rules/UW Workbench_Business Rules.xlsx")

bq_client = bigquery.Client(project=PROJECT_ID)


def _generate_case_id() -> str:
    year = datetime.now(timezone.utc).strftime("%y")
    prefix = f"NB-{year}-"
    try:
        result = list(bq_client.query(f"SELECT MAX(case_id) as max_id FROM `{TABLE_ID}` WHERE case_id LIKE '{prefix}%'").result())
        max_id = result[0].max_id if result and result[0].max_id else None
        seq = int(max_id.split("-")[-1]) + 1 if max_id else 34677
        return f"{prefix}{seq:05d}"
    except Exception:
        return f"{prefix}{int(datetime.now(timezone.utc).timestamp()) % 100000:05d}"


def _to_int(val):
    if val is None: return None
    try: return int(float(str(val).strip()))
    except (ValueError, TypeError): return None


def _to_float(val):
    if val is None: return None
    try: return float(str(val).strip().replace(",", ""))
    except (ValueError, TypeError): return None


def initialize_case(gcs_folder: str) -> dict:
    """Creates a new case record in BigQuery at the start of processing.

    Call this FIRST when a new submission arrives, before classification.
    Sets status to 'Processing' and current_step to 'classification'.

    Args:
        gcs_folder: GCS folder URI where the submission documents are stored.

    Returns:
        Dict with case_id.
    """
    logger.info(f"Tool: initialize_case for {gcs_folder}")
    case_id = _generate_case_id()
    now = datetime.now(timezone.utc).isoformat()

    try:
        query = f"""INSERT INTO `{TABLE_ID}` (case_id, created_on, updated_on, status, current_step, gcs_folder, step_timestamps)
        VALUES (@case_id, @now, @now, 'Processing', 'classification', @gcs_folder, @steps)"""
        bq_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("case_id", "STRING", case_id),
            bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
            bigquery.ScalarQueryParameter("gcs_folder", "STRING", gcs_folder),
            bigquery.ScalarQueryParameter("steps", "STRING", json.dumps({"initialized": now})),
        ])).result()
        return {"case_id": case_id, "status": "Processing", "current_step": "classification"}
    except Exception as e:
        return {"error": str(e)}


def update_case_progress(case_id: str, completed_step: str, next_step: str, data_json: str = "{}") -> dict:
    """Updates a case after a processing step completes, persisting progress.

    Call after each step so if the process fails later, we know where it stopped.

    Args:
        case_id: The Case ID.
        completed_step: Step just finished (classification, extraction, client_history, rules, evaluation).
        next_step: Next step (extraction, client_history, rules, evaluation, complete).
        data_json: JSON string with data to persist. Keys map to BigQuery columns.

    Returns:
        Dict with confirmation.
    """
    logger.info(f"Tool: update_case_progress {case_id} — {completed_step} → {next_step}")
    now = datetime.now(timezone.utc).isoformat()

    try:
        data = json.loads(data_json) if isinstance(data_json, str) else data_json
    except json.JSONDecodeError:
        data = {}

    set_parts = ["current_step = @next_step", "updated_on = @now"]
    params = [
        bigquery.ScalarQueryParameter("case_id", "STRING", case_id),
        bigquery.ScalarQueryParameter("next_step", "STRING", next_step),
        bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
    ]

    str_cols = {"classification_json", "extracted_json", "client_history_json", "uw_result_json",
                "insured_name", "mailing_address", "fein", "sic_code", "lob", "broker",
                "effective_date", "expiration_date", "proposed_carrier", "construction_type",
                "eq_zone", "flood_zone", "risk_level", "priority", "override_reasons",
                "assigned_to", "decline_reason", "justification_text"}
    float_cols = {"sum_insured"}
    int_cols = {"year_built", "no_of_employees", "renewal_days", "risk_score"}
    bool_cols = {"auto_decline"}

    json_cols = {"extracted_json", "uw_result_json", "classification_json", "client_history_json", "override_reasons"}

    # If extraction step completed, read extracted_json directly from GCS (source of truth)
    if completed_step == "extraction":
        try:
            from google.cloud import storage as _gcs
            _gc = _gcs.Client(project=PROJECT_ID)
            folder_rows = list(bq_client.query(
                f"SELECT gcs_folder FROM `{TABLE_ID}` WHERE case_id = @cid",
                job_config=bigquery.QueryJobConfig(query_parameters=[
                    bigquery.ScalarQueryParameter("cid", "STRING", case_id)
                ])).result())
            if folder_rows and folder_rows[0].gcs_folder:
                gcs_folder = folder_rows[0].gcs_folder
                bucket_name = gcs_folder.split("/")[2]
                prefix = gcs_folder.replace(f"gs://{bucket_name}/", "").strip("/") + "/"
                blob = _gc.bucket(bucket_name).blob(f"{prefix}_extracted_fields.json")
                if blob.exists():
                    gcs_ext = json.loads(blob.download_as_text())
                    data["extracted_json"] = gcs_ext
                    # Also populate top-level columns from GCS data
                    for k in ["insured_name", "mailing_address", "fein", "sic_code", "lob", "broker",
                              "effective_date", "expiration_date", "proposed_carrier", "construction_type",
                              "eq_zone", "flood_zone"]:
                        if gcs_ext.get(k) and not data.get(k):
                            data[k] = gcs_ext[k]
                    for k in ["year_built", "no_of_employees", "renewal_days"]:
                        if gcs_ext.get(k) is not None and not data.get(k):
                            data[k] = gcs_ext[k]
                    if gcs_ext.get("sum_insured") and not data.get("sum_insured"):
                        data["sum_insured"] = gcs_ext["sum_insured"]
        except Exception as _e:
            logger.warning(f"GCS extracted_fields read failed: {_e}")

    # If evaluation/complete step, read uw_result from GCS (source of truth)
    if completed_step in ("evaluation", "complete") or next_step == "complete":
        try:
            from google.cloud import storage as _gcs
            _gc = _gcs.Client(project=PROJECT_ID)
            folder_rows = list(bq_client.query(
                f"SELECT gcs_folder FROM `{TABLE_ID}` WHERE case_id = @cid",
                job_config=bigquery.QueryJobConfig(query_parameters=[
                    bigquery.ScalarQueryParameter("cid", "STRING", case_id)
                ])).result())
            if folder_rows and folder_rows[0].gcs_folder:
                gcs_folder = folder_rows[0].gcs_folder
                bucket_name = gcs_folder.split("/")[2]
                prefix = gcs_folder.replace(f"gs://{bucket_name}/", "").strip("/") + "/"
                blob = _gc.bucket(bucket_name).blob(f"{prefix}_uw_result.json")
                if blob.exists():
                    gcs_uw = json.loads(blob.download_as_text())
                    data["uw_result_json"] = gcs_uw
                    for k in ["priority", "risk_score", "risk_level", "assigned_to", "auto_decline", "decline_reason"]:
                        if gcs_uw.get(k) is not None:
                            data[k] = gcs_uw[k]
                    if gcs_uw.get("override_reasons"):
                        data["override_reasons"] = gcs_uw["override_reasons"]
        except Exception as _e:
            logger.warning(f"GCS uw_result read failed: {_e}")

    # Generate justification when case completes
    if next_step == "complete" and not data.get("justification_text"):
        try:
            ext = data.get("extracted_json") if isinstance(data.get("extracted_json"), dict) else json.loads(data.get("extracted_json", "{}"))
            uw = data.get("uw_result_json") if isinstance(data.get("uw_result_json"), dict) else json.loads(data.get("uw_result_json", "{}"))
            if ext and uw:
                import vertexai
                from vertexai.generative_models import GenerativeModel
                vertexai.init(project=PROJECT_ID, location="us-central1")
                model = GenerativeModel("gemini-2.0-flash")
                prompt = f"""You are an insurance underwriting assistant. Generate a concise justification/recommendation for this submission.

Insured: {ext.get('insured_name')}
LoB: {ext.get('lob')}
Broker: {ext.get('broker')}
Sum Insured: ${ext.get('sum_insured', 0):,.0f}
Premises: {ext.get('premises_address')}
Construction: {ext.get('construction_type')} | Year Built: {ext.get('year_built')}
Employees: {ext.get('no_of_employees')}
Loss History: {ext.get('total_claims', 0)} claims, ${ext.get('total_incurred', 0):,.0f} total incurred

Risk Score: {uw.get('risk_score')}/12 ({uw.get('risk_level')})
Priority: {uw.get('priority')}
Assigned To: {uw.get('assigned_to')}
Risk Breakdown: {json.dumps(uw.get('risk_breakdown', {}))}
Override Reasons: {uw.get('override_reasons', [])}

Write a 3-4 paragraph recommendation covering: overall risk assessment, key factors, concerns, and recommendation (accept/decline/review). Be specific with numbers."""
                resp = model.generate_content(prompt)
                data["justification_text"] = resp.text.strip()
        except Exception as _e:
            logger.warning(f"Justification generation failed: {_e}")

    for key, val in data.items():
        pn = f"d_{key}"
        if key in str_cols:
            set_parts.append(f"{key} = @{pn}")
            # Serialize dicts/lists as JSON, not Python str()
            if key in json_cols and isinstance(val, (dict, list)):
                params.append(bigquery.ScalarQueryParameter(pn, "STRING", json.dumps(val)))
            else:
                params.append(bigquery.ScalarQueryParameter(pn, "STRING", str(val) if val is not None else None))
        elif key in float_cols:
            set_parts.append(f"{key} = @{pn}")
            params.append(bigquery.ScalarQueryParameter(pn, "FLOAT64", float(val) if val is not None else None))
        elif key in int_cols:
            set_parts.append(f"{key} = @{pn}")
            params.append(bigquery.ScalarQueryParameter(pn, "INT64", int(val) if val is not None else None))
        elif key in bool_cols:
            set_parts.append(f"{key} = @{pn}")
            params.append(bigquery.ScalarQueryParameter(pn, "BOOL", bool(val) if val is not None else None))

    if next_step == "complete":
        # If priority/risk missing, RUN apply_uw_rules directly — don't rely on LLM
        if not data.get("priority") or not data.get("risk_score"):
            try:
                from google.cloud import storage as _gcs
                _gc = _gcs.Client(project=PROJECT_ID)
                folder_rows = list(bq_client.query(
                    f"SELECT gcs_folder FROM `{TABLE_ID}` WHERE case_id = @cid",
                    job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("cid", "STRING", case_id)])
                ).result())
                if folder_rows and folder_rows[0].gcs_folder:
                    gcs_folder = folder_rows[0].gcs_folder
                    # Try reading existing _uw_result.json first
                    blob_path = gcs_folder.replace(f"gs://{BUCKET_NAME}/", "").strip("/") + "/_uw_result.json"
                    uw_blob = _gc.bucket(BUCKET_NAME).blob(blob_path)
                    if uw_blob.exists():
                        uw = json.loads(uw_blob.download_as_text())
                    else:
                        # Run evaluation directly
                        from tools_rules import apply_uw_rules as _run_rules
                        uw = _run_rules(gcs_folder)
                        if "error" in uw:
                            logger.error(f"Auto-eval failed: {uw['error']}")
                            uw = {}

                    for k in ["priority", "risk_score", "risk_level", "assigned_to", "auto_decline", "decline_reason"]:
                        if uw.get(k) is not None:
                            data[k] = uw[k]
                    data["override_reasons"] = json.dumps(uw.get("override_reasons", []))
                    data["uw_result_json"] = json.dumps(uw)
                    # Add to params
                    for key, val in data.items():
                        pn = f"d_{key}"
                        if any(p.name == pn for p in params):
                            continue
                        if key in str_cols:
                            set_parts.append(f"{key} = @{pn}")
                            if key in json_cols and isinstance(val, (dict, list)):
                                params.append(bigquery.ScalarQueryParameter(pn, "STRING", json.dumps(val)))
                            else:
                                params.append(bigquery.ScalarQueryParameter(pn, "STRING", str(val) if val is not None else None))
                        elif key in float_cols:
                            set_parts.append(f"{key} = @{pn}")
                            params.append(bigquery.ScalarQueryParameter(pn, "FLOAT64", float(val) if val is not None else None))
                        elif key in int_cols:
                            set_parts.append(f"{key} = @{pn}")
                            params.append(bigquery.ScalarQueryParameter(pn, "INT64", int(val) if val is not None else None))
                        elif key in bool_cols:
                            set_parts.append(f"{key} = @{pn}")
                            params.append(bigquery.ScalarQueryParameter(pn, "BOOL", bool(val) if val is not None else None))
            except Exception as e:
                logger.warning(f"Auto-eval on complete failed: {e}")

        final_status = "Declined" if data.get("auto_decline") else "Assigned"
        set_parts.append("status = @final_status")
        params.append(bigquery.ScalarQueryParameter("final_status", "STRING", final_status))

    query = f"UPDATE `{TABLE_ID}` SET {', '.join(set_parts)} WHERE case_id = @case_id"
    bq_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
    return {"case_id": case_id, "completed_step": completed_step, "next_step": next_step}


def create_submission(extracted_fields_json: str, uw_result_json: str, gcs_folder: str = "") -> dict:
    """Creates a new submission record in BigQuery.

    Args:
        extracted_fields_json: JSON string with extracted submission fields.
        uw_result_json: JSON string with UW rules evaluation result.
        gcs_folder: GCS folder URI where documents are stored.

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

    row = {
        "case_id": case_id, "created_on": now, "updated_on": now,
        "insured_name": fields.get("insured_name"), "mailing_address": fields.get("mailing_address"),
        "fein": fields.get("fein"), "sic_code": fields.get("sic_code"), "lob": fields.get("lob"),
        "effective_date": fields.get("effective_date"), "expiration_date": fields.get("expiration_date"),
        "renewal_days": _to_int(fields.get("renewal_days")), "broker": fields.get("broker"),
        "proposed_carrier": fields.get("proposed_carrier"),
        "sum_insured": _to_float(fields.get("sum_insured")),
        "no_of_employees": _to_int(fields.get("no_of_employees")),
        "year_built": _to_int(fields.get("year_built")), "construction_type": fields.get("construction_type"),
        "eq_zone": fields.get("eq_zone"), "flood_zone": fields.get("flood_zone"),
        "risk_score": _to_int(uw.get("risk_score")), "risk_level": uw.get("risk_level"),
        "priority": uw.get("priority"), "override_reasons": json.dumps(uw.get("override_reasons", [])),
        "assigned_to": uw.get("assigned_to"), "status": status,
        "auto_decline": bool(uw.get("auto_decline", False)), "decline_reason": uw.get("decline_reason"),
        "extracted_json": json.dumps(fields), "uw_result_json": json.dumps(uw), "gcs_folder": gcs_folder,
    }

    try:
        float_cols = {"sum_insured"}
        int_cols = {"renewal_days", "no_of_employees", "year_built", "risk_score"}
        bool_cols = {"auto_decline"}

        columns = ", ".join(row.keys())
        values_params = []
        query_params = []
        for k, v in row.items():
            pn = f"p_{k}"
            values_params.append(f"@{pn}")
            if k in float_cols:
                query_params.append(bigquery.ScalarQueryParameter(pn, "FLOAT64", float(v) if v is not None else None))
            elif k in int_cols:
                query_params.append(bigquery.ScalarQueryParameter(pn, "INT64", int(v) if v is not None else None))
            elif k in bool_cols:
                query_params.append(bigquery.ScalarQueryParameter(pn, "BOOL", bool(v) if v is not None else None))
            else:
                query_params.append(bigquery.ScalarQueryParameter(pn, "STRING", str(v) if v is not None else None))

        query = f"INSERT INTO `{TABLE_ID}` ({columns}) VALUES ({', '.join(values_params)})"
        bq_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=query_params)).result()
        return {"case_id": case_id, "status": status, "assigned_to": uw.get("assigned_to")}
    except Exception as e:
        return {"error": str(e)}


def update_submission_decision(case_id: str, decision: str, decision_by: str = "Underwriter") -> dict:
    """Records accept or decline decision on a submission.

    Args:
        case_id: The Case ID e.g. NB-26-34677
        decision: 'accept' or 'decline'
        decision_by: Underwriter name.

    Returns:
        Dict with updated status.
    """
    decision = decision.strip().lower()
    if decision not in ("accept", "decline"):
        return {"error": "Decision must be 'accept' or 'decline'"}

    new_status = "Complete" if decision == "accept" else "Declined"
    now = datetime.now(timezone.utc).isoformat()

    query = f"UPDATE `{TABLE_ID}` SET status=@status, decision=@decision, decision_by=@decision_by, decision_at=@decision_at, updated_on=@updated_on WHERE case_id=@case_id"
    try:
        bq_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("status", "STRING", new_status),
            bigquery.ScalarQueryParameter("decision", "STRING", decision),
            bigquery.ScalarQueryParameter("decision_by", "STRING", decision_by),
            bigquery.ScalarQueryParameter("decision_at", "TIMESTAMP", now),
            bigquery.ScalarQueryParameter("updated_on", "TIMESTAMP", now),
            bigquery.ScalarQueryParameter("case_id", "STRING", case_id),
        ])).result()
        return {"case_id": case_id, "status": new_status, "decision": decision, "decision_by": decision_by}
    except Exception as e:
        return {"error": str(e)}


def get_submission(case_id: str) -> dict:
    """Retrieves a submission record by Case ID.

    Args:
        case_id: The Case ID e.g. NB-26-34677

    Returns:
        Dict with all submission fields.
    """
    query = f"SELECT * FROM `{TABLE_ID}` WHERE case_id = @case_id"
    try:
        rows = list(bq_client.query(query, job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("case_id", "STRING", case_id)]
        )).result())
        if not rows:
            return {"status": "not_found", "case_id": case_id}
        row = dict(rows[0])
        for k, v in row.items():
            if hasattr(v, 'isoformat'): row[k] = v.isoformat()
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
    """Updates specific fields on a submission record.

    Args:
        case_id: The Case ID.
        updates_json: JSON string with fields to update e.g. '{"fein": "58-1234567"}'

    Returns:
        Dict with case_id and updated fields.
    """
    try:
        updates = json.loads(updates_json) if isinstance(updates_json, str) else updates_json
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}

    invalid = set(updates.keys()) - EDITABLE_FIELDS
    if invalid:
        return {"error": f"Cannot edit: {invalid}"}
    if not updates:
        return {"error": "No fields to update"}

    set_clauses = []
    params = [bigquery.ScalarQueryParameter("case_id", "STRING", case_id),
              bigquery.ScalarQueryParameter("updated_on", "TIMESTAMP", datetime.now(timezone.utc).isoformat())]

    for field, value in updates.items():
        pn = f"f_{field}"
        set_clauses.append(f"{field} = @{pn}")
        if field in ("sum_insured",):
            params.append(bigquery.ScalarQueryParameter(pn, "FLOAT64", float(value) if value is not None else None))
        elif field in ("no_of_employees", "year_built", "risk_score", "renewal_days"):
            params.append(bigquery.ScalarQueryParameter(pn, "INT64", int(value) if value is not None else None))
        elif field in ("auto_decline",):
            params.append(bigquery.ScalarQueryParameter(pn, "BOOL", bool(value) if value is not None else None))
        else:
            params.append(bigquery.ScalarQueryParameter(pn, "STRING", str(value) if value is not None else None))

    set_clauses.append("updated_on = @updated_on")
    query = f"UPDATE `{TABLE_ID}` SET {', '.join(set_clauses)} WHERE case_id = @case_id"
    try:
        bq_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
        return {"case_id": case_id, "updated_fields": list(updates.keys()), "status": "updated"}
    except Exception as e:
        return {"error": str(e)}


def list_submissions(status: str = "", assigned_to: str = "", limit: int = 20) -> dict:
    """Lists submission records with optional filters.

    Args:
        status: Filter by status. Empty for all.
        assigned_to: Filter by underwriter. Empty for all.
        limit: Max records (default 20).

    Returns:
        Dict with list of submissions.
    """
    conditions, params = [], []
    if status:
        conditions.append("status = @status")
        params.append(bigquery.ScalarQueryParameter("status", "STRING", status))
    if assigned_to:
        conditions.append("LOWER(assigned_to) LIKE @assigned_to")
        params.append(bigquery.ScalarQueryParameter("assigned_to", "STRING", f"%{assigned_to.strip().lower()}%"))

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT case_id, created_on, insured_name, lob, effective_date, broker, priority, risk_score, risk_level, assigned_to, status, decision FROM `{TABLE_ID}` {where} ORDER BY created_on DESC LIMIT {limit}"

    try:
        rows = list(bq_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
        submissions = []
        for row in rows:
            r = dict(row)
            for k, v in r.items():
                if hasattr(v, 'isoformat'): r[k] = v.isoformat()
            submissions.append(r)
        return {"count": len(submissions), "submissions": submissions}
    except Exception as e:
        return {"error": str(e)}


def get_prioritized_workload(assigned_to: str = "") -> dict:
    """Gets submissions ranked by urgency score for an underwriter.

    Ranking: Priority level + effective date urgency + risk score + sum insured.

    Args:
        assigned_to: Underwriter name. Empty for all.

    Returns:
        Dict with ranked submissions and workload summary.
    """
    conditions = ["status IN ('Assigned')"]
    params = []
    if assigned_to:
        conditions.append("LOWER(assigned_to) LIKE @assigned_to")
        params.append(bigquery.ScalarQueryParameter("assigned_to", "STRING", f"%{assigned_to.strip().lower()}%"))

    query = f"SELECT * FROM `{TABLE_ID}` WHERE {' AND '.join(conditions)} ORDER BY created_on DESC"
    rows = list(bq_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())

    priority_scores = {"P0": 100, "P1": 80, "P2": 60, "P3": 40, "P4": 20}
    ranked = []

    for row in rows:
        r = dict(row)
        score = priority_scores.get(r.get("priority", ""), 0)

        eff = r.get("effective_date")
        if eff:
            try:
                eff_date = eff if isinstance(eff, date) else date.fromisoformat(eff) if isinstance(eff, str) and "-" in eff else None
                if eff_date:
                    days_left = (eff_date - date.today()).days
                    score += 50 if days_left < 0 else 45 if days_left <= 3 else 30 if days_left <= 10 else 15 if days_left <= 30 else 0
                    r["days_to_effective"] = days_left
                    r["rag_status"] = "Red" if days_left < 3 else "Amber" if days_left < 10 else "Green"
            except (ValueError, TypeError):
                pass

        rs = r.get("risk_score")
        if rs and isinstance(rs, (int, float)):
            score += min(int(rs), 12)

        si = r.get("sum_insured")
        if si and isinstance(si, (int, float)):
            score += 10 if si > 5000000 else 7 if si > 1000000 else 5 if si > 500000 else 2

        r["urgency_score"] = score
        for k, v in r.items():
            if hasattr(v, 'isoformat'): r[k] = v.isoformat()
        ranked.append(r)

    ranked.sort(key=lambda x: x.get("urgency_score", 0), reverse=True)
    for i, r in enumerate(ranked):
        r["rank"] = i + 1

    summary = {
        "total_pending": len(ranked),
        "p0_count": sum(1 for r in ranked if r.get("priority") == "P0"),
        "p1_count": sum(1 for r in ranked if r.get("priority") == "P1"),
    }

    return {
        "assigned_to": assigned_to or "All",
        "summary": summary,
        "submissions": [
            {"rank": r["rank"], "case_id": r.get("case_id"), "insured_name": r.get("insured_name"),
             "priority": r.get("priority"), "risk_score": r.get("risk_score"), "sum_insured": r.get("sum_insured"),
             "effective_date": r.get("effective_date"), "days_to_effective": r.get("days_to_effective"),
             "rag_status": r.get("rag_status"), "broker": r.get("broker"), "urgency_score": r.get("urgency_score")}
            for r in ranked
        ],
        "recommendation": f"Start with {ranked[0]['case_id']} ({ranked[0]['insured_name']}) — highest urgency ({ranked[0]['urgency_score']})" if ranked else "No pending submissions"
    }


def update_review_status(case_id: str, review_status: str) -> dict:
    """Updates the review status of a submission.

    Args:
        case_id: The Case ID.
        review_status: One of 'Pending', 'In Review', 'Reviewed', 'Complete'.

    Returns:
        Dict with confirmation.
    """
    valid = {"Pending", "In Review", "Reviewed", "Complete"}
    if review_status not in valid:
        return {"error": f"Invalid. Must be one of: {valid}"}

    now = datetime.now(timezone.utc).isoformat()
    try:
        bq_client.query(
            f"UPDATE `{TABLE_ID}` SET review_status=@status, updated_on=@updated_on WHERE case_id=@case_id",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("status", "STRING", review_status),
                bigquery.ScalarQueryParameter("updated_on", "TIMESTAMP", now),
                bigquery.ScalarQueryParameter("case_id", "STRING", case_id),
            ])
        ).result()
        return {"case_id": case_id, "review_status": review_status}
    except Exception as e:
        return {"error": str(e)}


def justify_submission(case_id: str) -> dict:
    """Generates a deterministic justification for all decisions on a submission.

    Re-runs business rules against stored data and traces each step.

    Args:
        case_id: The Case ID.

    Returns:
        Dict with priority, risk score, assignment, and auto-decline justifications.
    """
    logger.info(f"Tool: justify_submission for {case_id}")

    rows = list(bq_client.query(
        f"SELECT * FROM `{TABLE_ID}` WHERE case_id = @case_id",
        job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("case_id", "STRING", case_id)])
    ).result())
    if not rows:
        return {"error": f"Submission {case_id} not found"}

    row = dict(rows[0])
    extracted = json.loads(row.get("extracted_json", "{}"))

    # Load rules
    gcs = storage.Client(project=PROJECT_ID)
    blob = gcs.bucket(BUCKET_NAME).blob(RULES_FILE)
    wb = openpyxl.load_workbook(io.BytesIO(blob.download_as_bytes()))

    ws = wb["Submission Priority Rules"]
    lob_rules = [{"lob": str(r[0]).strip(), "priority": str(r[1]).strip()} for r in ws.iter_rows(min_row=3, max_row=8, min_col=2, max_col=3, values_only=True) if r[0] and r[1]]
    broker_rules = [{"broker": str(r[0]).strip(), "priority": str(r[1]).strip()} for r in ws.iter_rows(min_row=3, max_row=5, min_col=8, max_col=9, values_only=True) if r[0] and r[1]]

    ws2 = wb["UW Risk Score Rules"]
    year_rules = [{"range": str(r[0]).strip(), "score": str(r[1]).strip()} for r in ws2.iter_rows(min_row=3, max_row=7, min_col=2, max_col=3, values_only=True) if r[0] and r[1] is not None]
    eq_rules = [{"zone": str(r[0]).strip(), "score": str(r[1]).strip()} for r in ws2.iter_rows(min_row=3, max_row=6, min_col=5, max_col=6, values_only=True) if r[0] and r[1] is not None]
    flood_rules = [{"zone": str(r[0]).strip(), "score": str(r[1]).strip()} for r in ws2.iter_rows(min_row=3, max_row=6, min_col=8, max_col=9, values_only=True) if r[0] and r[1] is not None]
    construction_rules = [{"type": str(r[0]).strip(), "score": str(r[1]).strip()} for r in ws2.iter_rows(min_row=3, max_row=6, min_col=11, max_col=12, values_only=True) if r[0] and r[1] is not None]

    ws3 = wb["Submission Assignment Rules"]
    assignment_rules = [{"condition": str(r[0]).strip(), "underwriter": str(r[1]).strip()} for r in ws3.iter_rows(min_row=3, max_row=14, min_col=5, max_col=6, values_only=True) if r[0] and r[1]]

    def _norm(t):
        return re.sub(r'[^a-z0-9\s]', '', (t or "").lower().strip())

    lob = extracted.get("lob", "")
    broker = extracted.get("broker", "")
    sum_insured = extracted.get("sum_insured")
    renewal_days = extracted.get("renewal_days")
    year_built = extracted.get("year_built")
    eq_zone = extracted.get("eq_zone", "No")
    flood_zone = extracted.get("flood_zone", "No")
    construction = extracted.get("construction_type", "")

    # Priority trace
    priority_trace = {"base_rule": None, "overrides_evaluated": [], "final_priority": row.get("priority")}
    for rule in lob_rules:
        if _norm(rule["lob"]) in _norm(lob) or _norm(lob) in _norm(rule["lob"]):
            priority_trace["base_rule"] = f"LoB '{lob}' matched '{rule['lob']}' → {rule['priority']}"
            break
    if not priority_trace["base_rule"]:
        for rule in lob_rules:
            if "rest" in rule["lob"].lower():
                priority_trace["base_rule"] = f"LoB '{lob}' → fallback '{rule['lob']}' → {rule['priority']}"

    if renewal_days is not None:
        triggered = 0 < renewal_days < 5
        priority_trace["overrides_evaluated"].append({"rule": "Renewal days < 5", "value": renewal_days, "triggered": triggered})
    if sum_insured is not None:
        triggered = sum_insured > 10000000
        priority_trace["overrides_evaluated"].append({"rule": "Sum insured > $10M", "value": sum_insured, "triggered": triggered})

    broker_matched = False
    for rule in broker_rules:
        if _norm(rule["broker"]) in _norm(broker) or _norm(broker) in _norm(rule["broker"]):
            priority_trace["overrides_evaluated"].append({"rule": "Broker priority", "value": broker, "triggered": True, "reason": f"Matched '{rule['broker']}' → {rule['priority']}"})
            broker_matched = True
            break
    if not broker_matched:
        priority_trace["overrides_evaluated"].append({"rule": "Broker priority", "value": broker, "triggered": False})

    # Risk trace
    risk_trace = {"factors": [], "total_score": 0}

    yb_score, yb_reason = 0, "No data"
    if year_built:
        for rule in year_rules:
            rt = rule["range"].lower()
            sc = rule["score"]
            if "after" in rt:
                t = int(re.search(r'\d{4}', rt).group())
                if year_built > t: yb_score = 0 if sc == "Decline" else int(sc); yb_reason = f"{year_built} matched '{rule['range']}' → {sc}"; break
            elif "before" in rt:
                t = int(re.search(r'\d{4}', rt).group())
                if year_built < t: yb_reason = f"{year_built} matched '{rule['range']}' → DECLINE"; break
            elif "between" in rt or "-" in rt:
                yrs = re.findall(r'\d{4}', rt)
                if len(yrs) == 2 and int(yrs[0]) <= year_built <= int(yrs[1]):
                    yb_score = int(sc); yb_reason = f"{year_built} matched '{rule['range']}' → {sc}"; break
    risk_trace["factors"].append({"factor": "Year Built", "value": year_built, "score": yb_score, "reason": yb_reason})

    for label, val, rules_list, key in [("EQ Zone", eq_zone, eq_rules, "zone"), ("Flood Zone", flood_zone, flood_rules, "zone"), ("Construction", construction, construction_rules, "type")]:
        sc, reason = 0, f"'{val}' — no match"
        for rule in rules_list:
            if _norm(rule[key]) == _norm(val):
                sc = int(rule["score"]); reason = f"'{val}' matched '{rule[key]}' → {rule['score']}"; break
        risk_trace["factors"].append({"factor": label, "value": val, "score": sc, "reason": reason})

    risk_trace["total_score"] = sum(f["score"] for f in risk_trace["factors"])

    # Assignment trace
    assignment_trace = {"assigned_to": row.get("assigned_to"), "rule_matched": None}
    for rule in assignment_rules:
        parts = rule["condition"].split(" - ", 1)
        if len(parts) == 2:
            if (_norm(parts[1]) in _norm(lob) or _norm(lob) in _norm(parts[1])) and "rest" not in parts[1].lower():
                if parts[0].strip() == row.get("priority"):
                    assignment_trace["rule_matched"] = f"'{rule['condition']}' → {rule['underwriter']}"
                    break

    return {
        "case_id": case_id, "insured_name": extracted.get("insured_name"),
        "priority_justification": priority_trace,
        "risk_score_justification": risk_trace,
        "assignment_justification": assignment_trace,
    }


def save_pending_classification(gcs_folder: str, classification_results: str) -> dict:
    """Updates existing case to 'Pending Classification' status when documents can't be classified.

    Args:
        gcs_folder: GCS folder URI.
        classification_results: JSON string with classification results.

    Returns:
        Dict with case_id.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        # Find existing case for this folder
        rows = list(bq_client.query(
            f"SELECT case_id FROM `{TABLE_ID}` WHERE gcs_folder = @gf LIMIT 1",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("gf", "STRING", gcs_folder)
            ])).result())
        if rows:
            case_id = rows[0].case_id
            bq_client.query(
                f"UPDATE `{TABLE_ID}` SET status = 'Pending Classification', classification_json = @cr, updated_on = @now WHERE case_id = @cid",
                job_config=bigquery.QueryJobConfig(query_parameters=[
                    bigquery.ScalarQueryParameter("cr", "STRING", classification_results),
                    bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                    bigquery.ScalarQueryParameter("cid", "STRING", case_id),
                ])).result()
        else:
            case_id = _generate_case_id()
            bq_client.query(
                f"INSERT INTO `{TABLE_ID}` (case_id, created_on, updated_on, status, gcs_folder, classification_json) VALUES (@case_id, @now, @now, 'Pending Classification', @gcs_folder, @cr)",
                job_config=bigquery.QueryJobConfig(query_parameters=[
                    bigquery.ScalarQueryParameter("case_id", "STRING", case_id),
                    bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                    bigquery.ScalarQueryParameter("gcs_folder", "STRING", gcs_folder),
                    bigquery.ScalarQueryParameter("cr", "STRING", classification_results),
                ])).result()
        return {"case_id": case_id, "status": "Pending Classification", "gcs_folder": gcs_folder}
    except Exception as e:
        return {"error": str(e)}


def log_processing_error(gcs_folder: str, error_step: str, error_message: str, last_successful_step: str = "none", case_id: str = "") -> dict:
    """Logs a processing error to BigQuery.

    Args:
        gcs_folder: GCS folder that failed.
        error_step: Step that failed.
        error_message: The error message.
        last_successful_step: Last successful step.
        case_id: The case ID if available.

    Returns:
        Dict with error_id.
    """
    error_id = f"ERR-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc).isoformat()
    # Auto-find case_id from gcs_folder if not provided
    if not case_id:
        try:
            rows = list(bq_client.query(
                f"SELECT case_id FROM `{TABLE_ID}` WHERE gcs_folder = @gf LIMIT 1",
                job_config=bigquery.QueryJobConfig(query_parameters=[
                    bigquery.ScalarQueryParameter("gf", "STRING", gcs_folder)
                ])).result())
            if rows: case_id = rows[0].case_id
        except: pass
    try:
        bq_client.query(
            f"INSERT INTO `{PROJECT_ID}.{DATASET_ID}.processing_errors` (error_id, gcs_folder, error_step, error_message, last_successful_step, retry_count, created_on, resolved, case_id) VALUES (@eid, @gf, @es, @em, @ls, 0, @now, FALSE, @cid)",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("eid", "STRING", error_id),
                bigquery.ScalarQueryParameter("gf", "STRING", gcs_folder),
                bigquery.ScalarQueryParameter("es", "STRING", error_step),
                bigquery.ScalarQueryParameter("em", "STRING", error_message),
                bigquery.ScalarQueryParameter("ls", "STRING", last_successful_step),
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                bigquery.ScalarQueryParameter("cid", "STRING", case_id),
            ])
        ).result()
        return {"error_id": error_id, "logged": True}
    except Exception as e:
        return {"error": f"Failed to log: {e}"}


def get_processing_errors(resolved: bool = False) -> dict:
    """Lists processing errors.

    Args:
        resolved: If True show resolved, if False show unresolved.

    Returns:
        Dict with error list.
    """
    rows = list(bq_client.query(
        f"SELECT * FROM `{PROJECT_ID}.{DATASET_ID}.processing_errors` WHERE resolved = @r ORDER BY created_on DESC LIMIT 20",
        job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("r", "BOOL", resolved)])
    ).result())
    errors = []
    for row in rows:
        r = dict(row)
        for k, v in r.items():
            if hasattr(v, 'isoformat'): r[k] = v.isoformat()
        errors.append(r)
    return {"errors": errors, "count": len(errors)}


def resolve_processing_error(error_id: str, resolved_by: str = "System") -> dict:
    """Marks a processing error as resolved.

    Args:
        error_id: The error ID.
        resolved_by: Who resolved it.

    Returns:
        Dict with confirmation.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        bq_client.query(
            f"UPDATE `{PROJECT_ID}.{DATASET_ID}.processing_errors` SET resolved=TRUE, resolved_at=@now, resolved_by=@by WHERE error_id=@eid",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("eid", "STRING", error_id),
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                bigquery.ScalarQueryParameter("by", "STRING", resolved_by),
            ])
        ).result()
        return {"error_id": error_id, "resolved": True}
    except Exception as e:
        return {"error": str(e)}
