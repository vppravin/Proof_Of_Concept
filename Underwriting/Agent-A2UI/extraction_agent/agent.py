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
    format='%(asctime)s - [EXTRACTION_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing Extraction Agent...")

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("MODEL", "gemini-2.0-flash")

extraction_tools = [
    FunctionTool(tools.extract_fields),
    FunctionTool(tools.process_submission),
]

agent = Agent(
    model=model,
    name="ExtractionAgent",
    description="Extracts structured insurance fields from pre-classified submission documents stored in GCS.",
    instruction="""
    You are an insurance document extraction agent. You extract structured fields from
    submission documents stored in GCS using Gemini Flash multimodal.

    WORKFLOW:
    - When given a folder URI + classifications JSON → call process_submission
      It iterates each file, applies type-specific extraction prompts, and merges
      all results into a unified JSON.
    - When given a single file URI + file_type → call extract_fields
      It applies the type-specific prompt for that file type and returns extracted fields.

    EXTRACTION RULES:
    - Files are already classified — use the provided type for prompt selection
    - ACORD_125 extracts: insured info, broker, LoB, policy dates, premises addresses, loss history
    - ACORD_140 extracts: building details, construction type, year built, coverage amounts, fire protection
    - LOSS_RUN extracts: claims history, total incurred, large losses
    - EMAIL extracts: urgency, clarifications, key dates, additional context
    - UNKNOWN files are skipped during extraction
    - Return null for any field not found — never guess or fabricate values
    - Merge priority: ACORD_125 is primary for applicant/policy, ACORD_140 for building/coverage

    CRITICAL OUTPUT RULE:
    - ALWAYS return the raw tool output as-is. Do NOT summarize, reformat, or narrate the results.
    - The tool returns a JSON dict — return that exact JSON to the caller.
    - Do NOT convert JSON to bullet points or prose.
    """,
    tools=extraction_tools,
)

logger.info("ExtractionAgent created successfully with embedded tools")

root_agent = agent
