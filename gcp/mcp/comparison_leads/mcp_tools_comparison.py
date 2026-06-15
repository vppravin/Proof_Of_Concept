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
    format='%(asctime)s - [COMPARISON_MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
SDI_TABLE = os.getenv("SDI_TABLE", "gbu-demo-playground.Wealth_Management.SDI")
logger.info(f"Initializing BigQuery client for project: {PROJECT_ID}")
client = bigquery.Client(project=PROJECT_ID)

logger.info("Initializing FastMCP server...")
mcp = FastMCP("Lead Stock Comparison Tools")
logger.info("FastMCP server initialized")

@mcp.tool
def compare_leads_data(name1: str, name2: str) -> dict:
    logger.info(f"Tool invoked: compare_leads_data for {name1} vs {name2}")
    
    def fetch_lead_data(name: str) -> dict:
        logger.info(f"Fetching data for lead: {name}")
        query1 = f"""
            SELECT Activity, SUM(Amount) AS Total_Amount
            FROM `{SDI_TABLE}`
            WHERE LOWER(Lead_Name) = LOWER('{name}') OR LOWER(Lead_ID) = LOWER('{name}')
            GROUP BY Activity
        """
        result1 = client.query(query1).result()
        activity_totals = [
            {"Activity": row.Activity, "Total_Amount": float(row.Total_Amount or 0)}
            for row in result1
        ]
        logger.info(f"Fetched {len(activity_totals)} activity types for {name}")

        query2 = f"""
            SELECT * FROM (
            SELECT 'Top_Purchases' AS Category, Description, SUM(Amount) AS Total_Amount
            FROM `{SDI_TABLE}`
            WHERE (LOWER(Lead_Name) = LOWER('{name}') OR LOWER(Lead_ID) = LOWER('{name}'))
              AND LOWER(Activity) = 'purchase'
            GROUP BY Description
            ORDER BY Total_Amount DESC
            LIMIT 5
            )

            UNION ALL

            SELECT * FROM (
            SELECT 'Top_Sales' AS Category, Description, SUM(Amount) AS Total_Amount
            FROM `{SDI_TABLE}`
            WHERE (LOWER(Lead_Name) = LOWER('{name}') OR LOWER(Lead_ID) = LOWER('{name}'))
              AND LOWER(Activity) = 'sale'
            GROUP BY Description
            ORDER BY Total_Amount DESC
            LIMIT 5
            )

            UNION ALL

            SELECT * FROM (
            SELECT 'Top_Dividends' AS Category, Description, SUM(Amount) AS Total_Amount
            FROM `{SDI_TABLE}`
            WHERE (LOWER(Lead_Name) = LOWER('{name}') OR LOWER(Lead_ID) = LOWER('{name}'))
              AND LOWER(Activity) = 'dividend'
            GROUP BY Description
            ORDER BY Total_Amount DESC
            LIMIT 5
            )
        """
        result2 = client.query(query2).result()
        top_stocks = [
            {"Category": row.Category, "Description": row.Description, "Total_Amount": float(row.Total_Amount or 0)}
            for row in result2
        ]
        logger.info(f"Fetched {len(top_stocks)} top stock entries for {name}")

        return {
            "lead_name": name,
            "activity_totals": activity_totals,
            "top_stocks_summary": top_stocks
        }

    lead1_data = fetch_lead_data(name1)
    lead2_data = fetch_lead_data(name2)
    logger.info(f"Comparing data between {name1} and {name2}...")

    def compare_activities(lead1, lead2):
        all_activities = {entry['Activity'] for entry in lead1 + lead2}
        comparison = []
        for activity in all_activities:
            amt1 = next((x['Total_Amount'] for x in lead1 if x['Activity'] == activity), 0)
            amt2 = next((x['Total_Amount'] for x in lead2 if x['Activity'] == activity), 0)
            comparison.append({
                "Activity": activity,
                name1: amt1,
                name2: amt2,
                "Difference": round(abs(amt1 - amt2), 2),
                "Higher_Contribution": name1 if amt1 > amt2 else name2 if amt2 > amt1 else "Equal"
            })
        return comparison

    def compare_top_stocks(lead1, lead2):
        map1 = {(x["Category"], x["Description"]): x["Total_Amount"] for x in lead1}
        map2 = {(x["Category"], x["Description"]): x["Total_Amount"] for x in lead2}

        keys = set(map1.keys()).union(map2.keys())
        comparison = []
        for key in keys:
            amt1 = map1.get(key, 0)
            amt2 = map2.get(key, 0)
            comparison.append({
                "Category": key[0],
                "Description": key[1],
                name1: amt1,
                name2: amt2,
                "Difference": round(amt1 - amt2, 2),
                "Higher_Contribution": name1 if amt1 > amt2 else name2 if amt2 > amt1 else "Equal"
            })
        return comparison

    logger.info(f"Comparison complete for {name1} vs {name2}")
    return {
        "lead1": name1,
        "lead2": name2,
        "activity_comparison": compare_activities(lead1_data["activity_totals"], lead2_data["activity_totals"]),
        "top_stocks_comparison": compare_top_stocks(lead1_data["top_stocks_summary"], lead2_data["top_stocks_summary"])
    }

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
    return JSONResponse({"status": "healthy", "service": "Lead Comparison MCP Server"})

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
    logger.info("🚀 Starting Lead Comparison MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
