import os
import logging
from dotenv import load_dotenv
from starlette.responses import JSONResponse

from fastmcp import FastMCP
from google.cloud import bigquery

from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from mcp.server.sse import SseServerTransport
import uvicorn

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
CHECKING_TABLE = os.getenv("CHECKING_TABLE", "gbu-demo-playground.Wealth_Management.Checking")
logger.info(f"Initializing BigQuery client for project: {PROJECT_ID}")
client = bigquery.Client(project=PROJECT_ID)

logger.info("Initializing FastMCP server...")
mcp = FastMCP("Checking Account Analysis Tools")
logger.info("FastMCP server initialized")

@mcp.tool
def get_home_expenses(name: str) -> dict:
    """Get home expenses excluding goal contributions."""
    logger.info(f"Tool invoked: get_home_expenses for name={name}")
    query = f"""
    SELECT SUM(Debit) AS Home_Expenses
    FROM `{CHECKING_TABLE}`
    WHERE Description NOT IN (
        'Transfer-SMA- Goal Contribution',
        'Transfer-Managed- Goal Contribution',
        'Transfer-Savings- Goal Contribution'
    ) AND (LOWER(Lead_Name) = LOWER('{name}') OR LOWER(Lead_ID) = LOWER('{name}'))
    """
    try:
        logger.info(f"Executing BigQuery query for home expenses")
        result = client.query(query).result()
        home_expenses = [{"Total_Debit": row.Home_Expenses} for row in result]
        logger.info(f"Query successful. Retrieved home expenses data")
        return {"Home_Expenses": home_expenses}
    except Exception as e:
        logger.error(f"Error getting home expenses: {e}")
        return {"error": f"Error getting home expenses: {str(e)}"}

@mcp.tool
def get_goal_investments(name: str) -> dict:
    """Get home goal investment contributions."""
    logger.info(f"Tool invoked: get_goal_investments for name={name}")
    query = f"""
    SELECT SUM(Debit) AS Home_Goal_Investments
    FROM `{CHECKING_TABLE}`
    WHERE Description IN (
        'Transfer-SMA- Goal Contribution',
        'Transfer-Managed- Goal Contribution',
        'Transfer-Savings- Goal Contribution'
    ) AND (LOWER(Lead_Name) = LOWER('{name}') OR LOWER(Lead_ID) = LOWER('{name}'))
    """
    try:
        logger.info(f"Executing BigQuery query for goal investments")
        result = client.query(query).result()
        home_goal_investment = [{"Total_Debit": row.Home_Goal_Investments} for row in result]
        logger.info(f"Query successful. Retrieved goal investments data")
        return {"Home_Goal_Investments": home_goal_investment}
    except Exception as e:
        logger.error(f"Error getting goal investments: {e}")
        return {"error": f"Error getting goal investments: {str(e)}"}

@mcp.tool
def get_money_inflow(name: str) -> dict:
    """Get total credit inflow."""
    logger.info(f"Tool invoked: get_money_inflow for name={name}")
    query = f"""
    SELECT SUM(Credit) AS Credit_Inflow
    FROM `{CHECKING_TABLE}`
    WHERE LOWER(Lead_Name) = LOWER('{name}') OR LOWER(Lead_ID) = LOWER('{name}')
    """
    try:
        logger.info(f"Executing BigQuery query for money inflow")
        result = client.query(query).result()
        money_inflow = [{"Total_Credit": row.Credit_Inflow} for row in result]
        logger.info(f"Query successful. Retrieved money inflow data")
        return {"Credit_Inflow": money_inflow}
    except Exception as e:
        logger.error(f"Error getting money inflow: {e}")
        return {"error": f"Error getting money inflow: {str(e)}"}

@mcp.tool
def get_checking_summary(name: str) -> dict:
    """Get complete checking account summary."""
    logger.info(f"Tool invoked: get_checking_summary for name={name}")
    query = f"""
    SELECT
        SUM(CASE 
            WHEN Description NOT IN (
                'Transfer-SMA- Goal Contribution',
                'Transfer-Managed- Goal Contribution',
                'Transfer-Savings- Goal Contribution'
            )
            THEN Debit ELSE 0 END) AS Home_Expenses,
        SUM(CASE 
            WHEN Description IN (
                'Transfer-SMA- Goal Contribution',
                'Transfer-Managed- Goal Contribution',
                'Transfer-Savings- Goal Contribution'
            )
            THEN Debit ELSE 0 END) AS Home_Goal_Investments,
        SUM(CASE 
            WHEN Credit IS NOT NULL THEN Credit ELSE 0 END) AS Credit_Inflow
    FROM `{CHECKING_TABLE}`
    WHERE LOWER(Lead_Name) = LOWER('{name}') OR LOWER(Lead_ID) = LOWER('{name}')
    """
    try:
        logger.info(f"Executing BigQuery query for checking summary")
        result = client.query(query).result()
        summary = [{"Home_Expenses": row.Home_Expenses, "Home_Goal_Investments": row.Home_Goal_Investments, "Credit_Inflow": row.Credit_Inflow} for row in result]
        logger.info(f"Query successful. Retrieved checking summary data")
        return {"Summary": summary}
    except Exception as e:
        logger.error(f"Error getting checking summary: {e}")
        return {"error": f"Error getting checking summary: {str(e)}"}

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
    return JSONResponse({"status": "healthy", "service": "Checking Account Analysis MCP Server"})

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
    logger.info("🚀 Starting Checking Account Analysis MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
