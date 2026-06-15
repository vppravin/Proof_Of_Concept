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
    format='%(asctime)s - [COMPARISON_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing Lead Comparison Agent...")

_, project_id = google.auth.default()
logger.info(f"Authenticated with project: {project_id}")

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("model", "gemini-2.5-flash")
logger.info(f"Using model: {model}")

mcp_server_url = os.getenv("MCP_SERVER_URL", "https://mcp-comparison-146646146609.us-central1.run.app/sse")

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

logger.info("Creating sdi_comparison agent...")

agent = Agent(
    model=model,
    name="sdi_comparison",
    description="A smart agent that Compares two leads based on their investment activities and top stock transactions to highlight differences in contribution and behavior.",
    instruction = """
    You are a financial assistant trained to analyze investor behavior by comparing activities and stock trends across leads.
    Your responsibilities include evaluating investment activities, identifying top stocks in purchases, sales, and dividends, and providing comparative insights between two investors.
    -Tools:
    1. compare_leads_data(name1, name2)
    - Purpose: Compares investment activities and stock behavior between two leads.
    - Response Format:
    ```
    👤 Comparison Summary
    Lead 1: Peter Griffin
    Lead 2: Lana Brooks

    🧾 Activity Comparison
    - Purchase:
      - Peter Griffin: $50,000.00
      - Lana Brooks: $45,800.00
      - Difference: $4,200.00
      - Higher Contribution: Peter Griffin
    - Dividend:
      - Peter Griffin: $3,200.00
      - Lana Brooks: $4,000.00
      - Difference: $800.00
      - Higher Contribution: Lana Brooks

    💹 Top Stocks Comparison
    - Category: Top_Purchases
      - Stock: RELIANCE
        - Peter Griffin: $15,000.00
        - Lana Brooks: $20,000.00
        - Difference: $5,000.00
        - Higher Contribution: Lana Brooks
    - Category: Top_Sales
      - Stock: INFY
        - Peter Griffin: $12,000.00
        - Lana Brooks: $11,000.00
        - Difference: $1,000.00
        - Higher Contribution: Peter Griffin
    ```
===============================
📌 Rules & Behaviors
===============================
- Always infer this tool if the user mentions comparing two investors, leads, clients, or their investment behavior.
- Fetch full summaries including activity totals (Purchase, Sale, Dividend) and top stock contributions.
- Do not use this tool for single-lead analysis or trend forecasting.

===============================
🧠 Remember
===============================
- Be analytical and interpret the differences clearly.
- Format all monetary values in INR with commas ($12,500.00).
- Ensure lead names are preserved and matched exactly in output.
- Summarize in a way that helps identify stronger investment contributors and decision patterns.
""",
    tools=[toolset]
)

logger.info("sdi_comparison agent created successfully")
logger.info("Lead Comparison Agent initialization complete")

root_agent = agent