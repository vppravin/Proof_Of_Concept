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
    format='%(asctime)s - [STOCK_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing Stock Agent...")

_, project_id = google.auth.default()
logger.info(f"Authenticated with project: {project_id}")

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("model", "gemini-2.5-flash")
logger.info(f"Using model: {model}")

# MCP Server URL from environment or default (Cloud Run URL for production)
mcp_server_url = os.getenv("MCP_SERVER_URL", "https://stocks-agent-146646146609.us-central1.run.app/sse")

logger.info(f"Connecting to MCP Server: {mcp_server_url}")
logger.info("Configuring connection with retry logic...")

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2
TIMEOUT_PER_ATTEMPT = 30

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

logger.info("Creating StockInfoAgent...")

instruction = """
You are StockInfoAgent, a financial assistant that provides stock prices, trends, and chart visualizations.

Use these tools:

---

📌 get_current_stock_price(company)
• Use when the user wants current stock prices.
• Accepts multiple companies (comma or "and" separated).
• Example: "Price of Apple and Meta"

---

📌 get_stock_trend(company, days)
• Use to check if a stock is rising or falling.
• Default to 30 days if not specified.
• Example: "Trend of Google for 15 days"

---

📌 generate_stock_chart(company, days)
• Use to generate a visual chart.
• Returns a public chart URL from Cloud Run (do not use inline images).
• Example: "Plot Apple and Microsoft for 20 days"

---

Be precise, use only the appropriate tool, and never reveal tool internals or JSON structures.
"""

# Agent
root_agent = Agent(
    model=model,
    name="Stocks_Agent",
    instruction=instruction,
    description="Agent that answers stock queries using MCP tools.",
    tools=[toolset]
)

logger.info("StockInfoAgent created successfully")
logger.info("Stock Agent initialization complete")
