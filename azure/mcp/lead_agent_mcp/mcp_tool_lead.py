import os
import logging
from dotenv import load_dotenv
from simple_salesforce import Salesforce
from fastmcp import FastMCP
import uvicorn

load_dotenv()  # Fallback for local development

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [LEAD_MCP] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("Lead_Agent_MCP")
logger.info("FastMCP server initialized")

def get_salesforce_connection():
    """Establish Salesforce connection using credentials from environment variables"""
    logger.info("Establishing Salesforce connection...")
    try:
        sf = Salesforce(
            username=os.getenv("SF_USERNAME"),
            password=os.getenv("SF_PASSWORD"),
            security_token=os.getenv("SF_SECURITY_TOKEN"),
            domain='login'
        )
        logger.info("Salesforce connection established")
        return sf
    except Exception as e:
        logger.error(f"Salesforce connection failed: {e}")
        raise

@mcp.tool()
def get_salesforce_leads() -> dict:
    """
    Fetch high-value sales leads from Salesforce.
    Returns leads with Status='Working', LeadSource='Website', and AnnualRevenue >= 250K.
    Sorted by Annual Revenue (highest first).
    """
    logger.info("MCP Tool invoked: get_salesforce_leads")
    try:
        sf = get_salesforce_connection()
        query = """
            SELECT External_ID__c, Name, Status, AnnualRevenue, LeadSource, Address, Email
            FROM Lead
            WHERE Status = 'Working' AND LeadSource = 'Website' AND AnnualRevenue >= 250000
            ORDER BY AnnualRevenue DESC
            LIMIT 10
        """
        logger.info(f"Executing SOQL query")
        results = sf.query(query)
        record_count = len(results.get("records", []))
        logger.info(f"Retrieved {record_count} leads")
        return {"records": results.get("records", [])}
    except Exception as e:
        logger.error(f"Error fetching leads: {e}")
        return {"error": str(e)}

# Get the ASGI app for HTTP transport
app = mcp.http_app()

if __name__ == "__main__":
    logger.info("🚀 Starting Salesforce MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
