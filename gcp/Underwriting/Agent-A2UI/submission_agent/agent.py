import os
import logging
import google.auth
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from dotenv import load_dotenv

from . import tools

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [SUBMISSION_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing Submission Agent...")

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("MODEL", "gemini-2.0-flash")

submission_tools = [
    FunctionTool(tools.create_submission),
    FunctionTool(tools.update_submission_decision),
    FunctionTool(tools.update_submission),
    FunctionTool(tools.get_submission),
    FunctionTool(tools.list_submissions),
    FunctionTool(tools.justify_submission),
    FunctionTool(tools.get_prioritized_workload),
    FunctionTool(tools.update_review_status),
]

agent = Agent(
    model=model,
    name="SubmissionAgent",
    description="Manages submission records in BigQuery — create, update, query, and record accept/decline decisions.",
    instruction="""
    You are a submission record management agent. You persist underwriting
    submission data to BigQuery.

    TOOLS:
    - create_submission: Save a new submission after UW evaluation
    - update_submission_decision: Record accept/decline decision
    - update_submission: Edit/correct fields on an existing submission
    - get_submission: Retrieve a submission by Case ID
    - list_submissions: List submissions with optional filters
    - justify_submission: Generate deterministic justification for a submission

    CRITICAL OUTPUT RULE:
    - ALWAYS return the COMPLETE raw tool output as-is. Do NOT summarize or shorten.
    - If list_submissions returns 4 records, show ALL 4 records with ALL their fields.
    - If get_submission returns a record, show ALL fields of that record.
    - Do NOT say "I found 4 submissions" without listing them.
    - Return the exact JSON or data the tool returned.
    """,
    tools=submission_tools,
)

logger.info("SubmissionAgent created successfully with embedded tools")

root_agent = agent
