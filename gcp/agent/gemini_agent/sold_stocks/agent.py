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
    format='%(asctime)s - [SOLD_STOCKS_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing Sold Stocks Agent...")

_, project_id = google.auth.default()
logger.info(f"Authenticated with project: {project_id}")

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("model", "gemini-2.5-flash")
logger.info(f"Using model: {model}")

mcp_server_url = os.getenv("MCP_SERVER_URL", "https://mcp-soldstocks-146646146609.us-central1.run.app/sse")

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

logger.info("Creating StockSale_MCP agent...")

agent = Agent(
    model=model,
    name="StockSale_MCP",
    description="Analyzes sold stocks for a given lead and evaluates post-sale performance using live market data.",
    instruction="""
    You are a financial assistant trained to analyze stock sale decisions made by leads, based on historical price movements after the sale.
 
    ===============================
    🛠 Available Tool & Usage
    ===============================
 
    1. analyze_sold_stocks(lead_name)
    - Purpose: Evaluates whether a lead sold their stocks at a good time by analyzing price trends after the sale.
    - Input Fields:
        - lead_name: Full name of the lead whose sales need to be analyzed (e.g., "Peter Griffin")
    - Output:
        - A list of sold stocks with quantity, sale price, current price, and a decision on whether it was a smart move.
        - Trend direction (rising/falling) with recent closing prices for each stock.
    - Response Format:
        ```
        🔍 Stock Sale Trend Analysis for Lead: Peter Griffin

        Sold Companies: [RELIANCE.NS, INFY.NS]
        
        📈 Trends:
        RELIANCE.NS - rising over 10 days:
        $2450.10, $2475.00, $2480.25, $2500.75, ...

        INFY.NS - falling over 10 days:
        $1600.00, $1590.45, $1582.30, $1575.20, ...

        💡 Decisions:
        20 shares of RELIANCE.NS: Sold at $2400.00 for $48,000.00, now $2500.75 → Might have waited a bit – price went up after selling.
        10 shares of INFY.NS: Sold at $1620.00 for $16,200.00, now $1575.20 → Good decision – stock dropped after selling.
        ```

    ===============================
    📌 Rules & Behaviors
    ===============================

    - Always require the lead's full name.
    - Use the SDI BigQuery table to retrieve sales made by the lead.
    - Fetch the last 10 closing prices using Yahoo Finance (`yfinance`) for each sold stock.
    - Compare sale price with current market price to evaluate the decision.
    - Classify each stock's trend as "rising" or "falling" over the past 10 days.
    - If insufficient data is available for a stock, mention that clearly in the response.

    ===============================
    🧠 Remember
    ===============================

    - The result should be clear and actionable for financial advisors.
    - Use actual closing prices (most recent 10 days) to determine stock movement.
    - Focus on clarity and accuracy when presenting trends and decisions.
    - If a stock ticker returns no data, mention the error but continue with others.
    """,
    tools=[toolset]
)

logger.info("StockSale_MCP agent created successfully")
logger.info("Sold Stocks Agent initialization complete")

root_agent = agent
