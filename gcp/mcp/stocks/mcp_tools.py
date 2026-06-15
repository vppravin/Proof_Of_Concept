# mcp_stock_server.py
import os
import re
import datetime
import io
import logging
import requests
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from dotenv import load_dotenv

load_dotenv()

from fastmcp import FastMCP
from starlette.responses import StreamingResponse
from google.cloud import storage

from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from mcp.server.sse import SseServerTransport
import uvicorn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Config ---
GCS_BUCKET_NAME = "stock_charts"
GCS_FOLDER = "stock_charts"
GCS_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "gbu-demo-playground")
FINNHUB_API_KEY = "d1nou89r01qovv8kko50d1nou89r01qovv8kko5g"
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
ALPHA_VANTAGE_API_KEY = "OMPUUCGKQAILGF87"
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"


logger.info("Initializing FastMCP server...")
mcp = FastMCP("Stock tools")
logger.info("FastMCP server initialized")

# --- Helper ---
def get_stock_symbol(company_name: str) -> str:
    logger.debug(f"Looking up symbol for company: {company_name}")
    url = f"{FINNHUB_BASE_URL}/search"
    params = {"q": company_name, "token": FINNHUB_API_KEY}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        logger.error(f"Finnhub API error for {company_name}: {e}")
        raise ValueError(f"Error from Finnhub: {e}")
    
    results = data.get("result", [])
    if not results:
        logger.warning(f"No symbol found for company: {company_name}")
        raise ValueError(f"Could not find symbol for '{company_name}'")
    symbol = results[0]["symbol"]
    logger.info(f"Found symbol {symbol} for {company_name}")
    return symbol

def upload_to_gcs(local_path: str, destination: str):
    logger.info(f"Uploading {local_path} to GCS bucket {GCS_BUCKET_NAME}/{destination}")
    try:
        client = storage.Client(project=GCS_PROJECT_ID)
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(destination)
        blob.upload_from_filename(local_path)
        logger.info(f"Successfully uploaded to GCS: {destination}")
    except Exception as e:
        logger.error(f"Failed to upload to GCS: {e}")
        raise

# --- Tool 1: Current Price ---
@mcp.tool()
def get_current_stock_price(company: str) -> str:
    logger.info(f"Tool invoked: get_current_stock_price for {company}")
    companies = [c.strip() for c in re.split(r",|\band\b", company, flags=re.IGNORECASE) if c.strip()]
    results = []
    
    for comp in companies:
        try:
            symbol = get_stock_symbol(comp)
            quote_url = f"{FINNHUB_BASE_URL}/quote"
            params = {"symbol": symbol, "token": FINNHUB_API_KEY}
            data = requests.get(quote_url, params=params).json()
            price = data.get("c")
            if price is None:
                results.append(f"❌ No data for {comp} ({symbol})")
            else:
                results.append(f"✅ {comp} ({symbol}): ${price:.2f}")
        except Exception as e:
            logger.error(f"Error fetching price for {comp}: {e}")
            results.append(f"❌ Error for {comp}: {str(e)}")
    logger.info(f"Completed get_current_stock_price for {len(companies)} companies")
    return "\n".join(results)

# --- Tool 2: Textual Trend ---
@mcp.tool()
def get_stock_trend(company: str, days: int = 30) -> str:
    """Get stock price trend for a company over specified days."""
    logger.info(f"Tool invoked: get_stock_trend for {company} ({days} days)")
    companies = [c.strip() for c in re.split(r",|\band\b", company, flags=re.IGNORECASE) if c.strip()]
    results = []
    
    for comp in companies:
        try:
            symbol = get_stock_symbol(comp)
            
            # Use Alpha Vantage for historical data
            params = {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "apikey": ALPHA_VANTAGE_API_KEY,
                "outputsize": "compact"
            }
            
            response = requests.get(ALPHA_VANTAGE_BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()
            
            if "Time Series (Daily)" not in data:
                results.append(f"❌ No data available for {comp} ({symbol})")
                continue
            
            time_series = data["Time Series (Daily)"]
            sorted_dates = sorted(time_series.keys(), reverse=True)[:days]
            
            if len(sorted_dates) < 2:
                results.append(f"❌ Insufficient data for {comp} ({symbol})")
                continue
            
            # Get latest and oldest prices in the period
            latest_date = sorted_dates[0]
            oldest_date = sorted_dates[-1]
            latest_price = float(time_series[latest_date]["4. close"])
            oldest_price = float(time_series[oldest_date]["4. close"])
            
            # Calculate overall change
            change = latest_price - oldest_price
            change_pct = (change / oldest_price) * 100
            trend = "📈 rising" if change > 0 else "📉 falling" if change < 0 else "➡️ flat"
            
            # Get high and low over the period
            high = max(float(time_series[d]["2. high"]) for d in sorted_dates)
            low = min(float(time_series[d]["3. low"]) for d in sorted_dates)
            
            results.append(
                f"📊 {comp.title()} ({symbol}) - {trend} over {days} days\n"
                f"Latest: ${latest_price:.2f} ({latest_date}) | Start: ${oldest_price:.2f} ({oldest_date})\n"
                f"Change: ${change:+.2f} ({change_pct:+.2f}%)\n"
                f"Period Range: ${low:.2f} - ${high:.2f}"
            )
        except Exception as e:
            logger.error(f"Error fetching trend for {comp}: {e}")
            results.append(f"❌ Error for {comp}: {str(e)}")
    
    logger.info(f"Completed get_stock_trend for {len(companies)} companies")
    return "\n\n".join(results) if results else "❌ No results"

# --- Tool 3: Chart Image ---
@mcp.tool()
def generate_stock_chart(company: str, days: int = 30) -> str:
    """Generate a stock price chart for one or more companies."""
    logger.info(f"Tool invoked: generate_stock_chart for {company} ({days} days)")
    companies = [c.strip() for c in re.split(r",|\band\b", company, flags=re.IGNORECASE) if c.strip()]
    if not companies:
        logger.warning("No valid company names provided for chart generation")
        return "❌ No valid company names provided."
    
    plt.figure(figsize=(10, 5))
    plotted = []
    
    for comp in companies:
        try:
            symbol = get_stock_symbol(comp)
            
            # Use Alpha Vantage for historical data (free tier available)
            params = {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "apikey": ALPHA_VANTAGE_API_KEY,
                "outputsize": "compact"  # Last 100 days
            }
            
            response = requests.get(ALPHA_VANTAGE_BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()
            
            if "Time Series (Daily)" not in data:
                continue
            
            time_series = data["Time Series (Daily)"]
            
            # Extract dates and closing prices
            dates = []
            prices = []
            for date_str in sorted(time_series.keys(), reverse=True)[:days]:
                dates.append(datetime.datetime.strptime(date_str, "%Y-%m-%d"))
                prices.append(float(time_series[date_str]["4. close"]))
            
            if len(prices) < 2:
                continue
            
            # Reverse to show oldest to newest
            dates.reverse()
            prices.reverse()
            
            plt.plot(dates, prices, label=f"{comp.title()} ({symbol})", marker='o', markersize=3)
            plotted.append(comp.title())
        except Exception as e:
            continue
    
    if not plotted:
        plt.close()
        logger.error("Failed to plot any companies for chart generation")
        return "❌ Could not plot any companies. Please ensure ALPHA_VANTAGE_API_KEY is set in .env file. Get free key from https://www.alphavantage.co/support/#api-key"
    
    plt.title(f"Stock Chart: {' vs '.join(plotted)} ({days} days)")
    plt.xlabel("Date")
    plt.ylabel("Price (USD)")
    plt.legend()
    plt.grid(True)
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    filename = f"chart_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.png"
    local_path = f"/tmp/{filename}"
    blob_path = f"{GCS_FOLDER}/{filename}"
    
    plt.savefig(local_path)
    plt.close()
    
    try:
        upload_to_gcs(local_path, blob_path)
        # Get MCP server URL from environment (will be set on Cloud Run)
        base_url = os.getenv("CLOUD_RUN_URL", "https://stocks-agent-146646146609.us-central1.run.app")
        chart_url = f"{base_url}/chart/{filename}"
        logger.info(f"Chart generated successfully: {chart_url}")
        return chart_url
    except Exception as e:
        logger.error(f"Chart upload failed: {e}")
        return f"❌ Upload failed: {str(e)}"

# --- MCP App Setup ---
from starlette.responses import JSONResponse, Response

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

async def health_check(request: Request):
    """Health check endpoint"""
    return JSONResponse({"status": "healthy", "service": "Stock Tools MCP Server"})

async def serve_chart(request: Request):
    """Serve chart images from GCS bucket"""
    filename = request.path_params['filename']
    
    # Validate filename to prevent path traversal
    if not re.match(r'^chart_\d{14}\.png$', filename):
        logger.error(f"Invalid filename format: {filename}")
        return JSONResponse({"error": "Invalid filename"}, status_code=400)
    
    logger.info(f"Serving chart: {filename}")
    
    try:
        storage_client = storage.Client(project=GCS_PROJECT_ID)
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(f"{GCS_FOLDER}/{filename}")
        
        if not blob.exists():
            logger.error(f"Chart not found: {filename}")
            return JSONResponse({"error": "Chart not found"}, status_code=404)
        
        chart_data = blob.download_as_bytes()
        logger.info(f"Successfully served {filename}, size: {len(chart_data)} bytes")
        
        return Response(
            chart_data,
            media_type="image/png",
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                "Cache-Control": "public, max-age=3600",
                "Access-Control-Allow-Origin": "*"
            }
        )
    except Exception as e:
        logger.error(f"Error serving chart {filename}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

app = Starlette(
    debug=True,
    routes=[
        Route("/", endpoint=health_check),
        Route("/health", endpoint=health_check),
        Route("/sse", endpoint=handle_sse),
        Route("/chart/{filename}", endpoint=serve_chart),  # Chart serving endpoint
        Mount("/messages/", app=sse.handle_post_message),
    ],
)


if __name__ == "__main__":
    logger.info("🚀 Starting Stock Tools MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")