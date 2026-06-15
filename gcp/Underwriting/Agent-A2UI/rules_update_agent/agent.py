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
    format='%(asctime)s - [RULES_UPDATE_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing Rules Update Agent...")

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("MODEL", "gemini-2.0-flash")

rules_tools = [
    FunctionTool(tools.get_rules),
    FunctionTool(tools.get_all_rules),
    FunctionTool(tools.update_rules),
    FunctionTool(tools.validate_rules),
]

agent = Agent(
    model=model,
    name="RulesUpdateAgent",
    description="Manages underwriting business rules stored in an Excel file in GCS — read, update, and validate priority, risk score, and assignment rules.",
    instruction="""
    You are an underwriting business rules management agent. You read and update
    business rules stored in an Excel file in GCS.

    RULES STRUCTURE:
    - Three rule types: 'priority', 'risk_score', 'assignment'
    - Priority rules: LoB-based priority (P0-P4/Decline), override rules (renewal days,
      sum insured), broker-based overrides
    - Risk score rules: scoring tables for year_built, eq_zone, flood_zone, construction_type
    - Assignment rules: maps priority + LoB combination to an underwriter

    WORKFLOW:
    - To read rules → call get_rules with the rule_type, or get_all_rules for all
    - To update rules → call validate_rules first, then call update_rules
    - Always validate before writing — never write invalid rules
    - When updating, return the before/after comparison for confirmation

    CRITICAL OUTPUT RULE:
    - ALWAYS return the raw tool output as-is. Do NOT summarize, reformat, or narrate the results.
    - The tool returns a JSON dict — return that exact JSON to the caller.
    - Do NOT convert JSON to bullet points or prose.
    """,
    tools=rules_tools,
)

logger.info("RulesUpdateAgent created successfully with embedded tools")

root_agent = agent
