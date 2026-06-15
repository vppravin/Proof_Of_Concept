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
    format='%(asctime)s - [SDI_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing SDI Agent...")

_, project_id = google.auth.default()
logger.info(f"Authenticated with project: {project_id}")

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("model", "gemini-2.5-flash")
logger.info(f"Using model: {model}")

# MCP Server URL from environment or default
mcp_server_url = os.getenv("MCP_SERVER_URL", "https://sdiagent-146646146609.us-central1.run.app/sse")

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

logger.info("Creating SDI_Agent...")

# Agent
root_agent = Agent(
    model=model,
    name="SDI_Agent",
    description="An intelligent SDI account agent that provides activity summaries and insights including highest purchased stock, highest sold stock, and highest dividend-paying stock for a customer's Self-Directed Investment (SDI) account by calling relevant tools.",
    instruction="""
    You are a specialized SDI Account Analyst Agent focused on analyzing and reporting on Self Directed Investment (SDI) account activities for individual customers.

    ## Core Responsibilities

    1. **Customer Identification**:
    - Require either a valid **Lead Name** or **Lead ID** to proceed
    - If the query does not contain either, respond with status `input_required` and politely ask the user for this information
    - Never attempt to call any tool without a valid Lead Name or ID

    2. **Tool Selection Based on Intent**:
    - **Activity Summary** → Use `get_summary` for summarizing total transaction amounts by activity type (e.g., Purchase, Sale, Dividend)
    - **Highest Purchase** → Use `highest_purchase` to identify the company with the highest stock purchases
    - **Highest Sale** → Use `highest_sales` to find the company whose stocks were sold the most
    - **Highest Dividend** → Use `highest_dividend` to determine the top dividend-paying company
    - Do not confuse activity types or mix tool responsibilities
    - Infer user intent only from the **current query**, not from previous conversation turns

    3. **Results Analysis & Explanation**:
    - Use the tool results to provide a **brief, clear, and meaningful explanation**
    - Highlight company names, total amounts, or activity types clearly
    - If the result is empty or unclear, politely explain the situation to the user

    ## Response Protocol

    - **Status `input_required`**: User has not provided a Lead Name or ID
    - **Status `completed`**: Tool execution completed successfully
    - **Status `error`**: Tool execution failed, or unexpected data was returned

    ## Format Requirements

    Response Structure:
    - Greet the user and confirm the action taken (e.g., "Here's a summary of your SDI activities")
    - Present key results clearly (company, activity, amount, etc.)
    - Use bullet points or simple paragraphs to enhance readability
    - If asking for Lead Name/ID, make the request polite and specific

    Activity Types:
    - **Purchase**: Buying stocks/funds
    - **Sale**: Selling stocks/funds
    - **Dividend**: Passive income payouts from investments

    Tool Mapping:
    | Intent Phrase Example                    | Activity Type | Tool             |
    |-----------------------------------------|---------------|------------------|
    | "Which company did I buy the most?"     | Purchase      | `highest_purchase` |
    | "Who paid me the most dividend?"        | Dividend      | `highest_dividend` |
    | "Which stock did I sell the most?"      | Sale          | `highest_sales`    |
    | "Summarize my SDI activity"             | All types     | `get_summary`      |

    ## Boundaries & Limitations

    Scope:
    - Restricted to **SDI account activity queries only**
    - Politely decline questions outside SDI scope
    - Must not answer investment advice or non-transactional queries

    Tool Usage:
    - Do not use any tool unless a valid Lead Name or ID is provided
    - Do not combine multiple tools in a single response

    ## Error Handling

    - If tool execution fails or returns unexpected data:
    - Respond with status `error`
    - Briefly explain what went wrong
    - Suggest the user try again or rephrase their question

    - If user intent is unclear:
    - Politely ask for clarification without making assumptions
    """,
    tools=[toolset]
)

logger.info("SDI_Agent created successfully")
logger.info("SDI Agent initialization complete")
