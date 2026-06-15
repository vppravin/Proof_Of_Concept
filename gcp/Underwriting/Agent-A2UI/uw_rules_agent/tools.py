import json
import re
import logging

logger = logging.getLogger(__name__)

# Priority order for comparison — lower index = higher priority
PRIORITY_ORDER = ["P0", "P1", "P2", "P3", "P4", "Decline"]


def _normalize(text: str) -> str:
    """Normalize text for fuzzy comparison."""
    if not text:
        return ""
    return re.sub(r'[^a-z0-9\s]', '', text.lower().strip())


def _match_lob(extracted_lob: str, rule_lob: str) -> bool:
    """Fuzzy match LoB from extraction against rule LoB."""
    e = _normalize(extracted_lob)
    r = _normalize(rule_lob)
    if not e or not r:
        return False
    if e == r:
        return True
    if r in e or e in r:
        return True
    # Handle common variations
    r_words = set(r.split())
    e_words = set(e.split())
    if r_words.issubset(e_words) or e_words.issubset(r_words):
        return True
    return False


def _match_broker(extracted_broker: str, rule_broker: str) -> bool:
    """Fuzzy match broker name."""
    e = _normalize(extracted_broker)
    r = _normalize(rule_broker)
    if not e or not r:
        return False
    return r in e or e in r


def _evaluate_year_built(year_built, year_rules: list) -> dict:
    """Evaluate year_built against the rules dynamically by parsing range text."""
    if year_built is None:
        return {"score": 0, "matched_rule": "No year_built data", "decline": False}

    year = int(year_built)

    for rule in year_rules:
        range_text = rule["range"].lower().strip()
        score = rule["score"].strip()

        if "after" in range_text:
            # "After 2010" → year > 2010
            threshold = int(re.search(r'\d{4}', range_text).group())
            if year > threshold:
                return {"score": 0 if score == "Decline" else int(score), "matched_rule": rule["range"], "decline": score == "Decline"}

        elif "before" in range_text:
            # "Before 1970" → year < 1970
            threshold = int(re.search(r'\d{4}', range_text).group())
            if year < threshold:
                return {"score": 0, "matched_rule": rule["range"], "decline": True}

        elif "between" in range_text or "-" in range_text:
            # "between 1990 - 2010" or "Between 1980 - 1990"
            years = re.findall(r'\d{4}', range_text)
            if len(years) == 2:
                low, high = int(years[0]), int(years[1])
                if low <= year <= high:
                    return {"score": int(score), "matched_rule": rule["range"], "decline": score == "Decline"}

    return {"score": 0, "matched_rule": "No matching rule", "decline": False}


def _evaluate_zone_or_type(value: str, rules: list, key_field: str) -> dict:
    """Evaluate eq_zone, flood_zone, or construction_type against rules."""
    if not value:
        return {"score": 0, "matched_rule": "No data", "value": None}

    norm_value = _normalize(value)

    for rule in rules:
        rule_val = rule[key_field]
        if _normalize(rule_val) == norm_value:
            score = rule["score"].strip()
            return {"score": int(score), "matched_rule": rule_val, "value": value}

    return {"score": 0, "matched_rule": "No matching rule", "value": value}


# ── Tool functions ─────────────────────────────────────────────────────────

def apply_uw_rules(extracted_fields_json: str, rules_json: str, client_history_json: str = "{}") -> dict:
    """Applies underwriting rules to extracted submission fields.

    Evaluates priority, risk score, and assignment by parsing the rules JSON
    dynamically. No hardcoded rule values — all logic reads from the rules structure.

    Args:
        extracted_fields_json: JSON string with extracted submission fields.
            Required keys: lob, renewal_days, sum_insured, broker, year_built,
            eq_zone, flood_zone, construction_type
        rules_json: JSON string with all rules from get_all_rules().
        client_history_json: Optional JSON string with client history data.

    Returns:
        Dict with priority, risk_score, risk_level, assigned_to, auto_decline, and breakdown.
    """
    logger.info("Tool: apply_uw_rules")

    try:
        fields = json.loads(extracted_fields_json) if isinstance(extracted_fields_json, str) else extracted_fields_json
        rules = json.loads(rules_json) if isinstance(rules_json, str) else rules_json
        client_history = json.loads(client_history_json) if isinstance(client_history_json, str) else client_history_json
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}

    # Handle nested rules structure from get_all_rules
    if "rules" in rules:
        rules = rules["rules"]

    priority_rules = rules.get("priority", {})
    risk_rules = rules.get("risk_score", {})
    assignment_rules = rules.get("assignment", {})

    # ── Step 1: Apply Priority ──────────────────────────────────────────

    lob = fields.get("lob", "")
    renewal_days = fields.get("renewal_days")
    sum_insured = fields.get("sum_insured")
    broker = fields.get("broker", "")

    # Base priority from LoB
    base_priority = "P4"  # default if no LoB match
    matched_lob_rule = None
    auto_decline = False
    decline_reason = None

    for rule in priority_rules.get("lob_rules", []):
        if _match_lob(lob, rule["lob"]):
            base_priority = rule["priority"]
            matched_lob_rule = rule["lob"]
            if base_priority == "Decline":
                auto_decline = True
                decline_reason = f"LoB '{lob}' matched rule '{rule['lob']}' -> Decline"
            break

    # If no exact match, use "Rest of the LoB" if it exists
    if matched_lob_rule is None:
        for rule in priority_rules.get("lob_rules", []):
            if "rest" in rule["lob"].lower():
                base_priority = rule["priority"]
                matched_lob_rule = rule["lob"]
                break

    # Override rules
    final_priority = base_priority
    override_reasons = []

    if not auto_decline:
        for rule in priority_rules.get("override_rules", []):
            condition = rule["condition"]
            value = rule["value"]
            override_priority = rule["priority"]

            if condition == "renewal_days_less_than" and renewal_days is not None:
                if 0 < renewal_days < value:
                    override_reasons.append(f"Renewal days ({renewal_days}) < {value}")
                    if PRIORITY_ORDER.index(override_priority) < PRIORITY_ORDER.index(final_priority):
                        final_priority = override_priority

            elif condition == "sum_insured_greater_than" and sum_insured is not None:
                if sum_insured > value:
                    override_reasons.append(f"Sum insured (${sum_insured:,.0f}) > ${value:,.0f}")
                    if PRIORITY_ORDER.index(override_priority) < PRIORITY_ORDER.index(final_priority):
                        final_priority = override_priority

        # Broker override
        for rule in priority_rules.get("broker_rules", []):
            if _match_broker(broker, rule["broker"]):
                override_reasons.append(f"Broker '{broker}' matched '{rule['broker']}'")
                override_priority = rule["priority"]
                if PRIORITY_ORDER.index(override_priority) < PRIORITY_ORDER.index(final_priority):
                    final_priority = override_priority
                break

    # ── Step 2: Apply Risk Score ────────────────────────────────────────

    year_built_result = _evaluate_year_built(fields.get("year_built"), risk_rules.get("year_built", []))
    eq_result = _evaluate_zone_or_type(fields.get("eq_zone"), risk_rules.get("eq_zone", []), "zone")
    flood_result = _evaluate_zone_or_type(fields.get("flood_zone"), risk_rules.get("flood_zone", []), "zone")
    construction_result = _evaluate_zone_or_type(fields.get("construction_type"), risk_rules.get("construction_type", []), "type")

    # Check for decline from year_built
    if year_built_result.get("decline"):
        auto_decline = True
        decline_reason = f"Year built ({fields.get('year_built')}) matched '{year_built_result['matched_rule']}' -> Decline"

    total_risk_score = (
        year_built_result["score"] +
        eq_result["score"] +
        flood_result["score"] +
        construction_result["score"]
    )

    if total_risk_score <= 3:
        risk_level = "Low Risk"
    elif total_risk_score <= 6:
        risk_level = "Medium Risk"
    elif total_risk_score <= 9:
        risk_level = "High Risk"
    else:
        risk_level = "Very High Risk"

    # ── Step 3: Apply Assignment ────────────────────────────────────────

    assigned_to = None
    if not auto_decline:
        priority_num = final_priority  # e.g. "P0"
        for rule in assignment_rules.get("assignment_rules", []):
            condition = rule["condition"]  # e.g. "P0 - Commercial Property" or "P1 to P3 - Commercial Property"

            # Parse condition: "P0 - Commercial Property" or "P1 to P4 - Cyber"
            parts = condition.split(" - ", 1)
            if len(parts) != 2:
                continue
            priority_part = parts[0].strip()
            lob_part = parts[1].strip()

            if not _match_lob(lob, lob_part):
                continue

            # Check priority match
            if priority_part == priority_num:
                assigned_to = rule["underwriter"]
                break
            elif "to" in priority_part:
                # "P1 to P3" → check range
                range_match = re.match(r'P(\d+)\s+to\s+P(\d+)', priority_part)
                if range_match:
                    low = int(range_match.group(1))
                    high = int(range_match.group(2))
                    current = int(priority_num.replace("P", ""))
                    if low <= current <= high:
                        assigned_to = rule["underwriter"]
                        break

        # Fallback: if no LoB-specific match, try "Rest of the LOB"
        if assigned_to is None:
            for rule in assignment_rules.get("assignment_rules", []):
                condition = rule["condition"]
                parts = condition.split(" - ", 1)
                if len(parts) != 2:
                    continue
                priority_part = parts[0].strip()
                lob_part = parts[1].strip()
                if "rest" not in lob_part.lower():
                    continue
                if priority_part == priority_num:
                    assigned_to = rule["underwriter"]
                    break
                elif "to" in priority_part:
                    range_match = re.match(r'P(\d+)\s+to\s+P(\d+)', priority_part)
                    if range_match:
                        low = int(range_match.group(1))
                        high = int(range_match.group(2))
                        current = int(priority_num.replace("P", ""))
                        if low <= current <= high:
                            assigned_to = rule["underwriter"]
                            break

    # ── Build result ────────────────────────────────────────────────────

    result = {
        "priority": final_priority if not auto_decline else "Decline",
        "base_priority": base_priority,
        "matched_lob_rule": matched_lob_rule,
        "override_reasons": override_reasons,
        "risk_score": total_risk_score,
        "risk_level": risk_level,
        "risk_breakdown": {
            "year_built": {"value": fields.get("year_built"), "score": year_built_result["score"], "rule": year_built_result["matched_rule"]},
            "eq_zone": {"value": fields.get("eq_zone"), "score": eq_result["score"], "rule": eq_result.get("matched_rule")},
            "flood_zone": {"value": fields.get("flood_zone"), "score": flood_result["score"], "rule": flood_result.get("matched_rule")},
            "construction_type": {"value": fields.get("construction_type"), "score": construction_result["score"], "rule": construction_result.get("matched_rule")},
        },
        "assigned_to": assigned_to,
        "auto_decline": auto_decline,
        "decline_reason": decline_reason,
    }

    logger.info(f"UW Rules result: priority={result['priority']}, risk_score={total_risk_score}, assigned={assigned_to}, decline={auto_decline}")
    return result
