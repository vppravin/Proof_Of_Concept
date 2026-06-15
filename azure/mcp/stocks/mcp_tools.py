import os
import re
import datetime
import logging
import requests
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from fastmcp import FastMCP
from azure.storage.blob import BlobServiceClient, ContentSettings
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
import uvicorn

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [STOCKS_MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
BLOB_CONTAINER = os.getenv("BLOB_CONTAINER", "stock-charts")
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://stocks-mcp.livelybay-96634f40.eastus2.azurecontainerapps.io")

logger.info("Initializing FastMCP server...")
mcp = FastMCP("Stock tools")
logger.info("FastMCP server initialized")


def get_stock_symbol(company_name: str) -> str:
    url = f"{FINNHUB_BASE_URL}/search"
    params = {"q": company_name, "token": FINNHUB_API_KEY}
    response = requests.get(url, params=params)
    response.raise_for_status()
    results = response.json().get("result", [])
    if not results:
        raise ValueError(f"Could not find symbol for '{company_name}'")
    symbol = results[0]["symbol"]
    logger.info(f"Found symbol {symbol} for {company_name}")
    return symbol


def upload_to_blob(local_path: str, blob_name: str) -> str:
    blob_service = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
    container_client = blob_service.get_container_client(BLOB_CONTAINER)
    try:
        container_client.create_container()
    except Exception:
        pass
    with open(local_path, "rb") as f:
        container_client.upload_blob(
            name=blob_name, data=f, overwrite=True,
            content_settings=ContentSettings(content_type="image/png")
        )
    return f"{APP_BASE_URL}/chart/{blob_name}"


@mcp.tool()
def get_current_stock_price(company: str) -> str:
    """Get current stock price for one or more companies."""
    logger.info(f"Tool invoked: get_current_stock_price for {company}")
    companies = [c.strip() for c in re.split(r",|\band\b", company, flags=re.IGNORECASE) if c.strip()]
    results = []
    for comp in companies:
        try:
            symbol = get_stock_symbol(comp)
            data = requests.get(f"{FINNHUB_BASE_URL}/quote", params={"symbol": symbol, "token": FINNHUB_API_KEY}).json()
            price = data.get("c")
            results.append(f"✅ {comp} ({symbol}): ${price:.2f}" if price else f"❌ No data for {comp} ({symbol})")
        except Exception as e:
            results.append(f"❌ Error for {comp}: {str(e)}")
    return "\n".join(results)


@mcp.tool()
def get_stock_trend(company: str, days: int = 30) -> str:
    """Get stock price trend for a company over specified days."""
    logger.info(f"Tool invoked: get_stock_trend for {company} ({days} days)")
    companies = [c.strip() for c in re.split(r",|\band\b", company, flags=re.IGNORECASE) if c.strip()]
    results = []
    for comp in companies:
        try:
            symbol = get_stock_symbol(comp)
            data = requests.get(ALPHA_VANTAGE_BASE_URL, params={
                "function": "TIME_SERIES_DAILY", "symbol": symbol,
                "apikey": ALPHA_VANTAGE_API_KEY, "outputsize": "compact"
            }).json()
            if "Time Series (Daily)" not in data:
                results.append(f"❌ No data available for {comp} ({symbol})")
                continue
            time_series = data["Time Series (Daily)"]
            sorted_dates = sorted(time_series.keys(), reverse=True)[:days]
            latest_price = float(time_series[sorted_dates[0]]["4. close"])
            oldest_price = float(time_series[sorted_dates[-1]]["4. close"])
            change = latest_price - oldest_price
            change_pct = (change / oldest_price) * 100
            trend = "📈 rising" if change > 0 else "📉 falling" if change < 0 else "➡️ flat"
            high = max(float(time_series[d]["2. high"]) for d in sorted_dates)
            low = min(float(time_series[d]["3. low"]) for d in sorted_dates)
            results.append(
                f"📊 {comp.title()} ({symbol}) - {trend} over {days} days\n"
                f"Latest: ${latest_price:.2f} ({sorted_dates[0]}) | Start: ${oldest_price:.2f} ({sorted_dates[-1]})\n"
                f"Change: ${change:+.2f} ({change_pct:+.2f}%)\nPeriod Range: ${low:.2f} - ${high:.2f}"
            )
        except Exception as e:
            results.append(f"❌ Error for {comp}: {str(e)}")
    return "\n\n".join(results) if results else "❌ No results"


@mcp.tool()
def generate_stock_chart(company: str, days: int = 30) -> str:
    """Generate a stock price chart for one or more companies."""
    logger.info(f"Tool invoked: generate_stock_chart for {company} ({days} days)")
    companies = [c.strip() for c in re.split(r",|\band\b", company, flags=re.IGNORECASE) if c.strip()]
    if not companies:
        return "❌ No valid company names provided."

    plt.figure(figsize=(10, 5))
    plotted = []
    for comp in companies:
        try:
            symbol = get_stock_symbol(comp)
            data = requests.get(ALPHA_VANTAGE_BASE_URL, params={
                "function": "TIME_SERIES_DAILY", "symbol": symbol,
                "apikey": ALPHA_VANTAGE_API_KEY, "outputsize": "compact"
            }).json()
            if "Time Series (Daily)" not in data:
                continue
            time_series = data["Time Series (Daily)"]
            entries = sorted(time_series.keys(), reverse=True)[:days]
            dates = [datetime.datetime.strptime(d, "%Y-%m-%d") for d in reversed(entries)]
            prices = [float(time_series[d]["4. close"]) for d in reversed(entries)]
            if len(prices) < 2:
                continue
            plt.plot(dates, prices, label=f"{comp.title()} ({symbol})", marker='o', markersize=3)
            plotted.append(comp.title())
        except Exception:
            continue

    if not plotted:
        plt.close()
        return "❌ Could not plot any companies."

    plt.title(f"Stock Chart: {' vs '.join(plotted)} ({days} days)")
    plt.xlabel("Date")
    plt.ylabel("Price (USD)")
    plt.legend()
    plt.grid(True)
    plt.xticks(rotation=45)
    plt.tight_layout()

    filename = f"chart_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.png"
    local_path = f"/tmp/{filename}"
    plt.savefig(local_path)
    plt.close()

    try:
        chart_url = upload_to_blob(local_path, filename)
        logger.info(f"Chart generated: {chart_url}")
        return chart_url
    except Exception as e:
        logger.error(f"Chart upload failed: {e}")
        return f"❌ Upload failed: {str(e)}"


async def serve_chart(request: Request):
    filename = request.path_params["filename"]
    if not re.match(r'^chart_\d{14}\.png$', filename):
        return JSONResponse({"error": "Invalid filename"}, status_code=400)
    try:
        blob_service = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        blob_client = blob_service.get_blob_client(container=BLOB_CONTAINER, blob=filename)
        data = blob_client.download_blob().readall()
        return Response(data, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=404)

mcp_app = mcp.http_app()

app = Starlette(
    lifespan=mcp_app.lifespan,
    routes=[
        Route("/chart/{filename}", endpoint=serve_chart),
        Mount("/", app=mcp_app),
    ]
)

if __name__ == "__main__":
    logger.info("🚀 Starting Stock Tools MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
