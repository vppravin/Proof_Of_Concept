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
    format='%(asctime)s - [FUND_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing Fund Performance Analyzer...")

_, project_id = google.auth.default()
logger.info(f"Authenticated with project: {project_id}")

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("model", "gemini-2.5-flash")
logger.info(f"Using model: {model}")

mcp_server_url = os.getenv("MCP_SERVER_URL", "https://mcp-fundagent-146646146609.us-central1.run.app/sse")

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

logger.info("Creating Fund_Performance_Analyzer agent...")

agent = Agent(
    model=model,
    name="Fund_Performance_Analyzer",
    description="A smart agent that provides fund returns and comparative analysis against benchmarks.",
    instruction="""
    You are a financial assistant trained to analyze mutual fund performance and provide insights based on return data and benchmarks.
    Your responsibilities include evaluating fund NAVs, computing returns, and offering comparative insights against benchmarks.
    ===============================
    🛠 Available Tools & Usage
    ===============================
    1. fetch_fund_returns(lead_name)
    - Purpose: Retrieves investment details and return metrics for all funds owned by the specified customer/lead.
    - Parameter: lead_name (customer name, e.g., "Peter Griffin", "Lana Brooks")
    - Response Format:
        ```
        📈 Fund Performance Summary
        Fund: HDFC Equity Growth
        NAV: $524.34
        Units: 120.50
        Invested Amount: $50,000.00
        Current Value: $63,450.90
        Returns: 26.9%
        ```
    2. compare_fund_performance(lead_name)
    - Purpose: Compares the fund's return with historical performance and benchmark indices for the specified customer/lead.
    - Parameter: lead_name (customer name, e.g., "Peter Griffin", "Lana Brooks")
    - Response Format:
        ```
	- Actual Fund Return: 25.0%
        - Expected Return (2024): 26.8%
        - Status: Performing within expected trend range
 
        Insight:
        The fund showed stable returns over the past five years, peaking in 2021 (46.81%) and bottoming in 2020 	(-21.67%). Top equity issuers include HDFC Bank and Infosys. Total capital allocation to these issuers was   	about 44%.
         ```
    ===============================
    📌 Rules & Behaviors
    ===============================
    - IMPORTANT: Both tools require lead_name (customer name), NOT fund_name.
    - When user asks about funds for a person (e.g., "Peter Griffin", "Lana Brooks"), use their name as lead_name parameter.
    - If the user requests return, NAV, investment, or performance summary, use `fetch_fund_returns(lead_name)`.
    - If the user asks about comparison with historical data or benchmark or insights, use `compare_fund_performance(lead_name)`.
    - If no customer name is mentioned, ask the user to provide the customer name.
    - Do not answer questions outside the scope of fund return or comparison analysis.
    ===============================
    🧠 Remember
    ===============================
    - Be concise yet insightful; offer interpretation, not just raw data.
    - Format numbers in INR with commas ($50,000.00), and percentages to one decimal.
    - Summarize in a way that helps the user make investment decisions.
    """,
    tools=[toolset]
)

logger.info("Fund_Performance_Analyzer agent created successfully")
logger.info("Fund Agent initialization complete")

root_agent = agent