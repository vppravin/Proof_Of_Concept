import os
import logging
import pyodbc
from dotenv import load_dotenv
from fastmcp import FastMCP
import uvicorn

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [COMPARISON_MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

AZURE_SQL_CONNECTION_STRING = os.getenv("AZURE_SQL_CONNECTION_STRING")

logger.info("Initializing FastMCP server...")
mcp = FastMCP("Lead Stock Comparison Tools")
logger.info("FastMCP server initialized")


def get_conn():
    return pyodbc.connect(AZURE_SQL_CONNECTION_STRING)


@mcp.tool()
def compare_leads_data(name1: str, name2: str) -> dict:
    """Compares investment activities and top stocks between two leads."""
    logger.info(f"Tool invoked: compare_leads_data for {name1} vs {name2}")

    def fetch_lead_data(name: str) -> dict:
        conn = get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT Activity, SUM(Amount) AS Total_Amount
            FROM SDI
            WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)
            GROUP BY Activity
        """, name, name)
        activity_totals = [
            {"Activity": row.Activity, "Total_Amount": float(row.Total_Amount or 0)}
            for row in cursor.fetchall()
        ]

        top_stocks = []
        for category, activity in [("Top_Purchases", "Purchase"), ("Top_Sales", "Sale"), ("Top_Dividends", "Dividend")]:
            cursor.execute("""
                SELECT TOP 5 ? AS Category, Description, SUM(Amount) AS Total_Amount
                FROM SDI
                WHERE (LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?))
                  AND Activity = ?
                GROUP BY Description
                ORDER BY SUM(Amount) DESC
            """, category, name, name, activity)
            top_stocks.extend([
                {"Category": row.Category, "Description": row.Description, "Total_Amount": float(row.Total_Amount or 0)}
                for row in cursor.fetchall()
            ])

        cursor.close()
        conn.close()
        return {"lead_name": name, "activity_totals": activity_totals, "top_stocks_summary": top_stocks}

    try:
        lead1_data = fetch_lead_data(name1)
        lead2_data = fetch_lead_data(name2)

        def compare_activities(lead1, lead2):
            all_activities = {e["Activity"] for e in lead1 + lead2}
            return [{
                "Activity": a,
                name1: next((x["Total_Amount"] for x in lead1 if x["Activity"] == a), 0),
                name2: next((x["Total_Amount"] for x in lead2 if x["Activity"] == a), 0),
                "Difference": round(abs(
                    next((x["Total_Amount"] for x in lead1 if x["Activity"] == a), 0) -
                    next((x["Total_Amount"] for x in lead2 if x["Activity"] == a), 0)
                ), 2),
                "Higher_Contribution": name1 if
                    next((x["Total_Amount"] for x in lead1 if x["Activity"] == a), 0) >
                    next((x["Total_Amount"] for x in lead2 if x["Activity"] == a), 0)
                    else name2 if
                    next((x["Total_Amount"] for x in lead2 if x["Activity"] == a), 0) >
                    next((x["Total_Amount"] for x in lead1 if x["Activity"] == a), 0)
                    else "Equal"
            } for a in all_activities]

        def compare_top_stocks(lead1, lead2):
            map1 = {(x["Category"], x["Description"]): x["Total_Amount"] for x in lead1}
            map2 = {(x["Category"], x["Description"]): x["Total_Amount"] for x in lead2}
            return [{
                "Category": k[0], "Description": k[1],
                name1: map1.get(k, 0), name2: map2.get(k, 0),
                "Difference": round(map1.get(k, 0) - map2.get(k, 0), 2),
                "Higher_Contribution": name1 if map1.get(k, 0) > map2.get(k, 0)
                    else name2 if map2.get(k, 0) > map1.get(k, 0) else "Equal"
            } for k in set(map1) | set(map2)]

        logger.info(f"Comparison complete for {name1} vs {name2}")
        return {
            "lead1": name1, "lead2": name2,
            "activity_comparison": compare_activities(lead1_data["activity_totals"], lead2_data["activity_totals"]),
            "top_stocks_comparison": compare_top_stocks(lead1_data["top_stocks_summary"], lead2_data["top_stocks_summary"])
        }
    except Exception as e:
        logger.error(f"Error in compare_leads_data: {e}")
        return {"error": str(e)}


app = mcp.http_app()

if __name__ == "__main__":
    logger.info("🚀 Starting Lead Comparison MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
