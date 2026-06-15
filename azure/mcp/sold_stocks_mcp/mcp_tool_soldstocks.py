import os
import logging
import datetime
import pyodbc
import yfinance as yf
from dotenv import load_dotenv
from fastmcp import FastMCP
import uvicorn

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [SOLD_STOCKS_MCP] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

AZURE_SQL_CONNECTION_STRING = os.getenv("AZURE_SQL_CONNECTION_STRING")

logger.info("Initializing FastMCP server...")
mcp = FastMCP("Stock Sale Analysis Tools")
logger.info("FastMCP server initialized")


@mcp.tool()
def analyze_sold_stocks(lead_name: str) -> dict:
    logger.info(f"Tool invoked: analyze_sold_stocks for lead: {lead_name}")
    try:
        conn = pyodbc.connect(AZURE_SQL_CONNECTION_STRING)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT Description, SUM(UnitPrice) AS Unit_price, SUM(Quantity) AS Quantity, SUM(Amount) AS Total_Amount
            FROM SDI
            WHERE Activity = 'Sale' AND Lead_Name = ?
            GROUP BY Description
        """, lead_name)
        stock_results = cursor.fetchall()
        cursor.close()
        conn.close()

        if not stock_results:
            logger.warning(f"No sold stocks found for lead: {lead_name}")
            return {"result": f"No sold stocks found for lead: {lead_name}"}

        logger.info(f"Found {len(stock_results)} sold stocks for {lead_name}")

        sold_stocks = [{
            "Description": row.Description,
            "Sold_Amount": float(row.Unit_price),
            "Quantity": int(row.Quantity),
            "Total_Amount": float(row.Total_Amount)
        } for row in stock_results]

        sold_companies = [row.Description for row in stock_results]

        stock_trends = []
        days = 10
        logger.info(f"Fetching {days}-day price trends for {len(sold_companies)} stocks...")
        for comp in sold_companies:
            try:
                stock = yf.Ticker(comp)
                end = datetime.datetime.now()
                start = end - datetime.timedelta(days=days + 5)
                hist = stock.history(start=start.strftime('%Y-%m-%d'), end=end.strftime('%Y-%m-%d'))
                closing = hist["Close"].dropna().tail(days).tolist()

                if not closing or len(closing) < 2:
                    stock_trends.append(f"Not enough data for {comp}")
                    continue

                trend = "rising" if closing[-1] > closing[0] else "falling"
                price_str = ", ".join([f"${p:.2f}" for p in closing])
                stock_trends.append(f"{comp.upper()} - {trend} over {len(closing)} days:\n{price_str}")
                logger.info(f"{comp}: {trend} trend detected")
            except Exception as e:
                logger.error(f"Error fetching data for {comp}: {e}")
                stock_trends.append(f"Error for {comp}: {str(e)}")

        decisions = []
        for stock in sold_stocks:
            comp = stock["Description"]
            sold_amount = stock["Sold_Amount"]
            quantity = stock["Quantity"]
            total_amount = stock["Total_Amount"]

            matching_trend = next((t for t in stock_trends if comp.upper() in t), None)

            if matching_trend and "Error" not in matching_trend and "Not enough" not in matching_trend:
                prices_str = matching_trend.split("\n")[1]
                prices = [float(p.strip().replace("$", "")) for p in prices_str.split(",")]
                last_price = prices[-1]

                if last_price > sold_amount:
                    conclusion = "Might have waited a bit - stock price went up after selling."
                elif last_price < sold_amount:
                    conclusion = "Good decision - stock dropped after selling."
                else:
                    conclusion = "Neutral - stock price remained stable."

                decisions.append(
                    f"{quantity} shares of {comp}: Sold at ${sold_amount:.2f} for total ${total_amount:.2f}, Current price: ${last_price:.2f} → {conclusion}"
                )
            else:
                decisions.append(f"{comp}: No trend data available.")

        logger.info(f"Analysis complete for {lead_name}. Generated {len(decisions)} decisions.")
        return {
            "lead_name": lead_name,
            "sold_companies": sold_companies,
            "trends": stock_trends,
            "decisions": decisions
        }

    except Exception as e:
        logger.error(f"Error analyzing stock sales: {e}")
        return {"error": f"Error analyzing stock sales: {str(e)}"}


app = mcp.http_app()

if __name__ == "__main__":
    logger.info("🚀 Starting Stock Sale Analysis MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
