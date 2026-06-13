import os
import logging
import google.auth
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from dotenv import load_dotenv

from . import tools

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [EXTRACTION_V2] - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

logger.info("Initializing Extraction Agent v2 (Document AI)...")

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("MODEL", "gemini-2.0-flash")

extraction_tools = [
    FunctionTool(tools.process_submission_v2),
]

agent = Agent(
    model=model,
    name="ExtractionAgentV2",
    description="Extracts structured insurance fields from ACORD 125/140 forms using Document AI Form Parser. Saves results directly to GCS.",
    instruction="""
    You are an insurance document extraction agent using Document AI.

    WORKFLOW:
    - When given a folder URI + classifications JSON → call process_submission_v2
    - The tool uses Document AI Form Parser to extract fields from ACORD PDFs
    - Results are saved directly to GCS as _extracted_fields.json in the submission folder
    - Return the extracted fields summary to the caller

    CRITICAL OUTPUT RULE:
    - ALWAYS return the raw tool output as-is. Do NOT summarize, reformat, or narrate.
    - The tool returns a JSON dict — return that exact JSON to the caller.
    """,
    tools=extraction_tools,
)

logger.info("ExtractionAgentV2 created successfully")

root_agent = agent
