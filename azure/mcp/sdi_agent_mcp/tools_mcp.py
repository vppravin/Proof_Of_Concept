import os
import logging
import pyodbc
from dotenv import load_dotenv
from fastmcp import FastMCP
import uvicorn

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [SDI_MCP] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

AZURE_SQL_CONNECTION_STRING = os.getenv("AZURE_SQL_CONNECTION_STRING")

logger.info("Initializing FastMCP server...")
mcp = FastMCP("SDI tools", stateless_http=True)
logger.info("FastMCP server initialized")


def get_conn():
    return pyodbc.connect(AZURE_SQL_CONNECTION_STRING)


# Tool 1: Summary
@mcp.tool()
def get_summary(name: str) -> dict:
    logger.info(f"Tool invoked: get_summary for name={name}")
    results = {}
    try:
        conn = get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT Activity, SUM(Amount) AS Total_Amount
            FROM SDI
            WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)
            GROUP BY Activity
        """, name, name)
        activity_totals = [{"Activity": row.Activity, "Total_Amount": row.Total_Amount} for row in cursor.fetchall()]
        results['activity_totals'] = activity_totals
        logger.info(f"Retrieved {len(activity_totals)} activity totals")

        top_stocks = []
        for category, activity in [('Top_Purchases', 'Purchase'), ('Top_Sales', 'Sale'), ('Top_Dividends', 'Dividend')]:
            cursor.execute("""
                SELECT TOP 5 ? AS Category, Description, SUM(Amount) AS Total_Amount
                FROM SDI
                WHERE (LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?))
                  AND Activity = ?
                GROUP BY Description
                ORDER BY Total_Amount DESC
            """, category, name, name, activity)
            top_stocks.extend([{"Category": row.Category, "Description": row.Description, "Total_Amount": row.Total_Amount} for row in cursor.fetchall()])

        results['top_stocks_summary'] = top_stocks
        logger.info(f"Retrieved {len(top_stocks)} top stocks")
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error in get_summary: {e}")
        return {"error": str(e)}
    return results


# Tool 2: Highest Purchased Stock
@mcp.tool()
def highest_purchase(name: str) -> dict:
    logger.info(f"Tool invoked: highest_purchase for name={name}")
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TOP 1 Description, SUM(Amount) AS Total_Purchase
            FROM SDI
            WHERE Activity = 'Purchase' AND (LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?))
            GROUP BY Description
            ORDER BY Total_Purchase DESC
        """, name, name)
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return {"top_purchase_company": {"Company": row.Description, "Total_Purchase": row.Total_Purchase} if row else {}}
    except Exception as e:
        logger.error(f"Error in highest_purchase: {e}")
        return {"error": str(e)}


# Tool 3: Highest Dividend Providing Stock
@mcp.tool()
def highest_dividend(name: str) -> dict:
    logger.info(f"Tool invoked: highest_dividend for name={name}")
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TOP 1 Description, SUM(Amount) AS Total_Dividend
            FROM SDI
            WHERE Activity = 'Dividend' AND (LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?))
            GROUP BY Description
            ORDER BY Total_Dividend DESC
        """, name, name)
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return {"top_dividend_company": {"Company": row.Description, "Total_Dividend": row.Total_Dividend} if row else {}}
    except Exception as e:
        logger.error(f"Error in highest_dividend: {e}")
        return {"error": str(e)}


# Tool 4: Highest Sold Stock
@mcp.tool()
def highest_sales(name: str) -> dict:
    logger.info(f"Tool invoked: highest_sales for name={name}")
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TOP 1 Description, SUM(Amount) AS Total_Sale
            FROM SDI
            WHERE Activity = 'Sale' AND (LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?))
            GROUP BY Description
            ORDER BY Total_Sale DESC
        """, name, name)
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return {"top_sale_company": {"Company": row.Description, "Total_Sale": row.Total_Sale} if row else {}}
    except Exception as e:
        logger.error(f"Error in highest_sales: {e}")
        return {"error": str(e)}


app = mcp.http_app()

if __name__ == "__main__":
    logger.info("🚀 Starting SDI MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
