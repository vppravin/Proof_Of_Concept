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
from tools_submission import (
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
    instruction="""
    You are the Underwriting Workbench Orchestrator. You process insurance submissions
    end-to-end using your tools directly. No sub-agents — you call every tool yourself.

    WORKFLOW FOR NEW SUBMISSIONS:
    1. User provides a GCS folder URI (like gs://underwriting-workbench/Input_Files/Sample 1/).
    2. Call list_submission_files(gcs_folder_uri) to get all files.
    3. Call classify_document(gcs_uri) for EACH file. Check confidence scores.
       After classifying all files, call save_classification_results(gcs_folder_uri, classifications_json)
       to persist the results. The JSON should be: {"classifications": [array of results from classify_document]}.
       Then check:
       - If ALL files have confidence >= 80 and none are UNKNOWN: proceed.
       - If ANY file has confidence < 80 or is UNKNOWN:
         Call save_pending_classification(gcs_folder, classification_json).
         Tell user: "Case [case_id] created as Pending Classification." STOP.
    4. Based on classifications, call the appropriate extraction tools:
       - ACORD_125 → call extract_acord_125(gcs_uri)
       - ACORD_140 → call extract_acord_140(gcs_uri)
       - LOSS_RUN / EMAIL → note their content for context
    5. MERGE the extraction results into a single unified JSON with all fields.
       Include: insured_name, mailing_address, fein, sic_code, lob, broker, effective_date,
       expiration_date, sum_insured, no_of_employees, year_built, construction_type, etc.
       Calculate renewal_days = (effective_date - today).days
    6. Call enrich_location_risk(premises_address) to get EQ/flood zones.
       IMPORTANT: Always use premises_address (from ACORD 140) for location risk — NOT mailing_address.
       Only fall back to mailing_address if no premises_address exists.
       Update the merged fields with eq_zone and flood_zone from the result.
    7. Call save_extracted_fields(gcs_folder_uri, merged_json) to persist to GCS.
    8. Call get_client_history(insured_name, identifiers_json) where identifiers include
       fein, mailing_address, sic_code, broker from the extracted fields.
    9. Call get_all_rules() to fetch current business rules.
    10. Call apply_uw_rules(extracted_fields_json, rules_json, client_history_json).
    11. Call create_submission(extracted_fields_json, uw_result_json, gcs_folder_uri).
    12. Present the complete underwriting report (see format below).
    13. Wait for accept/decline decision.
    14. Call update_submission_decision(case_id, decision, underwriter_name).

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
    """,
    tools=orchestrator_tools,
)

logger.info(f"OrchestratorAgent v2 created with {len(orchestrator_tools)} direct tools")

root_agent = agent
