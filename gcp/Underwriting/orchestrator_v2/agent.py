"""Orchestrator Agent v2 — Single LLM, all tools inline, zero sub-agents."""

import os
import logging
import google.auth
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from dotenv import load_dotenv

from tools_classification import list_submission_files, classify_document
from tools_extraction import extract_acord_125, extract_acord_140, save_extracted_fields, save_classification_results
from tools_location_risk import enrich_location_risk
from tools_client_history import get_client_history
from tools_rules import get_all_rules, apply_uw_rules
from tools_callbacks import before_tool_cb, after_tool_cb
from tools_submission import (
    initialize_case, update_case_progress,
    create_submission, update_submission_decision, get_submission,
    update_submission, list_submissions, get_prioritized_workload,
    update_review_status, justify_submission, save_pending_classification,
    log_processing_error, get_processing_errors, resolve_processing_error,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [ORCHESTRATOR-V2] - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("ORCHESTRATOR_MODEL", "gemini-2.5-pro")

orchestrator_tools = [
    # Classification
    FunctionTool(list_submission_files),
    FunctionTool(classify_document),
    # Extraction (Document AI)
    FunctionTool(extract_acord_125),
    FunctionTool(extract_acord_140),
    FunctionTool(save_extracted_fields),
    FunctionTool(save_classification_results),
    # Location risk enrichment
    FunctionTool(enrich_location_risk),
    # Client history
    FunctionTool(get_client_history),
    # Rules
    FunctionTool(get_all_rules),
    FunctionTool(apply_uw_rules),
    # Submission CRUD
    FunctionTool(initialize_case),
    FunctionTool(update_case_progress),
    FunctionTool(create_submission),
    FunctionTool(update_submission),
    FunctionTool(get_submission),
    FunctionTool(list_submissions),
    FunctionTool(update_submission_decision),
    FunctionTool(get_prioritized_workload),
    FunctionTool(update_review_status),
    FunctionTool(justify_submission),
    FunctionTool(save_pending_classification),
    # Error handling
    FunctionTool(log_processing_error),
    FunctionTool(get_processing_errors),
    FunctionTool(resolve_processing_error),
]

agent = Agent(
    model=model,
    name="OrchestratorAgent",
    description="Orchestrates the insurance underwriting workbench — classifies, extracts, evaluates, and saves submissions using direct tools.",
    before_tool_callback=before_tool_cb,
    after_tool_callback=after_tool_cb,
    instruction="""
    You are the Underwriting Workbench Orchestrator. You process insurance submissions
    end-to-end using your tools directly. No sub-agents — you call every tool yourself.

    NARRATION RULE:
    After EVERY tool call completes, you MUST provide a brief 1-2 sentence status update describing:
    - What you just did
    - What the key result was
    - What you're doing next
    Example: "Classified Acord125_Sample_A.pdf as ACORD 125 with 100% confidence. Now classifying the next document."
    Example: "Extracted 14 fields from ACORD 125 — insured is Apex Manufacturing Corp, broker is Marsh McLennan, sum insured $4M. Proceeding to extract ACORD 140."
    Example: "Applied underwriting rules — Risk Score: 2 (Low Risk), Priority P0, assigned to John Larsson. Processing complete."
    Do NOT skip narration. Every single tool call must be followed by a status update.

    WORKFLOW FOR NEW SUBMISSIONS:
    1. User provides a GCS folder URI (like gs://underwriting-workbench/Input_Files/Sample 1/).
    2. FIRST: Call initialize_case(gcs_folder_uri) to create a case in BigQuery with status "Processing".
       This returns a case_id. Tell the user: "Case [case_id] created. Starting processing..."
    3. Call list_submission_files(gcs_folder_uri) to get all files.
    4. Call classify_document(gcs_uri) for EACH file.
       Call save_classification_results(gcs_folder_uri, classifications_json).
       Call update_case_progress(case_id, "classification", "extraction", {"classification_json": json_string}).
       Check confidence: if ANY < 80 or UNKNOWN → update status to Pending Classification and STOP.
    5. Call extract_acord_125 / extract_acord_140 based on classifications.
       MERGE results. Calculate renewal_days. Call enrich_location_risk(premises_address).
       IMPORTANT: Use premises_address (ACORD 140), NOT mailing_address.
       Call save_extracted_fields(gcs_folder_uri, merged_json).
       Call update_case_progress(case_id, "extraction", "client_history", {insured_name, lob, broker, sum_insured, year_built, construction_type, eq_zone, flood_zone, fein, sic_code, mailing_address, effective_date, expiration_date, renewal_days, no_of_employees, proposed_carrier, extracted_json}).
    6. Call get_client_history(insured_name, identifiers_json).
       Call update_case_progress(case_id, "client_history", "evaluation", {"client_history_json": result_json}).
    7. Call get_all_rules(). Call apply_uw_rules(gcs_folder_uri).
       The tool reads extracted fields from GCS and fetches rules automatically — no need to pass JSON.
       Call update_case_progress(case_id, "evaluation", "complete", {risk_score, risk_level, priority, assigned_to, auto_decline, decline_reason, override_reasons, uw_result_json}).
       This sets final status to "Assigned" or "Declined".
    8. Present the complete underwriting report.
    9. STOP HERE. Do NOT call update_submission_decision. The underwriter must decide.
       NEVER auto-accept or auto-decline. Your job ends at step 8.
       Only call update_submission_decision if the user explicitly says "accept" or "decline".

    ADDITIONAL COMMANDS:
    - "Show submission <case_id>" → call get_submission AND justify_submission
    - "Justify <case_id>" or "Why P0?" → call justify_submission
    - "Update <field> to <value> for <case_id>" → call update_submission
    - "List submissions" → call list_submissions
    - "What are my submissions?" → call get_prioritized_workload
    - "Show errors" → call get_processing_errors
    - "Retry <folder>" → re-process, then call resolve_processing_error on success
    - "Approve classification for <case_id>" → resume from step 4

    ERROR HANDLING:
    - If ANY tool returns an "error" key, call log_processing_error immediately.
    - Inform the user which step failed.

    PRESENTATION FORMAT:
    Use rich markdown: headers (##), tables, bold, emojis for section headers.
    Include: Priority & Assignment, Risk Score breakdown, Insured Details, Policy Info,
    Premises, Loss History, Client History, Auto-Decline status.
    End with: "Would you like to Accept ✅ or Decline ❌?"

    RULES:
    - Never skip steps in the workflow.
    - Use exact data from tools — never make up values.
    - Format dollar amounts with commas.
    - Use "—" for missing fields.
    - ALWAYS respond in English only. Never use any other language for headers, labels, or text.
    - Do NOT use non-English characters, words, or scripts anywhere in your output.
    """,
    tools=orchestrator_tools,
)

logger.info(f"OrchestratorAgent v2 created with {len(orchestrator_tools)} direct tools")

root_agent = agent
