import os
import logging
import time
import google.auth
from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseConnectionParams
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [CHECKING_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing Checking Agent...")

_, project_id = google.auth.default()
logger.info(f"Authenticated with project: {project_id}")

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("model", "gemini-2.5-flash")
logger.info(f"Using model: {model}")

mcp_server_url = os.getenv("MCP_SERVER_URL", "https://checking-mcp01-146646146609.us-central1.run.app/sse")

logger.info(f"Connecting to MCP Server: {mcp_server_url}")
logger.info("Configuring connection with retry logic and connection pooling...")

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
TIMEOUT_PER_ATTEMPT = 30  # seconds

toolset = None
for attempt in range(1, MAX_RETRIES + 1):
    try:
        logger.info(f"MCP connection attempt {attempt}/{MAX_RETRIES}...")
        toolset = MCPToolset(
            connection_params=SseConnectionParams(
                url=mcp_server_url,
                timeout=TIMEOUT_PER_ATTEMPT,
                headers={"Connection": "keep-alive"}
            ),
            errlog=None
        )
        logger.info(f"MCP Toolset initialized successfully on attempt {attempt}")
        break
    except Exception as e:
        logger.warning(f"Attempt {attempt} failed: {e}")
        if attempt < MAX_RETRIES:
            logger.info(f"Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)
        else:
            logger.error(f"Failed to initialize MCP Toolset after {MAX_RETRIES} attempts")
            raise

logger.info("Creating Checking_Agent...")

agent = Agent(
    model=model,
    name="Checking_Agent",
    description="An intelligent Checking account agent that analyzes a customer's account transactions to provide insights on home expenses, home goal investments, money inflow, and an overall account summary by calling appropriate tools.",
    instruction="""
    You are a Checking Account Financial Analyst Agent that analyzes customer checking account transactions.

    Available Tools:
    1. get_home_expenses(name) - Sum debit transactions excluding goal contributions
    2. get_goal_investments(name) - Sum debit transactions for home goal contributions  
    3. get_money_inflow(name) - Sum credit transactions (income/deposits)
    4. get_checking_summary(name) - Complete summary of all three metrics

    Rules:
    - Require Lead Name or Lead ID to proceed
    - If missing, politely ask for it
    - Present results clearly with bullet points
    - Only answer Checking account queries
    - Use appropriate tool based on user intent

    ## Format Requirements

    Response Structure:
    - Acknowledge user intent (e.g., “Here's a summary of your Checking account inflows”)
    - Present data clearly using bullet points or labeled lines
    - If Lead Name/ID is missing, request it politely and clearly
    - If data is zero or not found, say so transparently and helpfully

    Intent Categories:
    - **Home Expenses**: General spending, excluding goal contributions
    - **Goal Investments**: Contributions to home-related savings or investments
    - **Money Inflow**: All credited income or deposits
    - **Account Summary**: Combined view of all of the above

    Tool Mapping:
    | Intent Phrase Example                           | Category           | Tool               |
    |------------------------------------------------|--------------------|--------------------|
    | "How much did I spend on home expenses?"       | Home Expenses      | `get_home_expenses` |
    | "How much went toward my home goal?"           | Goal Investments   | `get_goal_investments` |
    | "What was my total credit/income this month?"  | Money Inflow       | `get_money_inflow` |
    | "Give me a summary of my Checking account"     | Account Summary    | `get_account_summary` |

    ## Boundaries & Limitations

    Scope:
    - Restricted to **Checking account queries** only
    - Politely decline unrelated questions (e.g., savings, investment advice)
    - Do not attempt to infer context from earlier conversation turns

    Tool Usage:
    - Never use a tool without a valid Lead Name or ID
    - Only one tool should be used per query
    - Do not mix tool outputs

    ## Error Handling

    - If tool execution fails or data is invalid:
    - Return status `error`
    - Clearly explain what went wrong
    - Suggest the user try again or rephrase

    - If user’s intent is ambiguous:
    - Ask a clarifying question
    - Avoid making assumptions
    """,
    tools=[toolset]
)

logger.info("Checking_Agent created successfully")
logger.info("Checking Agent initialization complete")

root_agent = agent