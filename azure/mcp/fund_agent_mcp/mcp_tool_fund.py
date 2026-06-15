import os
import json
import logging
import pyodbc
from azure.storage.blob import BlobServiceClient
from openai import AzureOpenAI
from dotenv import load_dotenv
from fastmcp import FastMCP
import uvicorn

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [FUND_MCP] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Azure Configuration
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
BLOB_CONTAINER = os.getenv("BLOB_CONTAINER", "fund-analyzer")
INPUT_PDF_BLOB = os.getenv("INPUT_PDF_BLOB", "trend_document/trend_document_Franklin India Fund Factsheet.pdf")
OUTPUT_TXT_BLOB = os.getenv("OUTPUT_TXT_BLOB", "trend_document/trend_document_funds_trend_insight.txt")
LOCAL_TEMP_PDF = os.getenv("LOCAL_TEMP_PDF", "/tmp/funds_trend.pdf")
LOCAL_OUTPUT_TXT = os.getenv("LOCAL_OUTPUT_TXT", "/tmp/funds_trend_insight.txt")

AZURE_SQL_CONNECTION_STRING = os.getenv("AZURE_SQL_CONNECTION_STRING")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "wm-gpt4o")

logger.info("Initializing Azure clients...")
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
openai_client = AzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    api_version="2024-02-15-preview"
)

logger.info("Initializing FastMCP server...")
mcp = FastMCP("Fund_Agent_MCP")
logger.info("FastMCP server initialized")

@mcp.tool()
def fetch_fund_returns(lead_name: str) -> dict:
    """Fetch fund returns summary for a specific lead/customer by name."""
    logger.info(f"Tool invoked: fetch_fund_returns for lead: {lead_name}")
    try:
        query = """
            SELECT
                fund_name, total_units, current_nav, current_value, total_invested,
                (current_value - total_invested) AS absolute_return,
                ((current_value - total_invested) / total_invested) * 100 AS return_percentage
            FROM Funds
            WHERE LOWER(Lead_Name) = LOWER(?)
        """
        logger.info(f"Executing Azure SQL query for lead: {lead_name}")
        
        conn = pyodbc.connect(AZURE_SQL_CONNECTION_STRING)
        cursor = conn.cursor()
        cursor.execute(query, lead_name)
        
        summary = []
        for row in cursor.fetchall():
            summary.append(
                f"Fund: {row.fund_name}\n"
                f"  - Units: {row.total_units}\n"
                f"  - NAV: {row.current_nav}\n"
                f"  - Current Value: {row.current_value}\n"
                f"  - Invested: {row.total_invested}\n"
                f"  - Return: {row.absolute_return:.2f} ({row.return_percentage:.2f}%)"
            )
        
        cursor.close()
        conn.close()
        
        result_text = "\n\n".join(summary) if summary else "No fund data found for this lead."
        logger.info(f"Query successful. Retrieved {len(summary)} fund(s) for {lead_name}")
        return {"result": result_text}

    except Exception as e:
        logger.error(f"Error fetching fund returns for {lead_name}: {e}")
        return {"error": f"Error fetching fund returns: {str(e)}"}


@mcp.tool()
def compare_fund_performance(lead_name: str) -> dict:
    """Compare PDF-based fund performance with Azure SQL data for a specific lead/customer."""
    logger.info(f"Tool invoked: compare_fund_performance for lead: {lead_name}")
    try:
        # Step 1: Download PDF from Azure Blob Storage
        logger.info("Step 1: Downloading PDF from Azure Blob Storage...")
        blob_client = blob_service_client.get_blob_client(container=BLOB_CONTAINER, blob=INPUT_PDF_BLOB)
        with open(LOCAL_TEMP_PDF, "wb") as pdf_file:
            pdf_file.write(blob_client.download_blob().readall())
        logger.info(f"PDF downloaded to {LOCAL_TEMP_PDF}")

        # Step 2: Extract text from PDF
        logger.info("Step 2: Extracting text from PDF...")
        from PyPDF2 import PdfReader
        reader = PdfReader(LOCAL_TEMP_PDF)
        pdf_text = ""
        for page in reader.pages:
            pdf_text += page.extract_text()
        logger.info(f"Extracted {len(pdf_text)} characters from PDF")
        
        # Step 3: Analyze with Azure OpenAI
        logger.info("Step 3: Analyzing with Azure OpenAI...")
        response = openai_client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {
                    "role": "user",
                    "content": f"""Extract the details of annual return trends for the fund from this text as a JSON object.

PDF Text:
{pdf_text}

Return a JSON object with:
- 'annual_return_trends' array with 'year', 'return_percentage', 'w_vs_benchmark', 'w_vs_peergroup'
- 'Insights' key with analysis text

Return only valid JSON, no markdown."""
                }
            ],
            max_tokens=2000
        )
        
        response_text = response.choices[0].message.content
        with open(LOCAL_OUTPUT_TXT, "w") as f:
            f.write(response_text)
        logger.info(f"Azure OpenAI response saved to {LOCAL_OUTPUT_TXT}")

        # Upload TXT to Azure Blob Storage
        logger.info("Uploading insights to Azure Blob Storage...")
        blob_client_out = blob_service_client.get_blob_client(container=BLOB_CONTAINER, blob=OUTPUT_TXT_BLOB)
        with open(LOCAL_OUTPUT_TXT, "rb") as data:
            blob_client_out.upload_blob(data, overwrite=True)
        logger.info("Insights uploaded to Azure Blob Storage")

        # Step 4: Fetch actual return from Azure SQL
        logger.info(f"Step 4: Querying Azure SQL for lead '{lead_name}'...")
        query = """
            SELECT
                fund_name,
                ((current_value - total_invested) / total_invested) * 100 AS return_percentage
            FROM Funds
            WHERE LOWER(Lead_Name) = LOWER(?)
                AND fund_name = 'Franklin_India_Fund_Class_W'
        """
        
        conn = pyodbc.connect(AZURE_SQL_CONNECTION_STRING)
        cursor = conn.cursor()
        cursor.execute(query, lead_name)
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        actual_return = None
        if row:
            actual_return = float(row.return_percentage)
            logger.info(f"Found actual return: {actual_return}%")

        if actual_return is None:
            logger.warning(f"No return data found for lead '{lead_name}'")
            return {
                "status": "error",
                "message": f"No return data found in Azure SQL for lead '{lead_name}'."
            }

        # Step 5: Parse expected returns from Azure OpenAI output
        logger.info("Step 5: Parsing Azure OpenAI output...")
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
            
            # Get the most recent year
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


# Get the ASGI app for HTTP transport
app = mcp.http_app()

if __name__ == "__main__":
    logger.info("🚀 Starting Fund Analysis MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
