import os
import logging
from dotenv import load_dotenv
from datetime import datetime
import pytz
from simple_salesforce import Salesforce
from starlette.responses import JSONResponse

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from mcp.server.sse import SseServerTransport
import uvicorn

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [SFDC_TASK_MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Establishing Salesforce connection...")
sf = Salesforce(
    username=os.environ["SF_USERNAME"],
    password=os.environ["SF_PASSWORD"],
    security_token=os.environ["SF_SECURITY_TOKEN"],
    domain='login'
)
logger.info("Salesforce connection established")

logger.info("Initializing FastMCP server...")
mcp = FastMCP("Sfdc_Task Tools")
logger.info("FastMCP server initialized")

@mcp.tool
def create_task_by_lead_name(lead_name: str, subject: str, due_date_str: str,
    status: str = "Not Started", comments: str = "") -> dict:
    """
    Creates a Salesforce Task for a given Lead based on the name.
    """
    logger.info(f"Tool invoked: create_task_by_lead_name for lead: {lead_name}")
    try:
        query = f"""
            SELECT Id, Name, Email, Company
            FROM Lead
            WHERE Name = '{lead_name}'
            LIMIT 1
        """
        logger.info(f"Querying Salesforce for lead: {lead_name}")
        result = sf.query(query)
        lead = result['records'][0] if result['records'] else None

        if not lead:
            logger.warning(f"Lead '{lead_name}' not found")
            return {"error": f"Lead with name '{lead_name}' not found."}

        logger.info(f"Lead found: {lead['Name']} (ID: {lead['Id']})")
        local_tz = pytz.timezone("Asia/Kolkata")
        naive_due_date = datetime.strptime(due_date_str.strip(), "%Y-%m-%d")
        localized_due_date = local_tz.localize(naive_due_date)
        utc_due_date = localized_due_date.astimezone(pytz.utc).date()
        logger.info(f"Due date converted: {due_date_str} (IST) -> {utc_due_date} (UTC)")

        task_data = {
            'Subject': subject,
            'WhoId': lead['Id'],
            'ActivityDate': str(utc_due_date),
            'Status': status,
            'Description': comments,
            'Priority': 'Normal'
        }

        logger.info(f"Creating task with subject: {subject}")
        result = sf.Task.create(task_data)
        if result.get('success'):
            logger.info(f"Task created successfully. Task ID: {result['id']}")
            return {
                "message": f"✅ Task created for {lead['Name']}.",
                "task_id": result['id'],
                "lead": lead
            }
        else:
            logger.error(f"Task creation failed: {result}")
            return {"error": "❌ Task creation failed.", "details": result}

    except Exception as e:
        logger.error(f"Error creating task: {e}")
        return {"error": str(e)}

sse = SseServerTransport("/sse/messages")

async def handle_sse(request: Request):
    logger.info(f"SSE connection request received from {request.client.host}")
    _server = mcp._mcp_server
    try:
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,
        ) as (reader, writer):
            logger.info("SSE connection established, running MCP server...")
            await _server.run(reader, writer, _server.create_initialization_options())
            logger.info("MCP server session completed")
    except Exception as e:
        logger.error(f"Error in SSE handler: {e}")
        raise
    return JSONResponse({"status": "ok"})

async def health_check(request: Request):
    """Health check endpoint for Cloud Run"""
    logger.debug("Health check requested")
    return JSONResponse({"status": "healthy", "service": "Salesforce Task MCP Server"})

app = Starlette(
    debug=False,
    routes=[
        Route("/", endpoint=health_check),
        Route("/health", endpoint=health_check),
        Route("/sse", endpoint=handle_sse),
        Mount("/sse/", app=sse.handle_post_message),
    ],
)

if __name__ == "__main__":
    logger.info("🚀 Starting Salesforce Task MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
