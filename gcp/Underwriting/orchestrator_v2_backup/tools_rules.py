"""Rules tools — reads business rules from Excel in GCS."""

import os
import io
import json
import re
import logging

from google.cloud import storage
import openpyxl

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
BUCKET_NAME = os.getenv("BUCKET_NAME", "underwriting-workbench")
RULES_FILE = os.getenv("RULES_FILE", "Rules/UW Workbench_Business Rules.xlsx")

gcs_client = storage.Client(project=PROJECT_ID)

PRIORITY_ORDER = ["P0", "P1", "P2", "P3", "P4", "Decline"]


def _download_workbook():
    blob = gcs_client.bucket(BUCKET_NAME).blob(RULES_FILE)
    return openpyxl.load_workbook(io.BytesIO(blob.download_as_bytes()))


def get_all_rules() -> dict:
    """Reads all underwriting business rules (priority, risk score, assignment) from GCS.

    Returns:
        Dict with priority, risk_score, and assignment rule sets.
    """
    logger.info("Tool: get_all_rules")
    try:
        wb = _download_workbook()
        rules = {}

        # Priority rules
        ws = wb["Submission Priority Rules"]
        lob_rules = []
        for row in ws.iter_rows(min_row=3, max_row=8, min_col=2, max_col=3, values_only=True):
            if row[0] and row[1]:
                lob_rules.append({"lob": str(row[0]).strip(), "priority": str(row[1]).strip()})
        override_rules = []
        if ws.cell(row=3, column=5).value:
            override_rules.append({"condition": "renewal_days_less_than", "value": 5, "priority": "P0"})
        if ws.cell(row=7, column=5).value:
            override_rules.append({"condition": "sum_insured_greater_than", "value": 10000000, "priority": "P0"})
        broker_rules = []
        for row in ws.iter_rows(min_row=3, max_row=5, min_col=8, max_col=9, values_only=True):
            if row[0] and row[1]:
                broker_rules.append({"broker": str(row[0]).strip(), "priority": str(row[1]).strip()})
        rules["priority"] = {"lob_rules": lob_rules, "override_rules": override_rules, "broker_rules": broker_rules}

        # Risk score rules
        ws2 = wb["UW Risk Score Rules"]
        risk = {"year_built": [], "eq_zone": [], "flood_zone": [], "construction_type": []}
        for row in ws2.iter_rows(min_row=3, max_row=7, min_col=2, max_col=3, values_only=True):
            if row[0] and row[1] is not None:
                risk["year_built"].append({"range": str(row[0]).strip(), "score": str(row[1]).strip()})
        for row in ws2.iter_rows(min_row=3, max_row=6, min_col=5, max_col=6, values_only=True):
            if row[0] and row[1] is not None:
                risk["eq_zone"].append({"zone": str(row[0]).strip(), "score": str(row[1]).strip()})
        for row in ws2.iter_rows(min_row=3, max_row=6, min_col=8, max_col=9, values_only=True):
            if row[0] and row[1] is not None:
                risk["flood_zone"].append({"zone": str(row[0]).strip(), "score": str(row[1]).strip()})
        for row in ws2.iter_rows(min_row=3, max_row=6, min_col=11, max_col=12, values_only=True):
            if row[0] and row[1] is not None:
                risk["construction_type"].append({"type": str(row[0]).strip(), "score": str(row[1]).strip()})
        rules["risk_score"] = risk

        # Assignment rules
        ws3 = wb["Submission Assignment Rules"]
        underwriters = []
        for row in ws3.iter_rows(min_row=3, max_row=14, min_col=2, max_col=3, values_only=True):
            if row[0] and row[1]:
                underwriters.append({"lob": str(row[0]).strip(), "underwriter": str(row[1]).strip()})
        assignment_rules = []
        for row in ws3.iter_rows(min_row=3, max_row=14, min_col=5, max_col=6, values_only=True):
            if row[0] and row[1]:
                assignment_rules.append({"condition": str(row[0]).strip(), "underwriter": str(row[1]).strip()})
        rules["assignment"] = {"underwriters": underwriters, "assignment_rules": assignment_rules}

        return {"rules": rules}
    except Exception as e:
        return {"error": str(e)}


def _normalize(text: str) -> str:
    if not text: return ""
    return re.sub(r'[^a-z0-9\s]', '', text.lower().strip())


def _match_lob(extracted_lob: str, rule_lob: str) -> bool:
    e, r = _normalize(extracted_lob), _normalize(rule_lob)
    if not e or not r: return False
    if e == r or r in e or e in r: return True
    return set(r.split()).issubset(set(e.split())) or set(e.split()).issubset(set(r.split()))


def _match_broker(extracted_broker: str, rule_broker: str) -> bool:
    e, r = _normalize(extracted_broker), _normalize(rule_broker)
    if not e or not r: return False
    return r in e or e in r


def apply_uw_rules(extracted_fields_json: str, rules_json: str, client_history_json: str = "{}") -> dict:
    """Applies underwriting business rules to extracted submission fields.

    Evaluates priority (from LoB, overrides, broker), risk score (year built, EQ, flood, construction),
    and assignment (underwriter routing). All logic is deterministic from the rules.

    Args:
        extracted_fields_json: JSON string with extracted fields (lob, renewal_days, sum_insured, broker, year_built, eq_zone, flood_zone, construction_type).
        rules_json: JSON string with all rules from get_all_rules().
        client_history_json: Optional JSON string with client history.

    Returns:
        Dict with priority, risk_score, risk_level, assigned_to, auto_decline, and full breakdown.
    """
    logger.info("Tool: apply_uw_rules")
    try:
        fields = json.loads(extracted_fields_json) if isinstance(extracted_fields_json, str) else extracted_fields_json
        rules = json.loads(rules_json) if isinstance(rules_json, str) else rules_json
        json.loads(client_history_json) if isinstance(client_history_json, str) else client_history_json
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}

    if "rules" in rules:
        rules = rules["rules"]

    priority_rules = rules.get("priority", {})
    risk_rules = rules.get("risk_score", {})
    assignment_rules = rules.get("assignment", {})

    lob = fields.get("lob", "")
    renewal_days = fields.get("renewal_days")
    sum_insured = fields.get("sum_insured")
    broker = fields.get("broker", "")

    # Priority
    base_priority = "P4"
    matched_lob_rule = None
    auto_decline = False
    decline_reason = None

    for rule in priority_rules.get("lob_rules", []):
        if _match_lob(lob, rule["lob"]):
            base_priority = rule["priority"]
            matched_lob_rule = rule["lob"]
            if base_priority == "Decline":
                auto_decline = True
                decline_reason = f"LoB '{lob}' matched '{rule['lob']}' -> Decline"
            break

    if matched_lob_rule is None:
        for rule in priority_rules.get("lob_rules", []):
            if "rest" in rule["lob"].lower():
                base_priority = rule["priority"]
                matched_lob_rule = rule["lob"]
                break

    final_priority = base_priority
    override_reasons = []

    if not auto_decline:
        for rule in priority_rules.get("override_rules", []):
            cond, val, op = rule["condition"], rule["value"], rule["priority"]
            if cond == "renewal_days_less_than" and renewal_days is not None and 0 < renewal_days < val:
                override_reasons.append(f"Renewal days ({renewal_days}) < {val}")
                if PRIORITY_ORDER.index(op) < PRIORITY_ORDER.index(final_priority):
                    final_priority = op
            elif cond == "sum_insured_greater_than" and sum_insured is not None and sum_insured > val:
                override_reasons.append(f"Sum insured (${sum_insured:,.0f}) > ${val:,.0f}")
                if PRIORITY_ORDER.index(op) < PRIORITY_ORDER.index(final_priority):
                    final_priority = op

        for rule in priority_rules.get("broker_rules", []):
            if _match_broker(broker, rule["broker"]):
                override_reasons.append(f"Broker '{broker}' matched '{rule['broker']}'")
                if PRIORITY_ORDER.index(rule["priority"]) < PRIORITY_ORDER.index(final_priority):
                    final_priority = rule["priority"]
                break

    # Risk score
    def _eval_year(yb, rules_list):
        if yb is None: return {"score": 0, "matched_rule": "No data", "decline": False}
        year = int(yb)
        for rule in rules_list:
            rt = rule["range"].lower()
            sc = rule["score"].strip()
            if "after" in rt:
                t = int(re.search(r'\d{4}', rt).group())
                if year > t: return {"score": 0 if sc == "Decline" else int(sc), "matched_rule": rule["range"], "decline": sc == "Decline"}
            elif "before" in rt:
                t = int(re.search(r'\d{4}', rt).group())
                if year < t: return {"score": 0, "matched_rule": rule["range"], "decline": True}
            elif "between" in rt or "-" in rt:
                yrs = re.findall(r'\d{4}', rt)
                if len(yrs) == 2 and int(yrs[0]) <= year <= int(yrs[1]):
                    return {"score": int(sc), "matched_rule": rule["range"], "decline": sc == "Decline"}
        return {"score": 0, "matched_rule": "No match", "decline": False}

    def _eval_zone(val, rules_list, key):
        if not val: return {"score": 0, "matched_rule": "No data", "value": None}
        for rule in rules_list:
            if _normalize(rule[key]) == _normalize(val):
                return {"score": int(rule["score"]), "matched_rule": rule[key], "value": val}
        return {"score": 0, "matched_rule": "No match", "value": val}

    yb_r = _eval_year(fields.get("year_built"), risk_rules.get("year_built", []))
    eq_r = _eval_zone(fields.get("eq_zone"), risk_rules.get("eq_zone", []), "zone")
    fl_r = _eval_zone(fields.get("flood_zone"), risk_rules.get("flood_zone", []), "zone")
    ct_r = _eval_zone(fields.get("construction_type"), risk_rules.get("construction_type", []), "type")

    if yb_r.get("decline"):
        auto_decline = True
        decline_reason = f"Year built ({fields.get('year_built')}) matched '{yb_r['matched_rule']}' -> Decline"

    total_risk = yb_r["score"] + eq_r["score"] + fl_r["score"] + ct_r["score"]
    risk_level = "Low Risk" if total_risk <= 3 else "Medium Risk" if total_risk <= 6 else "High Risk" if total_risk <= 9 else "Very High Risk"

    # Assignment
    assigned_to = None
    if not auto_decline:
        for rule in assignment_rules.get("assignment_rules", []):
            parts = rule["condition"].split(" - ", 1)
            if len(parts) != 2: continue
            pri_part, lob_part = parts[0].strip(), parts[1].strip()
            if not _match_lob(lob, lob_part) or "rest" in lob_part.lower(): continue
            if pri_part == final_priority:
                assigned_to = rule["underwriter"]; break
            elif "to" in pri_part:
                m = re.match(r'P(\d+)\s+to\s+P(\d+)', pri_part)
                if m and int(m.group(1)) <= int(final_priority.replace("P", "")) <= int(m.group(2)):
                    assigned_to = rule["underwriter"]; break

        if assigned_to is None:
            for rule in assignment_rules.get("assignment_rules", []):
                parts = rule["condition"].split(" - ", 1)
                if len(parts) != 2 or "rest" not in parts[1].lower(): continue
                pri_part = parts[0].strip()
                if pri_part == final_priority:
                    assigned_to = rule["underwriter"]; break
                elif "to" in pri_part:
                    m = re.match(r'P(\d+)\s+to\s+P(\d+)', pri_part)
                    if m and int(m.group(1)) <= int(final_priority.replace("P", "")) <= int(m.group(2)):
                        assigned_to = rule["underwriter"]; break

    return {
        "priority": final_priority if not auto_decline else "Decline",
        "base_priority": base_priority, "matched_lob_rule": matched_lob_rule,
        "override_reasons": override_reasons,
        "risk_score": total_risk, "risk_level": risk_level,
        "risk_breakdown": {
            "year_built": {"value": fields.get("year_built"), "score": yb_r["score"], "rule": yb_r["matched_rule"]},
            "eq_zone": {"value": fields.get("eq_zone"), "score": eq_r["score"], "rule": eq_r.get("matched_rule")},
            "flood_zone": {"value": fields.get("flood_zone"), "score": fl_r["score"], "rule": fl_r.get("matched_rule")},
            "construction_type": {"value": fields.get("construction_type"), "score": ct_r["score"], "rule": ct_r.get("matched_rule")},
        },
        "assigned_to": assigned_to, "auto_decline": auto_decline, "decline_reason": decline_reason,
    }
