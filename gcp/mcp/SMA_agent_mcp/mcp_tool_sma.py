import os
import logging
from typing import Optional
from collections import defaultdict
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
    format='%(asctime)s - [SMA_MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
logger.info(f"Initializing BigQuery client for project: {PROJECT_ID}")
client = bigquery.Client(project=PROJECT_ID)

logger.info("Initializing FastMCP server...")
mcp = FastMCP("SMA Analysis Tools")
logger.info("FastMCP server initialized")

@mcp.tool
def summarize_by_activity_type(lead_name: Optional[str] = None) -> dict:
    """Categorizes and sums SMA activity types for a specific lead or all leads.
    
    Args:
        lead_name: Optional name of the lead to analyze. If None, analyzes all leads.
    
    Returns:
        Dict with 'result' key containing formatted string summary of SMA activities by type.
    """
    logger.info(f"Tool invoked: summarize_by_activity_type for lead: {lead_name or 'all leads'}")
    query = f"""
        SELECT
          CASE
            WHEN LOWER(Description) LIKE 'buy:%' THEN 'Investment Purchase'
            WHEN LOWER(Description) LIKE 'sell:%' THEN 'Investment Sale'
            WHEN LOWER(Activity_Type) IN ('dividend', 'interest', 'interest income') OR LOWER(Description) LIKE '%coupon%' THEN 'Investment Income'
            WHEN LOWER(Activity_Type) LIKE '%fee%' OR LOWER(Description) LIKE '%fee%' THEN 'Fees'
            WHEN LOWER(Activity_Type) LIKE '%tax%' THEN 'Taxes'
            WHEN LOWER(Activity_Type) = 'deposit' THEN 'Deposit'
            WHEN LOWER(Activity_Type) LIKE '%fx%' THEN 'FX Gain/Loss'
            WHEN LOWER(Activity_Type) = 'withdrawal' THEN 'Withdrawal'
            ELSE 'Others'
          END AS Group_Type,
          SUM(Amount) AS Total_Amount
        FROM `{PROJECT_ID}.Wealth_Management.SMA`
    """
    if lead_name:
        query += f" WHERE Lead_Name = '{lead_name}'"
    query += " GROUP BY Group_Type"

    try:
        logger.info("Executing BigQuery for activity type summary...")
        results = client.query(query).result()
        summary = f"SMA summary for {lead_name}:\n" if lead_name else "SMA summary across all leads:\n"
        summary += "\n".join([f"{row['Group_Type']}: ${row['Total_Amount']:.2f}" for row in results])
        logger.info("Activity type summary completed successfully")
        return {"result": summary}
    except Exception as e:
        logger.error(f"Error summarizing activities: {e}")
        return {"error": f"Error summarizing activities: {str(e)}"}

@mcp.tool
def summarize_target_vs_actual(lead_name: Optional[str] = None) -> dict:
    """Compares actual investment vs $500,000 target."""
    logger.info(f"Tool invoked: summarize_target_vs_actual for lead: {lead_name or 'all leads'}")
    lead_filter = f"AND Lead_Name = '{lead_name}'" if lead_name else ""
    
    subqueries = [
        f"""
        SELECT Lead_Name, SUM(Amount) AS amt
        FROM `{PROJECT_ID}.Wealth_Management.SMA`
        WHERE LOWER(Description) LIKE '%retirement plan contribution%'
        {lead_filter}
        GROUP BY Lead_Name
        """,
        f"""
        SELECT Lead_Name, SUM(Debit) AS amt
        FROM `{PROJECT_ID}.Wealth_Management.Checking`
        WHERE LOWER(Description) LIKE '%goal contribution%'
        {lead_filter}
        GROUP BY Lead_Name
        """,
        f"""
        SELECT Lead_Name, SUM(Credit) AS amt
        FROM `{PROJECT_ID}.Wealth_Management.Savings`
        WHERE LOWER(Description) LIKE '%home goal contribution%'
        {lead_filter}
        GROUP BY Lead_Name
        """,
        f"""
        SELECT Lead_Name, SUM(Credit) AS amt
        FROM `{PROJECT_ID}.Wealth_Management.Managed`
        WHERE LOWER(Description) LIKE '%retirement goal contribution%'
        {lead_filter}
        GROUP BY Lead_Name
        """
    ]

    union_query = " UNION ALL ".join(subqueries)
    full_query = f"""
        SELECT Lead_Name, SUM(amt) AS Actual_Investment
        FROM ({union_query})
        GROUP BY Lead_Name
    """

    try:
        logger.info("Executing BigQuery for target vs actual comparison...")
        results = client.query(full_query).result()
        target = 500000.00
        summary = ""

        for row in results:
            actual = row["Actual_Investment"]
            diff = target - actual
            summary += (
                f"{row['Lead_Name']}: Target ${target:,.2f}, Actual ${actual:,.2f} "
                f"({abs(diff):,.2f} {'below' if diff > 0 else 'above'} target)\n"
            )

        logger.info("Target vs actual comparison completed successfully")
        return {"result": summary.strip()}
    except Exception as e:
        logger.error(f"Error comparing target vs actual: {e}")
        return {"error": f"Error comparing target vs actual: {str(e)}"}

@mcp.tool
def trend_analysis(lead_name: Optional[str] = None) -> dict:
    """Shows monthly activity trends grouped by type."""
    logger.info(f"Tool invoked: trend_analysis for lead: {lead_name or 'all leads'}")
    query = f"""
        SELECT
          FORMAT_DATE('%b %Y', DATE) AS Month,
          CASE
            WHEN LOWER(Description) LIKE 'buy:%' THEN 'Investment Purchase'
            WHEN LOWER(Description) LIKE 'sell:%' THEN 'Investment Sale'
            WHEN LOWER(Activity_Type) IN ('dividend', 'interest', 'interest income') OR LOWER(Description) LIKE '%coupon%' THEN 'Investment Income'
            WHEN LOWER(Activity_Type) LIKE '%fee%' OR LOWER(Description) LIKE '%fee%' THEN 'Fees'
            WHEN LOWER(Activity_Type) LIKE '%tax%' THEN 'Taxes'
            WHEN LOWER(Activity_Type) = 'deposit' THEN 'Deposit'
            WHEN LOWER(Activity_Type) LIKE '%fx%' THEN 'FX Gain/Loss'
            WHEN LOWER(Activity_Type) = 'withdrawal' THEN 'Withdrawal'
            ELSE 'Others'
          END AS Group_Type,
          SUM(Amount) AS Total
        FROM `{PROJECT_ID}.Wealth_Management.SMA`
    """
    if lead_name:
        query += f" WHERE Lead_Name = '{lead_name}'"
    query += " GROUP BY Month, Group_Type ORDER BY PARSE_DATE('%b %Y', Month), Group_Type"

    try:
        logger.info("Executing BigQuery for trend analysis...")
        results = client.query(query).result()
        monthly = defaultdict(list)
        for row in results:
            monthly[row["Group_Type"]].append(f"{row['Month']}: ${row['Total']:.2f}")

        report = f"Monthly trend analysis for {lead_name}:\n\n" if lead_name else "Monthly trend analysis:\n\n"
        for activity_type, entries in monthly.items():
            report += f"📊 {activity_type}:\n" + "\n".join(entries) + "\n\n"
        logger.info("Trend analysis completed successfully")
        return {"result": report.strip()}
    except Exception as e:
        logger.error(f"Error analyzing trends: {e}")
        return {"error": f"Error analyzing trends: {str(e)}"}

@mcp.tool
def actual_investment_breakdown(lead_name: Optional[str] = None) -> dict:
    """Breaks down actual investment source-wise."""
    logger.info(f"Tool invoked: actual_investment_breakdown for lead: {lead_name or 'all leads'}")
    def single_query(label, table, column, match):
        return f"""
            SELECT '{label}' AS Source, SUM({column}) AS Amount
            FROM `{PROJECT_ID}.{table}`
            WHERE LOWER(Description) LIKE '%{match}%'
            {f"AND Lead_Name = '{lead_name}'" if lead_name else ''}
        """

    queries = [
        single_query("SMA: Retirement Plan Contribution", "Wealth_Management.SMA", "Amount", "retirement plan contribution"),
        single_query("Checking: Goal Contribution", "Wealth_Management.Checking", "Debit", "goal contribution"),
        single_query("Savings: Home Goal Contribution", "Wealth_Management.Savings", "Credit", "home goal contribution"),
        single_query("Managed: Retirement Goal Contribution", "Wealth_Management.Managed", "Credit", "retirement goal contribution"),
    ]

    full_query = " UNION ALL ".join(queries)
    
    try:
        logger.info("Executing BigQuery for investment breakdown...")
        results = client.query(full_query).result()
        breakdown = [f"{row['Source']}: ${row['Amount']:.2f}" for row in results if row['Amount']]
        response = f"Actual investment breakdown for {lead_name}:\n" if lead_name else "Actual investment breakdown:\n"
        response += "\n".join(breakdown)
        logger.info("Investment breakdown completed successfully")
        return {"result": response.strip()}
    except Exception as e:
        logger.error(f"Error getting investment breakdown: {e}")
        return {"error": f"Error getting investment breakdown: {str(e)}"}

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
    # No return needed - SSE handles the response

async def health_check(request: Request):
    """Health check endpoint for Cloud Run"""
    logger.debug("Health check requested")
    return JSONResponse({"status": "healthy", "service": "SMA Analysis MCP Server"})

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
    logger.info("🚀 Starting SMA Analysis MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
