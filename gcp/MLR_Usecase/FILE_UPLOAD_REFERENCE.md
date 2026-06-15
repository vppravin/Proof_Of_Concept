# Handling File Uploads in Google ADK Agents on Vertex AI / Gemini

## Overview

When deploying ADK agents on Vertex AI Agent Engine and using them through the
Gemini UI, uploaded files go through an internal `file_and_coding_agent` that
pre-processes files (converts PDFs to images, extracts text, etc.). This
**destroys the original binary** by default.

To preserve the original file binary, a **backend allowlist** must be enabled
by Google Cloud Support for your agent engine. Once enabled, the original file
is available alongside the processed version.

## Prerequisites

1. **Raise a Google Cloud Support ticket** requesting the allowlist for your
   specific Reasoning Engine resource. Provide:
   - Project ID
   - Reasoning Engine resource name (e.g. `projects/PROJECT_NUM/locations/REGION/reasoningEngines/ENGINE_ID`)
   - Explain that your agent needs access to the original file binary

2. **Wait for confirmation** that the allowlist is applied.

## How Files Arrive in Your Agent

After the allowlist, uploaded files arrive in `tool_context` in two possible forms:

### Small files → `inline_data` (raw bytes in memory)
```
tool_context.user_content.parts[i].inline_data.data       → bytes
tool_context.user_content.parts[i].inline_data.mime_type   → "application/pdf"
tool_context.user_content.parts[i].inline_data.display_name → filename or None
```

### Large files → `file_data` (GCS URI)
```
tool_context.user_content.parts[i].file_data.file_uri   → "gs://bucket/path/file.pdf"
tool_context.user_content.parts[i].file_data.mime_type   → "application/pdf"
tool_context.user_content.parts[i].file_data.display_name → filename or None
```

### ADK UI (local testing) → always `inline_data`

## Reference Implementation

### Core Helper: Extract File from Context

```python
import os
import logging
import google.auth
import httpx
from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)
TIMEOUT = 300


def _extract_file_from_context(tool_context: ToolContext) -> tuple:
    """Extract raw file bytes and filename from ADK user content or session events.

    Handles:
    - inline_data bytes  (ADK UI / small files on Gemini)
    - file_data gs:// URI (Gemini / Vertex AI Agent Engine — large files)
    - file_data HTTP URI  (Gemini File API)

    Returns:
        tuple of (file_bytes, file_name) or (None, None) if no file found.
    """
    def _from_parts(parts):
        if not parts:
            return None, None
        for part in parts:
            # Case 1: inline bytes (ADK UI / small files)
            if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                if len(part.inline_data.data) > 100:
                    name = getattr(part.inline_data, "display_name", None) or "document.pdf"
                    logger.info(f"Found inline_data: {name}, {len(part.inline_data.data)} bytes")
                    return part.inline_data.data, name

            # Case 2: file URI (Gemini / Vertex AI — GCS or HTTP)
            if hasattr(part, "file_data") and part.file_data and part.file_data.file_uri:
                uri = part.file_data.file_uri
                mime = part.file_data.mime_type or "application/pdf"
                name = getattr(part.file_data, "display_name", None)
                if not name:
                    name = uri.split("/")[-1] if "/" in uri else "document.pdf"
                logger.info(f"Found file_data URI: {uri}, mime: {mime}, name: {name}")

                file_bytes = None
                if uri.startswith("gs://"):
                    # Download from Google Cloud Storage
                    from google.cloud import storage as gcs
                    uri_parts = uri.replace("gs://", "").split("/", 1)
                    blob = gcs.Client().bucket(uri_parts[0]).blob(uri_parts[1])
                    file_bytes = blob.download_as_bytes()
                    logger.info(f"Downloaded from GCS: {len(file_bytes)} bytes")
                else:
                    # Authenticated HTTP download (e.g. Gemini File API URI)
                    import google.auth.transport.requests
                    creds, _ = google.auth.default()
                    creds.refresh(google.auth.transport.requests.Request())
                    resp = httpx.get(
                        uri,
                        headers={"Authorization": f"Bearer {creds.token}"},
                        timeout=TIMEOUT,
                    )
                    resp.raise_for_status()
                    file_bytes = resp.content
                    logger.info(f"Downloaded from HTTP: {len(file_bytes)} bytes")

                if file_bytes and len(file_bytes) > 100:
                    return file_bytes, name

        return None, None

    # 1. Check current turn
    uc = tool_context.user_content
    if uc and uc.parts:
        file_bytes, file_name = _from_parts(uc.parts)
        if file_bytes:
            return file_bytes, file_name

    # 2. Search session history (most recent first)
    try:
        for event in reversed(tool_context.session.events):
            if event.author == "user" and event.content and event.content.parts:
                file_bytes, file_name = _from_parts(event.content.parts)
                if file_bytes:
                    return file_bytes, file_name
    except Exception as e:
        logger.warning(f"Session scan failed: {e}")

    return None, None
```

### Using It in a Tool

```python
import io
import httpx
from google.adk.tools import ToolContext

BACKEND_URL = "https://your-backend.run.app"


async def upload_document(tool_context: ToolContext, file_path: str = "") -> dict:
    """Upload a document to the backend.

    Accepts either:
    - A directly uploaded file from ADK/Gemini UI (no file_path needed)
    - A local file path as fallback

    Args:
        tool_context: The ADK tool context (automatically provided).
        file_path: Optional local file path. Leave empty when user uploads directly.
    """
    file_bytes = None
    file_name = "document.pdf"

    # Priority 1: uploaded file from ADK/Gemini context
    file_bytes, file_name = _extract_file_from_context(tool_context)

    # Priority 2: local file path fallback
    if not file_bytes and file_path:
        file_name = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            file_bytes = f.read()

    if not file_bytes:
        return {"error": "No file found. Please upload a file or provide a file path."}

    # Send raw binary to backend
    mime_type = "text/csv" if file_name.endswith(".csv") else "application/pdf"
    files = {"file": (file_name, io.BytesIO(file_bytes), mime_type)}
    with httpx.Client(timeout=300) as client:
        resp = client.post(f"{BACKEND_URL}/api/upload", files=files)
        resp.raise_for_status()
        return resp.json()
```

### Agent Instruction (Key Part)

```python
from google.adk.agents import Agent

root_agent = Agent(
    model="gemini-2.0-flash",
    name="Your_Agent",
    instruction="""
    ## File Handling

    - When a user uploads a file directly in the chat, call `upload_document`
      with NO file_path — the file is extracted automatically from the
      conversation context
    - Only pass file_path if the user explicitly provides a file system path
    """,
    tools=[upload_document],
)
```

### Requirements

```
google-cloud-aiplatform[agent_engines,adk]
google-cloud-storage          # needed for GCS URI downloads
google-genai>=1.69.0
httpx
python-dotenv
```

### Deploy Config

```python
config = {
    "requirements": [
        "google-cloud-aiplatform[agent_engines,adk]",
        "google-cloud-storage",
        "google-genai>=1.69.0",
        "httpx",
        "python-dotenv",
    ],
    "stagingBucket": "gs://your-bucket",
    "extraPackages": ["./your_agent/"],
    "displayName": "Your_Agent",
    "envVars": {
        "BACKEND_URL": "https://your-backend.run.app",
    },
    "pythonVersion": "3.11",
}
```

## Architecture Diagram

```
User uploads file via Gemini UI
    │
    ├──→ file_and_coding_agent (always runs)
    │       │
    │       ├── Extracts text, converts to images
    │       └── Gemini uses this for its own understanding
    │
    └──→ Preserved original binary (requires allowlist)
            │
            ├── Small file → inline_data.data (raw bytes)
            │
            └── Large file → file_data.file_uri (gs:// URI)
                    │
                    └── Your agent downloads via google.cloud.storage
            │
            └── Your agent's tool picks this up
                    → _extract_file_from_context(tool_context)
                    → sends raw bytes to your backend
```

## Checklist for New Agents

- [ ] Raise support ticket for allowlist on the new Reasoning Engine
- [ ] Include `google-cloud-storage` in requirements
- [ ] Use `_extract_file_from_context()` in all file-consuming tools
- [ ] Agent instruction tells LLM to call tool with NO file_path for direct uploads
- [ ] Test on ADK UI first (inline_data), then deploy and test on Gemini (file_data)
- [ ] Confirm with support: is allowlist per-engine or per-project?

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `inline_data` is empty or < 100 bytes | Allowlist not applied | Raise support ticket |
| `file_data.file_uri` returns 403 | Service account lacks GCS access | Grant `storage.objectViewer` role |
| LLM hallucinates `/tmp/document.pdf` | Agent instruction missing | Add "call with NO file_path" to instruction |
| File found in session history but not current turn | Multi-turn delay | The helper searches history automatically |
| Works in ADK UI but not Gemini | Allowlist is per-engine | Confirm engine ID is allowlisted |
```
