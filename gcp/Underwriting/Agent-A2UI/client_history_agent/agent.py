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
    format='%(asctime)s - [CLIENT_HISTORY_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing Client History Agent...")

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("MODEL", "gemini-2.0-flash")

client_history_tools = [
    FunctionTool(tools.get_client_history),
    FunctionTool(tools.create_client_history),
    FunctionTool(tools.update_client_history),
]

agent = Agent(
    model=model,
    name="ClientHistoryAgent",
    description="Fetches, creates, and updates client history records stored as JSON files in GCS.",
    instruction="""
    You are a client history agent. You manage client history records stored in GCS.

    WORKFLOW:
    - To look up a client -> call get_client_history with the client name.
      Optionally pass identifiers (FEIN, address, SIC code, broker, contact person)
      as a JSON string for confirmation. The tool fuzzy-matches the name against
      filenames in GCS, then confirms using the identifiers.
    - If client not found (new client) -> call create_client_history with the client data
    - To update existing client -> call update_client_history with name and updates

    MATCH CONFIDENCE:
    - high: 2+ identifiers confirmed (FEIN, address, SIC, broker, contact)
    - medium: 1 identifier confirmed
    - name_only: name matched but no identifiers provided to confirm
    - not_found: no matching client in the system

    CRITICAL OUTPUT RULE:
    - ALWAYS return the raw tool output as-is. Do NOT summarize, reformat, or narrate the results.
    - The tool returns a JSON dict — return that exact JSON to the caller.
    - Do NOT convert JSON to bullet points or prose.
    """,
    tools=client_history_tools,
)

logger.info("ClientHistoryAgent created successfully with embedded tools")

root_agent = agent
