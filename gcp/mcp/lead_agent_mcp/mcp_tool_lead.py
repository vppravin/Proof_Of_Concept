import os
import logging
from dotenv import load_dotenv
from simple_salesforce import Salesforce
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import JSONResponse
from mcp.server.sse import SseServerTransport
import uvicorn

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Salesforce connection from env vars
def get_salesforce_connection():
    logger.info("Establishing Salesforce connection...")
    try:
        sf = Salesforce(
            username=os.environ["SF_USERNAME"],
            password=os.environ["SF_PASSWORD"],
            security_token=os.environ["SF_SECURITY_TOKEN"],
            domain='login'
        )
        logger.info("Salesforce connection established successfully")
        return sf
    except Exception as e:
        logger.error(f"Failed to connect to Salesforce: {e}")
        raise

# Initialize MCP
logger.info("Initializing FastMCP server...")
mcp = FastMCP("Salesforce_lead_Tools")
logger.info("FastMCP server initialized")

@mcp.tool
def get_salesforce_leads() -> dict:
    """
    Returns the top 'Working' leads from 'Website' source with Annual Revenue >= 250K.
    """
    logger.info("Tool invoked: get_salesforce_leads")
    try:
        sf = get_salesforce_connection()
        query = """
            SELECT External_ID__c, Name, Status, AnnualRevenue, LeadSource, Address, Email
            FROM Lead
            WHERE Status = 'Working' AND LeadSource = 'Website' AND AnnualRevenue >= 250000
            ORDER BY AnnualRevenue DESC
        """
        logger.info(f"Executing Salesforce query: {query.strip()}")
        results = sf.query(query)
        record_count = len(results.get("records", []))
        logger.info(f"Query successful. Retrieved {record_count} leads")
        return {"records": results.get("records", [])}
    except Exception as e:
        logger.error(f"Error fetching Salesforce leads: {e}")
        return {"error": str(e)}

# SSE + Starlette app config
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

async def health_check(request: Request):
    """Health check endpoint for Cloud Run"""
    logger.debug("Health check requested")
    return JSONResponse({"status": "healthy", "service": "Salesforce MCP Server"})

# Starlette app
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
    logger.info("🚀 Starting Salesforce MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
