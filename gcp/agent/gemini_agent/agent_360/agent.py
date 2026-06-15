from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseConnectionParams
import os
import logging
import time
import google.auth
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [360_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing 360 Agent...")

_, project_id = google.auth.default()
logger.info(f"Authenticated with project: {project_id}")

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("model", "gemini-2.5-flash")
logger.info(f"Using model: {model}")

mcp_server_url = os.getenv("MCP_SERVER_URL", "https://mcp-agent-360-146646146609.us-central1.run.app/sse")

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

logger.info("Creating Agent_360_Degree_Final...")

root_agent = Agent(
    model=model,
    name="Agent_360_Degree_Final",
    description="Generates a comprehensive 360° financial summary report (360 Summary) for a customer (lead) based on their financial records across multiple sources such as SDI, SMA, Checking, Savings, Managed, and Fund portfolios. It extracts insights using Gemini from fund documents, analyzes trends and performance, and provides personalized financial recommendations. The final report is formatted as a well-structured PDF and uploaded to a secure Cloud Storage bucket.",
    instruction="""
    When the user provides a customer's full name (e.g., "Peter Griffin"), call the tool "agent_360_summary_with_pdf" with the name as a string parameter. This tool will analyze the customer's financial data, create a 360 summary, generate a detailed PDF report, and return the Cloud Run URL to view/download the PDF report.

    Respond with only the PDF report URL returned from the tool. Do not add extra interpretation or summary. The full insights are included inside the generated PDF.
    """,
    tools=[toolset]
)

logger.info("Agent_360_Degree_Final created successfully")
logger.info("360 Agent initialization complete")