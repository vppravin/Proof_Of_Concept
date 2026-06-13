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
    format='%(asctime)s - [UW_RULES_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing UW Rules Agent...")

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("MODEL", "gemini-2.0-flash")

uw_rules_tools = [
    FunctionTool(tools.apply_uw_rules),
]

agent = Agent(
    model=model,
    name="UWRulesAgent",
    description="Applies underwriting business rules (priority, risk score, assignment) to extracted submission data.",
    instruction="""
    You are an underwriting rules evaluation agent. You apply business rules to
    extracted submission data to determine priority, risk score, and underwriter assignment.

    WORKFLOW:
    - Receive extracted fields JSON, rules JSON, and optionally client history JSON
    - Call apply_uw_rules with all three inputs
    - Return the evaluation result including priority, risk score, risk level,
      assigned underwriter, and whether the submission is auto-declined

    EVALUATION:
    - Priority is determined by LoB, with overrides for renewal urgency, sum insured, and broker
    - Risk score is the sum of year_built, eq_zone, flood_zone, and construction_type scores
    - Assignment maps priority + LoB to a specific underwriter
    - Auto-decline triggers if LoB is Marine or year_built is before 1970

    CRITICAL OUTPUT RULE:
    - ALWAYS return the raw tool output as-is. Do NOT summarize, reformat, or narrate the results.
    - The tool returns a JSON dict — return that exact JSON to the caller.
    - Do NOT convert JSON to bullet points or prose.
    """,
    tools=uw_rules_tools,
)

logger.info("UWRulesAgent created successfully with embedded tools")

root_agent = agent
