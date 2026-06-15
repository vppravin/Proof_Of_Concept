import os
import logging
import pyodbc
from typing import Optional
from collections import defaultdict
from dotenv import load_dotenv
from fastmcp import FastMCP
import uvicorn

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [SMA_MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

AZURE_SQL_CONNECTION_STRING = os.getenv("AZURE_SQL_CONNECTION_STRING")

logger.info("Initializing FastMCP server...")
mcp = FastMCP("SMA Analysis Tools", stateless_http=True)
logger.info("FastMCP server initialized")


def get_conn():
    return pyodbc.connect(AZURE_SQL_CONNECTION_STRING)


@mcp.tool()
def summarize_by_activity_type(lead_name: Optional[str] = None) -> dict:
    """Categorizes and sums SMA activity types for a specific lead or all leads."""
    logger.info(f"Tool invoked: summarize_by_activity_type for lead: {lead_name or 'all leads'}")
    where = "WHERE Lead_Name = ?" if lead_name else ""
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
        FROM SMA
        {where}
        GROUP BY
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
          END
    """
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(query, lead_name) if lead_name else cursor.execute(query)
        summary = f"SMA summary for {lead_name}:\n" if lead_name else "SMA summary across all leads:\n"
        summary += "\n".join([f"{row.Group_Type}: ${row.Total_Amount:.2f}" for row in cursor.fetchall()])
        cursor.close()
        conn.close()
        logger.info("Activity type summary completed successfully")
        return {"result": summary}
    except Exception as e:
        logger.error(f"Error summarizing activities: {e}")
        return {"error": f"Error summarizing activities: {str(e)}"}


@mcp.tool()
def summarize_target_vs_actual(lead_name: Optional[str] = None) -> dict:
    """Compares actual investment vs $500,000 target."""
    logger.info(f"Tool invoked: summarize_target_vs_actual for lead: {lead_name or 'all leads'}")
    lead_filter = "AND Lead_Name = ?" if lead_name else ""
    params = [lead_name] * 4 if lead_name else []

    query = f"""
        SELECT Lead_Name, SUM(amt) AS Actual_Investment FROM (
            SELECT Lead_Name, SUM(Amount) AS amt FROM SMA
            WHERE LOWER(Description) LIKE '%retirement plan contribution%' {lead_filter} GROUP BY Lead_Name
            UNION ALL
            SELECT Lead_Name, SUM(Debit) AS amt FROM Checking
            WHERE LOWER(Description) LIKE '%goal contribution%' {lead_filter} GROUP BY Lead_Name
            UNION ALL
            SELECT Lead_Name, SUM(Credit) AS amt FROM Savings
            WHERE LOWER(Description) LIKE '%home goal contribution%' {lead_filter} GROUP BY Lead_Name
            UNION ALL
            SELECT Lead_Name, SUM(Credit) AS amt FROM Managed
            WHERE LOWER(Description) LIKE '%retirement goal contribution%' {lead_filter} GROUP BY Lead_Name
        ) t GROUP BY Lead_Name
    """
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(query, *params) if params else cursor.execute(query)
        target = 500000.00
        summary = ""
        for row in cursor.fetchall():
            actual = float(row.Actual_Investment)
            diff = target - actual
            summary += (
                f"{row.Lead_Name}: Target ${target:,.2f}, Actual ${actual:,.2f} "
                f"({abs(diff):,.2f} {'below' if diff > 0 else 'above'} target)\n"
            )
        cursor.close()
        conn.close()
        logger.info("Target vs actual comparison completed successfully")
        return {"result": summary.strip()}
    except Exception as e:
        logger.error(f"Error comparing target vs actual: {e}")
        return {"error": f"Error comparing target vs actual: {str(e)}"}


@mcp.tool()
def trend_analysis(lead_name: Optional[str] = None) -> dict:
    """Shows monthly activity trends grouped by type."""
    logger.info(f"Tool invoked: trend_analysis for lead: {lead_name or 'all leads'}")
    where = "WHERE Lead_Name = ?" if lead_name else ""
    query = f"""
        SELECT
          FORMAT(Date, 'MMM yyyy') AS Month,
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
        FROM SMA
        {where}
        GROUP BY FORMAT(Date, 'MMM yyyy'),
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
          END
        ORDER BY MIN(Date), Group_Type
    """
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(query, lead_name) if lead_name else cursor.execute(query)
        monthly = defaultdict(list)
        for row in cursor.fetchall():
            monthly[row.Group_Type].append(f"{row.Month}: ${(row.Total or 0):.2f}")
        cursor.close()
        conn.close()
        report = f"Monthly trend analysis for {lead_name}:\n\n" if lead_name else "Monthly trend analysis:\n\n"
        for activity_type, entries in monthly.items():
            report += f"📊 {activity_type}:\n" + "\n".join(entries) + "\n\n"
        logger.info("Trend analysis completed successfully")
        return {"result": report.strip()}
    except Exception as e:
        logger.error(f"Error analyzing trends: {e}")
        return {"error": f"Error analyzing trends: {str(e)}"}


@mcp.tool()
def actual_investment_breakdown(lead_name: Optional[str] = None) -> dict:
    """Breaks down actual investment source-wise."""
    logger.info(f"Tool invoked: actual_investment_breakdown for lead: {lead_name or 'all leads'}")
    lead_filter = "AND Lead_Name = ?" if lead_name else ""
    params = [lead_name] * 4 if lead_name else []

    query = f"""
        SELECT 'SMA: Retirement Plan Contribution' AS Source, SUM(Amount) AS Amount FROM SMA
        WHERE LOWER(Description) LIKE '%retirement plan contribution%' {lead_filter}
        UNION ALL
        SELECT 'Checking: Goal Contribution', SUM(Debit) FROM Checking
        WHERE LOWER(Description) LIKE '%goal contribution%' {lead_filter}
        UNION ALL
        SELECT 'Savings: Home Goal Contribution', SUM(Credit) FROM Savings
        WHERE LOWER(Description) LIKE '%home goal contribution%' {lead_filter}
        UNION ALL
        SELECT 'Managed: Retirement Goal Contribution', SUM(Credit) FROM Managed
        WHERE LOWER(Description) LIKE '%retirement goal contribution%' {lead_filter}
    """
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(query, *params) if params else cursor.execute(query)
        breakdown = [f"{row.Source}: ${row.Amount:.2f}" for row in cursor.fetchall() if row.Amount]
        response = f"Actual investment breakdown for {lead_name}:\n" if lead_name else "Actual investment breakdown:\n"
        response += "\n".join(breakdown)
        cursor.close()
        conn.close()
        logger.info("Investment breakdown completed successfully")
        return {"result": response.strip()}
    except Exception as e:
        logger.error(f"Error getting investment breakdown: {e}")
        return {"error": f"Error getting investment breakdown: {str(e)}"}


app = mcp.http_app()

if __name__ == "__main__":
    logger.info("🚀 Starting SMA Analysis MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
