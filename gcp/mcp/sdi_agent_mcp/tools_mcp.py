from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.cloud import bigquery
from dotenv import load_dotenv
import os
import logging
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
    format='%(asctime)s - [MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

table = "gbu-demo-playground.Wealth_Management.SDI"

client = bigquery.Client()
logger.info("Initializing FastMCP server...")
mcp = FastMCP("SDI tools")
logger.info("FastMCP server initialized")

# Tool 1: Summary
@mcp.tool()
def get_summary(name: str) -> dict:
    logger.info(f"Tool invoked: get_summary for name={name}")
    results = {}

    # 1. Total Amount by Activity Type
    query1 = f"""
        SELECT Activity, SUM(Amount) AS Total_Amount
        FROM {table}
        WHERE lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}')
        GROUP BY Activity
    """
    result1 = client.query(query1).result()
    activity_totals = [{"Activity": row.Activity, "Total_Amount": row.Total_Amount} for row in result1]
    results['activity_totals'] = activity_totals
    logger.info(f"Retrieved {len(activity_totals)} activity totals")

    # 2. Top 5 Purchases, Sales, Dividends
    query2 = f"""
        SELECT * FROM (
        SELECT 'Top_Purchases' AS Category, Description, SUM(Amount) AS Total_Amount
        FROM {table}
        WHERE (lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}'))
          AND lower(Activity) = 'purchase'
        GROUP BY Description
        ORDER BY Total_Amount DESC
        LIMIT 5
        )
        
        UNION ALL

        SELECT * FROM (
        SELECT 'Top_Sales' AS Category, Description, SUM(Amount) AS Total_Amount
        FROM {table}
        WHERE (lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}'))
          AND lower(Activity) = 'sale'
        GROUP BY Description
        ORDER BY Total_Amount DESC
        LIMIT 5
        )
        
        UNION ALL

        SELECT * FROM (
        SELECT 'Top_Dividends' AS Category, Description, SUM(Amount) AS Total_Amount
        FROM {table}
        WHERE (lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}'))
          AND lower(Activity) = 'dividend'
        GROUP BY Description
        ORDER BY Total_Amount DESC
        LIMIT 5
        )
    """
    result2 = client.query(query2).result()
    top_stocks = [{"Category": row.Category, "Description": row.Description, "Total_Amount": row.Total_Amount} for row in result2]
    results['top_stocks_summary'] = top_stocks
    logger.info(f"Retrieved {len(top_stocks)} top stocks")

    return results


# Tool 2: Highest Purchased Stock
@mcp.tool()
def highest_purchase(name: str) -> dict:
    logger.info(f"Tool invoked: highest_purchase for name={name}")
    results = {}
    query2 = f"""
        SELECT Description, SUM(Amount) AS Total_Purchase
        FROM {table}
        WHERE Activity = 'Purchase' AND (lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}'))
        GROUP BY Description
        ORDER BY Total_Purchase DESC
        LIMIT 1
    """
    result = client.query(query2).result()
    purchase_top = [ { "Company": row.Description, "Total_Purchase": row.Total_Purchase } for row in result ]
    results['top_purchase_company'] = purchase_top[0] if purchase_top else {}
    return results


# Tool 3: Highest Dividend Providing Stock
@mcp.tool()
def highest_dividend(name: str) -> dict:
    logger.info(f"Tool invoked: highest_dividend for name={name}")
    results = {}
    query3 = f"""
        SELECT Description, SUM(Amount) AS Total_Dividend
        FROM {table}
        WHERE Activity = 'Dividend' AND (lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}'))
        GROUP BY Description
        ORDER BY Total_Dividend DESC
        LIMIT 1
    """
    result = client.query(query3).result()
    dividend_top = [ { "Company": row.Description, "Total_Dividend": row.Total_Dividend } for row in result ]
    results['top_dividend_company'] = dividend_top[0] if dividend_top else {}
    return results


# Tool 4: Highest Sold Stock
@mcp.tool()
def highest_sales(name: str) -> dict:
    logger.info(f"Tool invoked: highest_sales for name={name}")
    results = {}
    query4 = f"""
        SELECT Description, SUM(Amount) AS Total_Sale
        FROM {table}
        WHERE Activity = 'Sale' AND (lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}'))
        GROUP BY Description
        ORDER BY Total_Sale DESC
        LIMIT 1
    """
    result = client.query(query4).result()
    sale_top = [ { "Company": row.Description, "Total_Sale": row.Total_Sale } for row in result ]
    results['top_sale_company'] = sale_top[0] if sale_top else {}
    return results

# --- MCP App Setup ---
sse = SseServerTransport("/messages/")

async def handle_sse(request: Request) -> None:
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

app = Starlette(
    debug=True,
    routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ],
)

if __name__ == "__main__":
    logger.info("🚀 Starting SDI MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")