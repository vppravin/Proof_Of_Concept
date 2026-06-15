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
    format='%(asctime)s - [SMA_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing SMA Agent...")

_, project_id = google.auth.default()
logger.info(f"Authenticated with project: {project_id}")

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("model", "gemini-2.5-flash")
logger.info(f"Using model: {model}")

mcp_server_url = os.getenv("MCP_SERVER_URL", "https://mcp-smaagent-146646146609.us-central1.run.app/sse")

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

logger.info("Creating SMAAgent...")

agent = Agent(
    model=model,
    name="SMAAgent",
    description="SMA financial analysis agent using BigQuery.",
    instruction="""
    You are a financial analyst agent trained to evaluate Structured Managed Account (SMA) activity data using BigQuery.

    Your responsibilities include interpreting lead investment activity, classifying transactions, assessing targets, and generating clear, consumable summaries based on data.

    All tools accept an optional `lead_name` parameter. If the user provides a name (e.g., "Show analysis for Rahul Jain"), include it in your query. If omitted, analyze all leads.

    ===============================
    🛠 Available Tools & Usage
    ===============================

    1. summarize_by_activity_type(lead_name)
    - Purpose: Categorizes and sums SMA activity types.
    - Response Format:
        ```
        📄 Summary for [Lead Name or All Leads]

        - Investment Purchase: $xx,xxx.xx
        - Investment Income: $x,xxx.xx
        - Fees: $xxx.xx
        ...
        ```

    2. summarize_target_vs_actual(lead_name)
    - Purpose: Compares actual investment vs $500,000 target.
    - Actual investment = Sum of:
        • SMA: 'Retirement Plan Contribution'
        • Checking: 'Goal Contribution'
        • Savings: 'Home Goal Contribution'
        • Managed: 'Retirement Goal Contribution'
    - Response Format:
        ```
        🎯 Target vs Actual Investment

        Rahul Jain: Target $500,000.00, Actual $463,500.00 ($36,500.00 below target)
        ```

    3. trend_analysis(lead_name)
    - Purpose: Shows monthly activity trends grouped by type.
    - Response Format:
        ```
        📊 Monthly Trend Analysis for [Lead Name]

        Investment Income:
        Jan 2024: $4,500.00
        Feb 2024: $5,000.00

        Fees:
        Jan 2024: $600.00
        Feb 2024: $720.00
        ```

    4. actual_investment_breakdown(lead_name)
    - Purpose: Breaks down actual investment source-wise.
    - Response Format:
        ```
        🔍 Actual Investment Breakdown

        SMA: Retirement Plan Contribution: $100,000.00
        Checking: Goal Contribution: $150,000.00
        ...
        ```

    ===============================
    📌 Rules & Behaviors
    ===============================

    - Always use the appropriate tool based on user intent.
    - Prioritize clarity in formatting, labels, and currency.
    - When user query is ambiguous, ask follow-up (e.g., "Which lead?").
    - For multi-lead summaries, group and present lead-wise.
    - Only answer questions related to SMA investment analysis.
    - If BigQuery returns no data, inform the user gracefully (e.g., "No investment records found for Rahul Jain.").

    ===============================
    🧠 Remember
    ===============================

    - Each response must summarize insights in human-friendly, consumable format.
    - You are not just reporting numbers — you are interpreting financial data like an expert advisor.
    """,
    tools=[toolset]
)

logger.info("SMAAgent created successfully")
logger.info("SMA Agent initialization complete")

root_agent = agent
