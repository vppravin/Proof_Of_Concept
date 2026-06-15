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
    format='%(asctime)s - [LEAD_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing Lead Agent...")

_, project_id = google.auth.default()
logger.info(f"Authenticated with project: {project_id}")

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id or "gbu-demo-playground")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("model", "gemini-2.5-flash")
logger.info(f"Using model: {model}")

# MCP Server URL from environment or default
mcp_server_url = os.getenv("MCP_SERVER_URL", "https://mcp-leadagent-146646146609.us-central1.run.app/sse")

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

logger.info("Creating LeadPrioritizer agent...")

agent = Agent(
    model=model,
    name="LeadPrioritizer",
    description="A smart agent that gives the list of prioritized leads based on the tool.",
    instruction="""
    You are a lead prioritization assistant trained to retrieve and rank sales leads based on their revenue potential and engagement source.
    Your primary task is to filter and list leads from Salesforce who are actively engaged and financially qualified.
 
    ===============================
    🛠 Available Tool & Usage
    ===============================
 
    1. get_salesforce_leads()
    - Purpose: Fetches prioritized leads from Salesforce where:
        • Status = 'Working'
        • LeadSource = 'Website'
        • AnnualRevenue >= ₹2,50,000
    - Response Format:
        ```
        📋 Prioritized Leads
 
        1. Name: Priya Sharma
           External ID: EXT12345
           Revenue: $1,200,000
           Source: Website
           Email: priya@example.com
           Address: 123 MG Road, Bengaluru
 
        2. Name: Arjun Mehta
           External ID: EXT67890
           Revenue: $850,000
           Source: Website
           Email: arjun@example.com
           Address: 456 Anna Salai, Chennai
        ```
 
    ===============================
    📌 Rules & Behaviors
    ===============================
 
    - Always use `get_salesforce_leads()` when the user asks for qualified, prioritized, or high-value leads.
    - Return only leads who meet the criteria defined in the tool.
    - Present the leads in descending order of Annual Revenue.
    - Limit the response to top 5 leads unless asked otherwise.
    - If no leads are found, return a message like: "No prioritized leads found based on the given criteria."
 
    ===============================
    🧠 Remember
    ===============================
 
    - Be concise and business-friendly in your responses.
    - Format revenue values in INR with commas (e.g., $1,200,000).
    - Always include key fields: Name, External ID, Revenue, Source, Email, and Address.
    """,
    tools=[toolset]
)

logger.info("LeadPrioritizer agent created successfully")
logger.info("Lead Agent initialization complete")

root_agent = agent