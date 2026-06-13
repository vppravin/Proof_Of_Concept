"""Chat Agent Tools — read-only access to submissions data."""
import os
import json
import logging
from google.cloud import bigquery, storage
from datetime import datetime, timezone

logger = logging.getLogger("chat-agent")
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "gbu-demo-playground")
TABLE_ID = f"{PROJECT_ID}.underwriting_workbench.submissions"
BUCKET_NAME = "underwriting-workbench"

bq_client = bigquery.Client(project=PROJECT_ID)
gcs_client = storage.Client(project=PROJECT_ID)


def query_submissions(filter_query: str = "", limit: int = 20) -> dict:
    """Search and filter submissions. Use SQL WHERE clause syntax for filter_query.

    Args:
        filter_query: Optional SQL WHERE condition e.g. "priority = 'P0'" or "risk_score > 5" or "assigned_to = 'John Larsson'"
        limit: Max results to return.

    Returns:
        Dict with submissions list and count.
    """
    where = f"WHERE {filter_query}" if filter_query else ""
    query = f"SELECT case_id, insured_name, lob, broker, priority, risk_score, risk_level, status, assigned_to, effective_date, sum_insured, created_on FROM `{TABLE_ID}` {where} ORDER BY created_on DESC LIMIT {limit}"
    try:
        rows = [dict(r) for r in bq_client.query(query).result()]
        for r in rows:
            for k, v in r.items():
                if hasattr(v, 'isoformat'):
                    r[k] = v.isoformat()
        return {"count": len(rows), "submissions": rows}
    except Exception as e:
        return {"error": str(e)}


def get_submission_detail(case_id: str) -> dict:
    """Get full details of a specific submission including all extracted fields and UW result.

    Args:
        case_id: The case ID e.g. NB-26-34685

    Returns:
        Dict with all submission fields, extracted data, and UW result.
    """
    try:
        rows = list(bq_client.query(
            f"SELECT * FROM `{TABLE_ID}` WHERE case_id = @cid",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("cid", "STRING", case_id)
            ])).result())
        if not rows:
            return {"error": f"Case {case_id} not found"}
        row = dict(rows[0])
        # Parse JSON fields
        for field in ("extracted_json", "uw_result_json", "classification_json", "client_history_json"):
            if row.get(field):
                try:
                    row[field] = json.loads(row[field])
                except:
                    pass
        for k, v in row.items():
            if hasattr(v, 'isoformat'):
                row[k] = v.isoformat()
        return row
    except Exception as e:
        return {"error": str(e)}


def get_urgency_ranking(assigned_to: str = "") -> dict:
    """Get submissions ranked by weighted urgency score.

    Scoring algorithm:
    1. Priority level (P0=100, P1=80, P2=60, P3=40, P4=20)
    2. Effective date urgency (past due=50, <3 days=45, <10 days=30, <30 days=15)
    3. Risk score (0-12 direct)
    4. Sum insured (>$5M=10, >$1M=7, >$500K=5, else=2)

    Args:
        assigned_to: Filter by underwriter name. Empty for all.

    Returns:
        Dict with ranked submissions including urgency_score.
    """
    from datetime import date
    conditions = ["status = 'Assigned'"]
    params = []
    if assigned_to:
        conditions.append("assigned_to = @assigned_to")
        params.append(bigquery.ScalarQueryParameter("assigned_to", "STRING", assigned_to))

    query = f"SELECT case_id, insured_name, priority, risk_score, effective_date, status, assigned_to, lob, sum_insured FROM `{TABLE_ID}` WHERE {' AND '.join(conditions)}"
    try:
        rows = list(bq_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
        priority_scores = {"P0": 100, "P1": 80, "P2": 60, "P3": 40, "P4": 20}
        ranked = []
        for row in rows:
            r = dict(row)
            score = 0
            score += priority_scores.get(r.get("priority", ""), 0)

            eff = r.get("effective_date")
            if eff:
                try:
                    if isinstance(eff, str):
                        parts = eff.split("/")
                        eff_date = date(int(parts[2]), int(parts[0]), int(parts[1])) if len(parts) == 3 else date.fromisoformat(eff)
                    else:
                        eff_date = eff if isinstance(eff, date) else eff.date()
                    days_left = (eff_date - date.today()).days
                    if days_left < 0: score += 50
                    elif days_left <= 3: score += 45
                    elif days_left <= 10: score += 30
                    elif days_left <= 30: score += 15
                    r["days_to_effective"] = days_left
                    r["rag_status"] = "Red" if days_left < 3 else "Amber" if days_left < 10 else "Green"
                except: pass

            rs = r.get("risk_score")
            if rs: score += min(int(rs), 12)

            si = r.get("sum_insured")
            if si:
                si = float(si)
                if si > 5000000: score += 10
                elif si > 1000000: score += 7
                elif si > 500000: score += 5
                else: score += 2

            r["urgency_score"] = score
            for k, v in r.items():
                if hasattr(v, 'isoformat'): r[k] = v.isoformat()
            ranked.append(r)

        ranked.sort(key=lambda x: x.get("urgency_score", 0), reverse=True)
        return {
            "count": len(ranked),
            "scoring_method": "Priority(100/80/60/40/20) + Effective Date Urgency(0-50) + Risk Score(0-12) + Sum Insured(2-10)",
            "ranked_submissions": ranked,
            "recommendation": f"Start with {ranked[0]['case_id']} ({ranked[0]['insured_name']}) — urgency score {ranked[0]['urgency_score']}" if ranked else "No pending submissions"
        }
    except Exception as e:
        return {"error": str(e)}


def get_portfolio_stats() -> dict:
    """Get overall portfolio statistics: counts by status, priority, risk level, total sum insured.

    Returns:
        Dict with portfolio statistics.
    """
    try:
        stats = {}
        # Status counts
        rows = list(bq_client.query(f"SELECT status, COUNT(*) as cnt FROM `{TABLE_ID}` GROUP BY status").result())
        stats["by_status"] = {r.status: r.cnt for r in rows}
        # Priority counts
        rows = list(bq_client.query(f"SELECT priority, COUNT(*) as cnt FROM `{TABLE_ID}` GROUP BY priority").result())
        stats["by_priority"] = {r.priority: r.cnt for r in rows}
        # Assignee counts
        rows = list(bq_client.query(f"SELECT assigned_to, COUNT(*) as cnt FROM `{TABLE_ID}` WHERE assigned_to IS NOT NULL GROUP BY assigned_to").result())
        stats["by_assignee"] = {r.assigned_to: r.cnt for r in rows}
        # Totals
        row = list(bq_client.query(f"SELECT COUNT(*) as total, SUM(sum_insured) as total_sum, AVG(risk_score) as avg_risk FROM `{TABLE_ID}`").result())[0]
        stats["total"] = row.total
        stats["total_sum_insured"] = float(row.total_sum or 0)
        stats["avg_risk_score"] = float(row.avg_risk or 0)
        return stats
    except Exception as e:
        return {"error": str(e)}


def explain_risk_score(case_id: str) -> dict:
    """Explain how the risk score was calculated for a specific case, showing each factor.

    Args:
        case_id: The case ID.

    Returns:
        Dict with risk breakdown explanation.
    """
    try:
        rows = list(bq_client.query(
            f"SELECT uw_result_json, insured_name, risk_score, risk_level FROM `{TABLE_ID}` WHERE case_id = @cid",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("cid", "STRING", case_id)
            ])).result())
        if not rows:
            return {"error": f"Case {case_id} not found"}
        row = rows[0]
        uw = json.loads(row.uw_result_json or "{}")
        breakdown = uw.get("risk_breakdown", {})
        explanation = {
            "case_id": case_id,
            "insured_name": row.insured_name,
            "total_risk_score": row.risk_score,
            "risk_level": row.risk_level,
            "max_possible": 12,
            "factors": {}
        }
        for factor, detail in breakdown.items():
            explanation["factors"][factor] = {
                "value": detail.get("value"),
                "score": detail.get("score"),
                "rule_applied": detail.get("rule"),
                "max_score": 3
            }
        explanation["override_reasons"] = uw.get("override_reasons", [])
        return explanation
    except Exception as e:
        return {"error": str(e)}


def get_rules_summary() -> dict:
    """Get a summary of the underwriting rules: priority rules, risk scoring rules, and assignment rules.

    Returns:
        Dict with rules summary.
    """
    return {
        "priority_rules": {
            "by_lob": {"Commercial Property": "P0", "Workers Compensation": "P1", "Cyber": "P2", "Liability": "P3", "Rest": "P4", "Marine": "Decline"},
            "overrides_to_P0": ["Renewal days < 5", "Sum Insured > $10M", "Broker is Marsh, Aon, or AJG"]
        },
        "risk_score_rules": {
            "year_built": {"After 2010": 0, "1990-2010": 1, "1980-1990": 2, "1970-1980": 3, "Before 1970": "Decline"},
            "earthquake_zone": {"No": 0, "Low": 1, "Medium": 2, "High": 3},
            "flood_zone": {"No": 0, "Low": 1, "Medium": 2, "High": 3},
            "construction_type": {"Fire-resistive": 0, "Non-combustible": 1, "Ordinary": 2, "Heavy timber": 3}
        },
        "assignment_rules": {
            "Commercial Property": {"P0": "John Larsson", "P1-P3": "Harry Wills", "P4": "Mary Thomas"},
            "Workers Compensation": {"P0": "Tom Smith", "P1-P3": "Annie George", "P4": "Merin John"},
            "Cyber": {"P0": "Katty Mathew", "P1-P4": "Basil Joy"},
            "Liability": {"P0": "Kane William", "P1-P4": "Peter Kings"}
        }
    }


def get_pending_approvals() -> dict:
    """Get all submissions pending classification approval.

    Returns:
        Dict with list of pending cases including case_id, gcs_folder, classification results, and created date.
    """
    try:
        rows = list(bq_client.query(
            f"SELECT case_id, gcs_folder, classification_json, insured_name, created_on FROM `{TABLE_ID}` WHERE status = 'Pending Classification' ORDER BY created_on DESC"
        ).result())
        results = []
        for r in rows:
            row = {"case_id": r.case_id, "gcs_folder": r.gcs_folder, "insured_name": r.insured_name}
            if r.classification_json:
                try: row["classifications"] = json.loads(r.classification_json)
                except: row["classifications"] = []
            if r.created_on: row["created_on"] = r.created_on.isoformat()
            results.append(row)
        return {"count": len(results), "pending_approvals": results}
    except Exception as e:
        return {"error": str(e)}


def get_processing_errors(resolved: bool = False) -> dict:
    """Get processing errors from the system.

    Args:
        resolved: If True show resolved errors, if False show unresolved (active) errors.

    Returns:
        Dict with list of errors including error_id, case_id, failed step, error message, and timestamp.
    """
    try:
        rows = list(bq_client.query(
            f"SELECT error_id, case_id, gcs_folder, error_step, error_message, last_successful_step, retry_count, created_on, resolved FROM `{PROJECT_ID}.underwriting_workbench.processing_errors` WHERE resolved = @r ORDER BY created_on DESC",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("r", "BOOL", resolved)
            ])).result())
        results = []
        for r in rows:
            row = dict(r)
            for k, v in row.items():
                if hasattr(v, 'isoformat'): row[k] = v.isoformat()
            results.append(row)
        return {"count": len(results), "errors": results}
    except Exception as e:
        return {"error": str(e)}
