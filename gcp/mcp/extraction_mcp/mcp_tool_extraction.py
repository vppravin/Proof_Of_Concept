import os
import json
import logging
from dotenv import load_dotenv
from starlette.responses import JSONResponse

from fastmcp import FastMCP
from google.cloud import storage
import vertexai
from vertexai.generative_models import GenerativeModel, Part

from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from mcp.server.sse import SseServerTransport
import uvicorn

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [EXTRACTION_MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
LOCATION = os.getenv("LOCATION", "us-central1")
BUCKET_NAME = os.getenv("BUCKET_NAME", "underwriting-workbench")

logger.info(f"Initializing Vertex AI for project: {PROJECT_ID}, location: {LOCATION}")
vertexai.init(project=PROJECT_ID, location=LOCATION)

gcs_client = storage.Client(project=PROJECT_ID)

logger.info("Initializing FastMCP server...")
mcp = FastMCP("Extraction MCP Tools")
logger.info("FastMCP server initialized")

EXTRACTION_PROMPT = """
You are an expert insurance document parser.

Extract ALL of the following fields from the submitted insurance document.
Return ONLY a valid JSON object — no explanation, no markdown, no extra text.

Fields to extract:
- insured_name (string)
- lob (string) — Line of Business e.g. Commercial Property, Workers Compensation, Cyber, Marine, Liability
- broker (string)
- sum_insured (number)
- renewal_days (number) — days until renewal/effective date from today
- effective_date (string) — format YYYY-MM-DD
- year_built (number)
- construction_type (string) — one of: Fire-resistive, Non-Combustible, Ordinary, Heavy timber
- eq_zone (string) — one of: No, Low, Medium, High
- flood_zone (string) — one of: No, Low, Medium, High
- roof_type (string)
- fire_protection (string)
- no_of_employees (number)
- loss_history (array of objects with keys: date, description, amount, status)

If a field is not found in the document, set its value to null.
Return only the JSON object.
"""


@mcp.tool
def read_submission_file(gcs_uri: str) -> dict:
    """Reads an uploaded submission file from GCS and returns its content as bytes (base64).

    Args:
        gcs_uri: GCS URI of the uploaded file e.g. gs://underwriting-workbench/submissions/NB-25-34677/form.pdf

    Returns:
        Dict with 'gcs_uri', 'content_type', and 'size_bytes' confirming the file exists and is readable.
    """
    logger.info(f"Tool invoked: read_submission_file for URI: {gcs_uri}")
    try:
        if not gcs_uri.startswith("gs://"):
            return {"error": f"Invalid GCS URI: {gcs_uri}. Must start with gs://"}

        path = gcs_uri.replace("gs://", "")
        bucket_name, blob_path = path.split("/", 1)

        bucket = gcs_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)

        if not blob.exists():
            return {"error": f"File not found at {gcs_uri}"}

        blob.reload()
        content_type = blob.content_type or "application/octet-stream"
        size_bytes = blob.size

        logger.info(f"File confirmed: {gcs_uri}, type: {content_type}, size: {size_bytes} bytes")
        return {
            "gcs_uri": gcs_uri,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "status": "ready"
        }
    except Exception as e:
        logger.error(f"Error reading file from GCS: {e}")
        return {"error": f"Error reading file: {str(e)}"}


@mcp.tool
def extract_fields(gcs_uri: str) -> dict:
    """Extracts structured insurance fields from a submission document using Gemini Flash multimodal.

    Supports PDF, Excel, Word, scanned images, and email text files stored in GCS.

    Args:
        gcs_uri: GCS URI of the uploaded submission file e.g. gs://underwriting-workbench/submissions/NB-25-34677/form.pdf

    Returns:
        Dict with 'extracted_fields' containing structured JSON of all extracted insurance fields.
    """
    logger.info(f"Tool invoked: extract_fields for URI: {gcs_uri}")
    try:
        if not gcs_uri.startswith("gs://"):
            return {"error": f"Invalid GCS URI: {gcs_uri}. Must start with gs://"}

        # Determine mime type from extension
        ext = gcs_uri.lower().split(".")[-1]
        mime_map = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "tiff": "image/tiff",
            "tif": "image/tiff",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "txt": "text/plain",
        }
        mime_type = mime_map.get(ext, "application/pdf")
        logger.info(f"Detected mime type: {mime_type} for extension: {ext}")

        model = GenerativeModel("gemini-2.0-flash-001")

        file_part = Part.from_uri(uri=gcs_uri, mime_type=mime_type)

        logger.info("Calling Gemini Flash multimodal for field extraction...")
        response = model.generate_content([file_part, EXTRACTION_PROMPT])

        raw_text = response.text.strip()

        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        extracted = json.loads(raw_text)
        logger.info(f"Extraction successful for: {extracted.get('insured_name', 'unknown')}")
        return {"extracted_fields": extracted}

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response as JSON: {e}")
        return {"error": f"Gemini returned non-JSON response: {str(e)}", "raw_response": response.text if 'response' in dir() else ""}
    except Exception as e:
        logger.error(f"Error extracting fields: {e}")
        return {"error": f"Error extracting fields: {str(e)}"}


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


async def health_check(request: Request):
    """Health check endpoint for Cloud Run"""
    logger.debug("Health check requested")
    return JSONResponse({"status": "healthy", "service": "Extraction MCP Server"})


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
    logger.info("🚀 Starting Extraction MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
