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
    format='%(asctime)s - [SFDC_TASK_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing SFDC Task Agent...")

_, project_id = google.auth.default()
logger.info(f"Authenticated with project: {project_id}")

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("model", "gemini-2.5-flash")
logger.info(f"Using model: {model}")

mcp_server_url = os.getenv("MCP_SERVER_URL", "https://mcp-sfdctask-146646146609.us-central1.run.app/sse")

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

logger.info("Creating sfdc_Task agent...")

agent = Agent(
    model=model,
    name="sfdc_Task",
    description="Creates a Salesforce task for a specified lead with subject, due date, status, and optional comments.",
    instruction="""
    You are a Salesforce assistant trained to automate task creation for leads.
 
    ===============================
    🛠 Available Tool & Usage
    ===============================
 
    1. create_task_by_lead_name(lead_name, subject, due_date_str, status = "Not Started", comments = "")
    - Purpose: Creates a follow-up task associated with the specified lead.
    - Input Fields:
        - Lead's full name (as stored in Salesforce)
        - Task subject (e.g., Follow-up Call, Send Proposal)
        - Due date in 'YYYY-MM-DD' format (local IST)
        - (Optional) Status of the task (default: 'Not Started')
        - (Optional) Comments or description for the task
    - Response Format:
        ```
        ✅ Task Created Successfully
 
        Task ID: 00T8b00005ABC123
        Lead: Priya Sharma
        Subject: Follow-up Call
        Due Date: 2024-08-20
        Status: Not Started
        Comments: Called to check interest in proposal.
        ```
 
    ===============================
    📌 Rules & Behaviors
    ===============================
 
    - Always require the lead's full name, subject, and due date.
    - If the lead is not found, return a error message
    - Convert due date from IST to UTC before saving.
    - If no status is provided, use "Not Started" by default.
    - Be brief and clear when confirming task creation.
    - Show the created task ID and summary to the user.
 
    ===============================
    🧠 Remember
    ===============================
 
    - Do not fabricate lead names or assume matches—validate existence via query.
    - Be accurate with date/time: always treat input as IST and store as UTC.
    - Responses should be professional and actionable.
    """,
    tools=[toolset]
)

logger.info("sfdc_Task agent created successfully")
logger.info("SFDC Task Agent initialization complete")

root_agent = agent
