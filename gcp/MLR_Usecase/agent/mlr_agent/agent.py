import io
import mimetypes
import os
import logging
from typing import Any, Dict

import google.auth
import httpx
from google.adk.agents import Agent
from google.adk.tools import ToolContext
from google.genai import Client, types
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [MLR_AGENT] - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id or "gbu-demo-playground")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("model", "gemini-2.0-flash")
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "https://backend-fastapi-1090458629658.us-central1.run.app",
)
TIMEOUT = 300


# ── Helpers ───────────────────────────────────────────────────────────────────


def parse_uploaded_document(file_path: str) -> Dict[str, Any]:
    """Parse an uploaded document into plain text using Gemini via Vertex AI.

    Use this when you need OCR / text extraction from a local file.
    """
    try:
        client = Client(
            vertexai=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION"),
        )

        mime_type, _ = mimetypes.guess_type(file_path)

        if not mime_type:
            return {"output": {"text": "❌ Unsupported file format."}}

        if mime_type.startswith("text"):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            return {"output": {"text": content}}

        elif mime_type.startswith("application/pdf") or mime_type.startswith("image"):
            with open(file_path, "rb") as f:
                data = f.read()
            result = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[types.Part.from_bytes(data=data, mime_type=mime_type)],
                config=types.GenerateContentConfig(temperature=0.4),
            )
            return {"output": {"text": result.text}}

        else:
            return {"output": {"text": f"⚠️ File type {mime_type} is not currently supported."}}

    except Exception as e:
        return {"output": {"text": f"❌ Failed to parse document: {e}"}}


async def _extract_file_from_context(tool_context: ToolContext) -> tuple:
    """Extract raw file bytes and filename from the tool context.

    Priority order:
    1. ADK Artifact service (Gemini uploads files as artifacts)
    2. inline_data bytes (ADK UI / small files)
    3. file_data URI (GCS or HTTP)
    4. Session history fallback

    Returns raw bytes suitable for direct upload to the backend.
    """
    def _from_parts(parts):
        if not parts:
            return None, None
        for part in parts:
            if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                if len(part.inline_data.data) > 100:
                    name = getattr(part.inline_data, "display_name", None) or "document.pdf"
                    logger.info(f"Found inline_data: {name}, {len(part.inline_data.data)} bytes")
                    return part.inline_data.data, name
            if hasattr(part, "file_data") and part.file_data and part.file_data.file_uri:
                uri = part.file_data.file_uri
                name = getattr(part.file_data, "display_name", None)
                if not name:
                    name = uri.split("/")[-1] if "/" in uri else "document.pdf"
                logger.info(f"Found file_data URI: {uri}, name: {name}")
                file_bytes = None
                if uri.startswith("gs://"):
                    from google.cloud import storage as gcs
                    uri_parts = uri.replace("gs://", "").split("/", 1)
                    blob = gcs.Client().bucket(uri_parts[0]).blob(uri_parts[1])
                    file_bytes = blob.download_as_bytes()
                else:
                    import google.auth.transport.requests
                    creds, _ = google.auth.default()
                    creds.refresh(google.auth.transport.requests.Request())
                    resp = httpx.get(uri, headers={"Authorization": f"Bearer {creds.token}"}, timeout=TIMEOUT)
                    resp.raise_for_status()
                    file_bytes = resp.content
                if file_bytes and len(file_bytes) > 100:
                    return file_bytes, name
        return None, None

    # Priority 1: ADK Artifact service (Gemini stores uploads here)
    try:
        artifact_keys = await tool_context.list_artifacts()
        logger.info(f"Artifacts available: {artifact_keys}")
        if artifact_keys:
            for key in artifact_keys:
                artifact_part = await tool_context.load_artifact(key)
                if artifact_part and artifact_part.inline_data and artifact_part.inline_data.data:
                    data = artifact_part.inline_data.data
                    if len(data) > 100:
                        name = getattr(artifact_part.inline_data, "display_name", None) or key
                        logger.info(f"Loaded artifact '{key}': {name}, {len(data)} bytes")
                        return data, name
    except Exception as e:
        logger.warning(f"Artifact load failed: {e}")

    # Priority 2: Current turn inline_data / file_data
    uc = tool_context.user_content
    if uc and uc.parts:
        file_bytes, file_name = _from_parts(uc.parts)
        if file_bytes:
            return file_bytes, file_name

    # Priority 3: Session history
    try:
        for event in reversed(tool_context.session.events):
            if event.author == "user" and event.content and event.content.parts:
                file_bytes, file_name = _from_parts(event.content.parts)
                if file_bytes:
                    return file_bytes, file_name
    except Exception as e:
        logger.warning(f"Session scan failed: {e}")

    return None, None


# ── Tools ─────────────────────────────────────────────────────────────────────


async def debug_context(tool_context: ToolContext) -> dict:
    """Debug tool: inspect what file data is available in the current context.

    Call this to see exactly what the platform is passing to the agent.
    Useful for diagnosing file upload issues.

    Args:
        tool_context: The ADK tool context (automatically provided).

    Returns:
        dict with detailed context inspection results.
    """
    result = {"user_content": None, "session_events": [], "artifacts": []}

    # Inspect artifacts (Gemini stores uploads here)
    try:
        artifact_keys = await tool_context.list_artifacts()
        result["artifacts"] = {"keys": artifact_keys}
        for key in (artifact_keys or []):
            art = await tool_context.load_artifact(key)
            if art and art.inline_data:
                result["artifacts"][key] = {
                    "mime_type": art.inline_data.mime_type,
                    "data_size": len(art.inline_data.data) if art.inline_data.data else 0,
                    "display_name": getattr(art.inline_data, "display_name", None),
                }
    except Exception as e:
        result["artifacts_error"] = str(e)

    # Inspect user_content
    uc = tool_context.user_content
    if uc and uc.parts:
        parts_info = []
        for i, part in enumerate(uc.parts):
            info = {"index": i}
            if part.text:
                info["type"] = "text"
                info["text_preview"] = part.text[:200]
            if hasattr(part, "inline_data") and part.inline_data:
                info["type"] = "inline_data"
                info["mime_type"] = part.inline_data.mime_type
                info["data_size"] = len(part.inline_data.data) if part.inline_data.data else 0
                info["display_name"] = getattr(part.inline_data, "display_name", None)
            if hasattr(part, "file_data") and part.file_data:
                info["type"] = "file_data"
                info["file_uri"] = part.file_data.file_uri
                info["mime_type"] = part.file_data.mime_type
                info["display_name"] = getattr(part.file_data, "display_name", None)
            # Dump all non-None attributes
            raw = {}
            for attr in ["text", "inline_data", "file_data", "function_call", "function_response"]:
                val = getattr(part, attr, None)
                if val is not None:
                    raw[attr] = str(val)[:300]
            info["raw_attrs"] = raw
            parts_info.append(info)
        result["user_content"] = {"num_parts": len(uc.parts), "parts": parts_info}
    else:
        result["user_content"] = "empty or no parts"

    # Inspect last 5 user events in session
    try:
        events = tool_context.session.events
        if events:
            count = 0
            for event in reversed(events):
                if event.author == "user" and event.content and event.content.parts:
                    evt_info = {"event_author": event.author, "parts": []}
                    for i, part in enumerate(event.content.parts):
                        info = {"index": i}
                        if part.text:
                            info["type"] = "text"
                            info["text_preview"] = part.text[:200]
                        if hasattr(part, "inline_data") and part.inline_data:
                            info["type"] = "inline_data"
                            info["mime_type"] = part.inline_data.mime_type
                            info["data_size"] = len(part.inline_data.data) if part.inline_data.data else 0
                        if hasattr(part, "file_data") and part.file_data:
                            info["type"] = "file_data"
                            info["file_uri"] = part.file_data.file_uri
                            info["mime_type"] = part.file_data.mime_type
                        evt_info["parts"].append(info)
                    result["session_events"].append(evt_info)
                    count += 1
                    if count >= 5:
                        break
            result["total_events"] = len(events)
    except Exception as e:
        result["session_events_error"] = str(e)

    logger.info(f"DEBUG CONTEXT: {result}")
    return result


async def upload_document(tool_context: ToolContext, file_path: str = "") -> dict:
    """Upload a medical document (PDF) to the backend for processing.

    Accepts either a directly uploaded file from the ADK/Gemini UI or a local file path.

    Args:
        tool_context: The ADK tool context (automatically provided).
        file_path: Optional local file path. Leave empty when user uploads directly.

    Returns:
        dict with upload status and extracted page info.
    """
    logger.info(f"upload_document called, file_path='{file_path}'")
    try:
        file_bytes = None
        file_name = "document.pdf"
        mime_type = "application/pdf"

        # Priority 1: uploaded file from ADK/Gemini context
        file_bytes, file_name = await _extract_file_from_context(tool_context)
        if file_bytes:
            logger.info(f"Using file from context: {file_name}, {len(file_bytes)} bytes")
            ext = os.path.splitext(file_name)[1].lower()
            mime_type = "text/csv" if ext == ".csv" else "application/pdf"

        # Priority 2: local file path
        elif file_path:
            logger.info(f"Using file from path: {file_path}")
            file_name = os.path.basename(file_path)
            ext = os.path.splitext(file_name)[1].lower()
            mime_type = "text/csv" if ext == ".csv" else "application/pdf"
            with open(file_path, "rb") as f:
                file_bytes = f.read()

        else:
            return {"error": "No file found. Please upload a PDF file directly or provide a file path."}

        logger.info(f"Uploading {file_name} ({len(file_bytes)} bytes) to backend")
        files = {"file": (file_name, io.BytesIO(file_bytes), mime_type)}
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(f"{BACKEND_URL}/api/upload-document", files=files)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"upload_document failed: {e}")
        return {"error": str(e)}


async def upload_disclaimers(tool_context: ToolContext, file_path: str = "") -> dict:
    """Upload disclaimer/reference files (CSV/PDF) used for validation.

    Accepts either a directly uploaded file from the ADK/Gemini UI or a local file path.

    Args:
        tool_context: The ADK tool context (automatically provided).
        file_path: Optional local file path. Leave empty when user uploads directly.

    Returns:
        dict with upload status.
    """
    logger.info(f"upload_disclaimers called, file_path='{file_path}'")
    try:
        file_bytes, file_name = await _extract_file_from_context(tool_context)

        if not file_bytes and file_path:
            file_name = os.path.basename(file_path)
            with open(file_path, "rb") as f:
                file_bytes = f.read()

        if not file_bytes:
            return {"error": "No file found. Please upload a disclaimer file directly or provide a file path."}

        content_type = "text/csv" if file_name.endswith(".csv") else "application/pdf"
        files = {"file": (file_name, io.BytesIO(file_bytes), content_type)}
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(f"{BACKEND_URL}/api/upload-disclaimers", files=files)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"upload_disclaimers failed: {e}")
        return {"error": str(e)}


async def validate_document(
    model_name: str = "gemini-2.0-flash",
    enable_ocr: bool = True,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    top_k_results: int = 8,
    embedding_model: str = "sentence-transformers/all-mpnet-base-v2",
) -> dict:
    """Run MLR validation on the previously uploaded document.

    Returns:
        dict with page-by-page validation results.
    """
    logger.info("Running document validation")
    try:
        config = {
            "model_name": model_name,
            "enable_ocr": enable_ocr,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "top_k_results": top_k_results,
            "embedding_model": embedding_model,
        }
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(f"{BACKEND_URL}/api/validate", json=config)
            resp.raise_for_status()
            data = resp.json()
            if "results" in data and isinstance(data["results"], list):
                for page_result in data["results"]:
                    if isinstance(page_result, dict):
                        page_result.pop("page_image_base64", None)
            return data
    except Exception as e:
        logger.error(f"validate_document failed: {e}")
        return {"error": str(e)}


async def claim_review(tool_context: ToolContext, file_path: str = "") -> dict:
    """Run full MLR claim review using the library vectorstore.

    Accepts either a directly uploaded file from the ADK/Gemini UI or a local file path.

    Args:
        tool_context: The ADK tool context (automatically provided).
        file_path: Optional local file path. Leave empty when user uploads directly.

    Returns:
        dict with claim review results.
    """
    logger.info(f"claim_review called, file_path='{file_path}'")
    try:
        file_bytes, file_name = await _extract_file_from_context(tool_context)

        if not file_bytes and file_path:
            file_name = os.path.basename(file_path)
            with open(file_path, "rb") as f:
                file_bytes = f.read()

        if not file_bytes:
            return {"error": "No file found. Please upload a file directly or provide a file path."}

        content_type = "application/pdf" if file_name.endswith(".pdf") else "application/json"
        files = {"input_file": (file_name, io.BytesIO(file_bytes), content_type)}
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(f"{BACKEND_URL}/api/claim/review-library", files=files)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"claim_review failed: {e}")
        return {"error": str(e)}


async def reset_backend() -> dict:
    """Reset the backend state, clearing all uploaded documents and results."""
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(f"{BACKEND_URL}/api/reset")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e)}


async def get_health() -> dict:
    """Check backend health status."""
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{BACKEND_URL}/health")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e)}


async def get_dashboard_stats() -> dict:
    """Get dashboard KPIs including document counts, pages processed, and time stats."""
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{BACKEND_URL}/api/dashboard/stats")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e)}


async def chat_with_backend(query: str, session_id: str = "default") -> dict:
    """Chat with the MLR backend about uploaded documents and validation results.

    Args:
        query: The user's question or message.
        session_id: Session identifier for conversation continuity.

    Returns:
        dict with the chat reply.
    """
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(
                f"{BACKEND_URL}/api/chat",
                json={"query": query, "session_id": session_id},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e)}


# ── Agent ─────────────────────────────────────────────────────────────────────

root_agent = Agent(
    model=model,
    name="MLR_Document_Validator_Agent",
    description="An intelligent Medical/Legal/Regulatory (MLR) document validation agent that parses, uploads, and validates compliance documents.",
    instruction="""
    You are an MLR (Medical, Legal, Regulatory) Document Validation Agent.
    You help users validate medical promotional documents for regulatory compliance.

    ## Workflow

    When a user uploads a document or provides a file path, follow this sequence:

    1. Call `upload_document` — if the user uploaded a file directly, call with NO
       file_path (the file is extracted automatically from the conversation context).
       If the user provided a file system path, pass it as file_path.
    2. Immediately call `validate_document` in the SAME turn.
    3. Return the validation results.
    4. Do NOT ask "what would you like to do next?" — this is ONE atomic operation.

    ## Tool Usage

    | User Intent                          | Tool Sequence                                    |
    |--------------------------------------|--------------------------------------------------|
    | Upload a document for review         | `upload_document` → `validate_document`          |
    | Upload disclaimer/reference files    | `upload_disclaimers`                             |
    | Full claim review with library       | `claim_review`                                   |
    | Ask questions about results          | `chat_with_backend`                              |
    | Check system health                  | `get_health`                                     |
    | Get dashboard statistics             | `get_dashboard_stats`                            |
    | Clear/reset all data                 | `reset_backend`                                  |

    ## File Handling

    - When a user uploads a file directly in the chat, call the tool with NO
      file_path — the file is extracted automatically from the conversation context
    - Only pass file_path if the user explicitly provides a file system path
    - Supported formats: PDF, images (PNG/JPG), plain text, CSV (for disclaimers)

    ## Response Format

    - Present validation findings in a structured, readable format
    - Highlight flagged pages, missing disclaimers, and compliance issues
    - If any step fails, report the error and suggest next steps

    ## Boundaries

    - Only handle MLR document validation tasks
    - Do not provide medical or legal advice
    - Politely decline out-of-scope requests
    """,
    tools=[
        debug_context,
        upload_document,
        upload_disclaimers,
        validate_document,
        claim_review,
        reset_backend,
        get_health,
        get_dashboard_stats,
        chat_with_backend,
    ],
)

logger.info("MLR_Document_Validator_Agent created successfully")
