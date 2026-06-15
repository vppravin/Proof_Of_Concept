import os
import re
import logging
from google.cloud import storage, bigquery
from vertexai.preview.generative_models import GenerativeModel, Part  # type: ignore
from dotenv import load_dotenv  # type: ignore
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import JSONResponse
from mcp.server.sse import SseServerTransport
import uvicorn

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [FUND_MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

GCS_BUCKET = os.getenv("GCS_BUCKET", "fund_analyzer")
INPUT_PDF_BLOB = os.getenv("INPUT_PDF_BLOB", "trend_document/Franklin India Fund Factsheet.pdf")
OUTPUT_TXT_BLOB = os.getenv("OUTPUT_TXT_BLOB", "trend_document/funds_trend_insight.txt")
LOCAL_TEMP_PDF = os.getenv("LOCAL_TEMP_PDF", "/tmp/funds_trend.pdf")
LOCAL_OUTPUT_TXT = os.getenv("LOCAL_OUTPUT_TXT", "/tmp/funds_trend_insight.txt")
PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
FUNDS_TABLE = os.getenv("FUNDS_TABLE", "gbu-demo-playground.Wealth_Management.Funds")

logger.info(f"Initializing BigQuery client for project: {PROJECT_ID}")
client = bigquery.Client(project=PROJECT_ID)

logger.info("Initializing FastMCP server...")
mcp = FastMCP("Fund Performance Tools")
logger.info("FastMCP server initialized")

# --- Tool 1: Fund Returns Summary (by Lead Name) ---
@mcp.tool
def fetch_fund_returns(lead_name: str) -> dict:
    logger.info(f"Tool invoked: fetch_fund_returns for lead: {lead_name}")
    try:
        query = f"""
            SELECT
                fund_name, total_units, current_nav, current_value, total_invested,
                (current_value - total_invested) AS absolute_return,
                SAFE_DIVIDE((current_value - total_invested), total_invested) * 100 AS return_percentage
            FROM `{FUNDS_TABLE}`
            WHERE LOWER(Lead_Name) = LOWER(@lead_name)
        """
        logger.info(f"Executing BigQuery query for lead: {lead_name}")
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("lead_name", "STRING", lead_name)]
        )
        results = client.query(query, job_config=job_config).result()

        summary = []
        for row in results:
            summary.append(
                f"Fund: {row['fund_name']}\n"
                f"  - Units: {row['total_units']}\n"
                f"  - NAV: {row['current_nav']}\n"
                f"  - Current Value: {row['current_value']}\n"
                f"  - Invested: {row['total_invested']}\n"
                f"  - Return: {row['absolute_return']:.2f} ({row['return_percentage']:.2f}%)"
            )
        result_text = "\n\n".join(summary) if summary else "No fund data found for this lead."
        logger.info(f"Query successful. Retrieved {len(summary)} fund(s) for {lead_name}")
        return {"result": result_text}

    except Exception as e:
        logger.error(f"Error fetching fund returns for {lead_name}: {e}")
        return {"error": f"Error fetching fund returns: {str(e)}"}


# --- Tool 2: Compare PDF-based Fund Performance with BigQuery (by Lead Name) ---
@mcp.tool
def compare_fund_performance(lead_name: str) -> dict:
    logger.info(f"Tool invoked: compare_fund_performance for lead: {lead_name}")
    try:
        # Step 1: Download PDF from GCS
        logger.info("Step 1: Downloading PDF from GCS...")
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET)
        blob = bucket.blob(INPUT_PDF_BLOB)
        blob.download_to_filename(LOCAL_TEMP_PDF)
        logger.info(f"PDF downloaded to {LOCAL_TEMP_PDF}")

        # Step 2: Extract using Gemini
        logger.info("Step 2: Extracting data using Gemini...")
        model = GenerativeModel("gemini-2.0-flash-001")
        with open(LOCAL_TEMP_PDF, "rb") as pdf_file:
            pdf_part = Part.from_data(data=pdf_file.read(), mime_type="application/pdf")
            response = model.generate_content([
                """Extract the details of annual return trends for the fund mentioned in this document as a JSON 
                object with 'year', 'return_percentage', 'w_vs_benchmark' and 'w_vs_peergroup' keys.
                Give the best year and worst year with their return_percentage based on the return_performance
                of the fund.
                Give the top equity issuers with 'issuers', 'fund' as keys.
                Give the total funds of the top equity issuers.
                Also provide the insights as 'Insights:' in the text format for the above analyzed data.
                """,
                pdf_part
            ])
        with open(LOCAL_OUTPUT_TXT, "w") as f:
            f.write(response.text)
        logger.info(f"Gemini response saved to {LOCAL_OUTPUT_TXT}")

        # Step 3: Upload TXT to GCS
        logger.info("Step 3: Uploading insights to GCS...")
        blob_out = bucket.blob(OUTPUT_TXT_BLOB)
        blob_out.upload_from_filename(LOCAL_OUTPUT_TXT)
        logger.info("Insights uploaded to GCS")

        # Step 4: Fetch actual return from BigQuery by lead
        logger.info(f"Step 4: Querying BigQuery for lead '{lead_name}'...")
        query = f"""
            SELECT
                fund_name,
                SAFE_DIVIDE((current_value - total_invested), total_invested) * 100 AS return_percentage
            FROM `{FUNDS_TABLE}`
            WHERE LOWER(Lead_Name) = LOWER(@lead_name)
                AND fund_name = 'Franklin_India_Fund_Class_W'
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("lead_name", "STRING", lead_name)]
        )
        result = client.query(query, job_config=job_config).result()

        actual_return = None
        for row in result:
            actual_return = row.return_percentage
            logger.info(f"Found actual return: {actual_return}%")

        if actual_return is None:
            logger.warning(f"No return data found for lead '{lead_name}'")
            return {
                "status": "error",
                "message": f"No return data found in BigQuery for lead '{lead_name}'."
            }

        # Step 5: Parse expected returns from Gemini output
        logger.info("Step 5: Parsing Gemini output...")
        import json
        with open(LOCAL_OUTPUT_TXT, "r") as f:
            content = f.read().strip()
        
        # Remove markdown code blocks if present
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        elif content.startswith("```"):
            content = content.replace("```", "").strip()

        try:
            data = json.loads(content)
            annual_trends = data.get("annual_return_trends", [])
            
            if not annual_trends:
                logger.warning("No annual_return_trends found in JSON")
                return {
                    "status": "error",
                    "message": "No return data found in the trend document."
                }
            
            # Get the most recent year (first in list)
            latest_year_data = annual_trends[0]
            expected_return = float(latest_year_data["return_percentage"])
            logger.info(f"Expected return for {latest_year_data['year']}: {expected_return}%")
            
            tolerance = 2.0
            if actual_return < expected_return - tolerance:
                performance = "Underperforming based on trend analysis"
            elif actual_return > expected_return + tolerance:
                performance = "Outperforming based on trend analysis"
            else:
                performance = "Performing within expected trend range"
            
            insights_text = data.get("Insights", "No insights found.")
            
            result_dict = {
                "lead_name": lead_name,
                "actual_return": actual_return,
                "expected_return_year": latest_year_data["year"],
                "expected_return": expected_return,
                "performance": performance,
                "insights": insights_text
            }
            logger.info(f"Comparison successful for {lead_name}")
            return result_dict
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Error parsing JSON: {str(e)}")
            return {
                "status": "error",
                "message": f"Error parsing trend document: {str(e)}"
            }

    except Exception as e:
        logger.error(f"Error in compare_fund_performance: {str(e)}")
        return {"error": f"Error comparing performance: {str(e)}"}


# SSE + Starlette app config
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
    return JSONResponse({"status": "healthy", "service": "Fund Analysis MCP Server"})

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
    logger.info("🚀 Starting Fund Analysis MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
