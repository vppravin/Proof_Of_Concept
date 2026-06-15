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
    format='%(asctime)s - [CLASSIFICATION_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing Classification Agent...")

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("MODEL", "gemini-2.0-flash")

classification_tools = [
    FunctionTool(tools.list_submission_files),
    FunctionTool(tools.classify_document),
    FunctionTool(tools.classify_submission),
]

agent = Agent(
    model=model,
    name="ClassificationAgent",
    description="Validates and classifies uploaded insurance submission documents by reading their content.",
    instruction="""
    You are an insurance document classification agent. You classify uploaded
    submission documents by reading their content via Gemini Flash.

    WORKFLOW:
    - When given a folder URI → call classify_submission to list and classify all files
    - When given a single file URI → call classify_document for that file
    - When asked to just list files → call list_submission_files

    CLASSIFICATION RULES:
    - Classify by CONTENT (first page analysis), never by filename
    - Supported types: ACORD (insurance application forms), LOSS_RUN (claims history),
      EMAIL (broker communications), UNKNOWN (unrecognized)
    - Unsupported file formats (.docx, .xlsx) are marked UNKNOWN with reason
    - Each file gets a confidence level: High, Medium, or Low
    - Return all classification results as structured JSON
    """,
    tools=classification_tools,
)

logger.info("ClassificationAgent created successfully with embedded tools")

root_agent = agent
