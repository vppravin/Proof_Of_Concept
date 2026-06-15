import os
import logging
import datetime
import yfinance as yf
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
    format='%(asctime)s - [SOLD_STOCKS_MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
SDI_TABLE = os.getenv("SDI_TABLE", "gbu-demo-playground.Wealth_Management.SDI")

logger.info("Initializing FastMCP server...")
mcp = FastMCP("Stock Sale Analysis Tools")
logger.info("FastMCP server initialized")

@mcp.tool
def analyze_sold_stocks(lead_name: str = "Peter Griffin") -> dict:
    logger.info(f"Tool invoked: analyze_sold_stocks for lead: {lead_name}")
    client = bigquery.Client(project=PROJECT_ID)

    query = f"""
        SELECT
            Description,
            SUM(UnitPrice) AS Unit_price,
            SUM(Quantity) AS Quantity,
            SUM(Amount) AS Total_Amount
        FROM
            `{SDI_TABLE}`
        WHERE
            Activity = 'Sale'
            AND Lead_Name = @lead_name
        GROUP BY
            Description
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("lead_name", "STRING", lead_name)
        ]
    )

    try:
        logger.info(f"Querying BigQuery for sold stocks of lead: {lead_name}")
        query_job = client.query(query, job_config=job_config)
        stock_results = list(query_job.result())

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

        sold_companies = [str(row.Description) for row in stock_results]

        stock_trends = []
        days = 10
        logger.info(f"Fetching {days}-day price trends for {len(sold_companies)} stocks...")
        for comp in sold_companies:
            try:
                logger.info(f"Fetching data for {comp}...")
                stock = yf.Ticker(comp)
                end = datetime.datetime.now()
                start = end - datetime.timedelta(days=days + 5)
                hist = stock.history(start=start.strftime('%Y-%m-%d'), end=end.strftime('%Y-%m-%d'))
                closing = hist["Close"].dropna().tail(days).tolist()

                if not closing or len(closing) < 2:
                    logger.warning(f"Not enough data for {comp}")
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
                    f"{quantity} shares of {comp}: Sold at ${sold_amount:.2f} for the total amount of ${total_amount:.2f}, Current stock price: ${last_price:.2f} → {conclusion}"
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
    return JSONResponse({"status": "healthy", "service": "Stock Sale Analysis MCP Server"})

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
    logger.info("🚀 Starting Stock Sale Analysis MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
