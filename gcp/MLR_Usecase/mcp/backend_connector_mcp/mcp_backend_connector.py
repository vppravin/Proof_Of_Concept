import os
import json
import logging
import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP
import uvicorn

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [BACKEND_CONNECTOR_MCP] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Backend URL — update this when the team provides the Cloud Run URL
BACKEND_URL = os.getenv("BACKEND_URL", "https://PLACEHOLDER-UPDATE-THIS.run.app")

logger.info("Initializing FastMCP server for Backend Connector...")
mcp = FastMCP("Backend_Connector_Tools")
logger.info(f"FastMCP server initialized. Backend URL: {BACKEND_URL}")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _call_backend(endpoint: str, payload: dict, method: str = "POST") -> dict:
    """Call the LangChain backend API."""
    url = f"{BACKEND_URL}{endpoint}"
    logger.info(f"Calling backend: {method} {url}")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            if method == "POST":
                response = await client.post(url, json=payload)
            elif method == "GET":
                response = await client.get(url, params=payload)
            else:
                return {"error": f"Unsupported method: {method}"}

            response.raise_for_status()
            result = response.json()
            logger.info(f"Backend response: {response.status_code}")
            return result
    except httpx.HTTPStatusError as e:
        logger.error(f"Backend HTTP error: {e.response.status_code} - {e.response.text}")
        return {"error": f"Backend returned {e.response.status_code}: {e.response.text}"}
    except httpx.ConnectError as e:
        logger.error(f"Cannot reach backend: {e}")
        return {"error": f"Cannot reach backend at {url}. Is the service running?"}
    except Exception as e:
        logger.error(f"Backend call failed: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# MCP Tools — PLACEHOLDER: Update these once backend API spec is available
# ---------------------------------------------------------------------------

# Example tool structure — replace with actual endpoints from their Swagger docs
#
# @mcp.tool
# async def process_document(file_path: str) -> dict:
#     """
#     Send a document to the backend for processing.
#
#     Args:
#         file_path: GCS path or URL to the document.
#     """
#     logger.info(f"Tool invoked: process_document for {file_path}")
#     return await _call_backend("/api/process", {"file_path": file_path})
#
#
# @mcp.tool
# async def get_results(task_id: str) -> dict:
#     """
#     Get processing results from the backend.
#
#     Args:
#         task_id: The task ID returned from process_document.
#     """
#     logger.info(f"Tool invoked: get_results for {task_id}")
#     return await _call_backend(f"/api/results/{task_id}", {}, method="GET")


@mcp.tool
async def health_check() -> dict:
    """Check if the backend service is reachable and healthy."""
    logger.info("Tool invoked: health_check")
    return await _call_backend("/health", {}, method="GET")


# ---------------------------------------------------------------------------
# Streamable HTTP App
# ---------------------------------------------------------------------------
app = mcp.http_app()

if __name__ == "__main__":
    logger.info("Starting Backend Connector MCP Server (Streamable HTTP)...")
    port = int(os.environ.get("PORT", 8081))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
