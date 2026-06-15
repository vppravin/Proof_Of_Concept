# File Upload Handling in Gemini Enterprise (Vertex AI Agent Engine)

## Complete Guide for ADK Agents

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture — How File Uploads Work](#architecture)
3. [The Artifact Service](#the-artifact-service)
4. [Implementation Guide](#implementation-guide)
5. [Complete Sample Code](#complete-sample-code)
6. [Multi-File Upload Handling](#multi-file-upload-handling)
7. [Agent Instructions](#agent-instructions)
8. [Deployment Configuration](#deployment-configuration)
9. [Testing Strategy](#testing-strategy)
10. [Troubleshooting](#troubleshooting)
11. [Prerequisites & Support Ticket](#prerequisites)

---

## Overview <a name="overview"></a>

When users upload files through the **Gemini Enterprise UI** (Google Cloud Console)
to a custom ADK agent deployed on **Vertex AI Agent Engine**, the files are NOT
passed directly in `tool_context.user_content.parts`. Instead, they are stored
in the **ADK Artifact Service** and must be retrieved using `load_artifact()`.

This is different from the **ADK Dev UI** (local testing) where files arrive as
`inline_data` in `user_content.parts`.

---

## Architecture — How File Uploads Work <a name="architecture"></a>

### Gemini Enterprise (Production — Deployed Agent)

```
User uploads file(s) via Gemini UI
    │
    ├──→ file_and_coding_agent (internal Gemini component)
    │       │
    │       ├── Processes file for Gemini's own understanding
    │       │   (text extraction, image conversion, summarization)
    │       │
    │       └── Stores ORIGINAL binary in ADK Artifact Service
    │           (requires allowlist — see Prerequisites section)
    │
    └──→ Your Custom ADK Agent receives the text message
            │
            ├── tool_context.user_content.parts → contains ONLY text
            │   (file is NOT here)
            │
            ├── tool_context.list_artifacts() → returns artifact keys
            │   e.g. ["Disclaimer Library.pdf", "mlr_input.pdf"]
            │
            └── tool_context.load_artifact("mlr_input.pdf")
                → returns types.Part with inline_data containing raw bytes
```

### ADK Dev UI (Local Testing)

```
User uploads file via ADK Dev UI
    │
    └──→ Your Custom ADK Agent
            │
            └── tool_context.user_content.parts[i].inline_data.data
                → raw bytes directly available
```

### Key Difference

| Environment | Where file lives | How to access |
|---|---|---|
| Gemini Enterprise (deployed) | Artifact Service | `list_artifacts()` + `load_artifact(key)` |
| ADK Dev UI (local) | `user_content.parts` | `part.inline_data.data` |

Your code must handle **both** paths to work in both environments.

---

## The Artifact Service <a name="the-artifact-service"></a>

### What is it?

The ADK Artifact Service is a session-scoped storage system that persists binary
data (files, images, etc.) across turns within a conversation session.

### Key APIs

```python
from google.adk.tools import ToolContext

# List all artifact keys in the current session
keys: list[str] = await tool_context.list_artifacts()
# Returns: ["filename1.pdf", "filename2.csv", ...]

# Load a specific artifact by key
part: types.Part = await tool_context.load_artifact("filename.pdf")
# Returns a types.Part object with:
#   part.inline_data.data       → bytes (the raw file binary)
#   part.inline_data.mime_type  → str (e.g. "application/pdf")
#   part.inline_data.display_name → str or None

# Save an artifact (if you need to store something for later)
version: int = await tool_context.save_artifact("key_name", part)

# Get artifact version info
version: int = await tool_context.get_artifact_version("key_name")
```

### How Gemini Stores Uploaded Files

When a user uploads a file through Gemini Enterprise UI:
1. The platform assigns the **original filename** as the artifact key
2. The file binary is stored as `inline_data` within the artifact
3. The artifact is scoped to the current session
4. Multiple files = multiple artifacts with different keys

---

## Implementation Guide <a name="implementation-guide"></a>

### Step 1: Create the File Extraction Helper

This helper handles both environments (Gemini Enterprise + ADK Dev UI):

```python
async def _extract_file_from_context(tool_context: ToolContext) -> tuple:
    """Extract file bytes from the tool context.

    Priority:
    1. ADK Artifact Service (Gemini Enterprise)
    2. inline_data in user_content.parts (ADK Dev UI)
    3. file_data URI in user_content.parts (GCS/HTTP)
    4. Session history fallback

    Returns:
        tuple of (file_bytes, file_name) or (None, None)
    """
```

### Step 2: Use it in Your Tools

```python
async def upload_document(tool_context: ToolContext, file_path: str = "") -> dict:
    file_bytes, file_name = await _extract_file_from_context(tool_context)
    if not file_bytes and file_path:
        # Fallback to local file path
        ...
    if not file_bytes:
        return {"error": "No file found."}
    # Send to your backend
    ...
```

### Step 3: Configure Agent Instructions

Tell the LLM to call tools with NO file_path when users upload directly.

---

## Complete Sample Code <a name="complete-sample-code"></a>

```python
import io
import os
import logging
from typing import Any, Dict

import google.auth
import httpx
from google.adk.agents import Agent
from google.adk.tools import ToolContext
from google.genai import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv("BACKEND_URL", "https://your-backend.run.app")
TIMEOUT = 300


# ═══════════════════════════════════════════════════════════════════════════════
# FILE EXTRACTION HELPER
# ═══════════════════════════════════════════════════════════════════════════════


async def _extract_file_from_context(
    tool_context: ToolContext,
    target_filename: str = "",
) -> tuple:
    """Extract file bytes and filename from the tool context.

    Handles both Gemini Enterprise (artifact service) and ADK Dev UI (inline_data).

    Args:
        tool_context: The ADK tool context (automatically provided).
        target_filename: Optional. If provided, looks for a specific file by name.
                        Useful for multi-file scenarios.

    Returns:
        tuple of (file_bytes: bytes, file_name: str) or (None, None) if not found.
    """

    # ─── Priority 1: ADK Artifact Service (Gemini Enterprise) ───────────────
    try:
        artifact_keys = await tool_context.list_artifacts()
        logger.info(f"Artifacts available: {artifact_keys}")

        if artifact_keys:
            # If a specific filename is requested, look for it
            if target_filename:
                matching_keys = [
                    k for k in artifact_keys
                    if target_filename.lower() in k.lower()
                ]
                keys_to_try = matching_keys or artifact_keys
            else:
                keys_to_try = artifact_keys

            for key in keys_to_try:
                artifact_part = await tool_context.load_artifact(key)
                if (
                    artifact_part
                    and artifact_part.inline_data
                    and artifact_part.inline_data.data
                ):
                    data = artifact_part.inline_data.data
                    if len(data) > 100:  # Skip empty/corrupted artifacts
                        name = (
                            getattr(artifact_part.inline_data, "display_name", None)
                            or key
                        )
                        logger.info(
                            f"Loaded artifact '{key}': {name}, {len(data)} bytes"
                        )
                        return data, name
    except Exception as e:
        logger.warning(f"Artifact load failed: {e}")

    # ─── Priority 2: inline_data in user_content.parts (ADK Dev UI) ─────────
    uc = tool_context.user_content
    if uc and uc.parts:
        for part in uc.parts:
            if (
                hasattr(part, "inline_data")
                and part.inline_data
                and part.inline_data.data
            ):
                if len(part.inline_data.data) > 100:
                    name = (
                        getattr(part.inline_data, "display_name", None)
                        or "document.pdf"
                    )
                    logger.info(f"Found inline_data: {name}, {len(part.inline_data.data)} bytes")
                    return part.inline_data.data, name

    # ─── Priority 3: file_data URI (GCS or HTTP) ───────────────────────────
    if uc and uc.parts:
        for part in uc.parts:
            if (
                hasattr(part, "file_data")
                and part.file_data
                and part.file_data.file_uri
            ):
                uri = part.file_data.file_uri
                name = (
                    getattr(part.file_data, "display_name", None)
                    or uri.split("/")[-1]
                    or "document.pdf"
                )
                logger.info(f"Found file_data URI: {uri}")

                if uri.startswith("gs://"):
                    from google.cloud import storage as gcs
                    uri_parts = uri.replace("gs://", "").split("/", 1)
                    blob = gcs.Client().bucket(uri_parts[0]).blob(uri_parts[1])
                    return blob.download_as_bytes(), name
                else:
                    import google.auth.transport.requests
                    creds, _ = google.auth.default()
                    creds.refresh(google.auth.transport.requests.Request())
                    resp = httpx.get(
                        uri,
                        headers={"Authorization": f"Bearer {creds.token}"},
                        timeout=TIMEOUT,
                    )
                    resp.raise_for_status()
                    return resp.content, name

    # ─── Priority 4: Session history (most recent user turn with file) ──────
    try:
        for event in reversed(tool_context.session.events):
            if event.author == "user" and event.content and event.content.parts:
                for part in event.content.parts:
                    if (
                        hasattr(part, "inline_data")
                        and part.inline_data
                        and part.inline_data.data
                        and len(part.inline_data.data) > 100
                    ):
                        name = (
                            getattr(part.inline_data, "display_name", None)
                            or "document.pdf"
                        )
                        return part.inline_data.data, name
    except Exception as e:
        logger.warning(f"Session scan failed: {e}")

    return None, None


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS
# ═══════════════════════════════════════════════════════════════════════════════


async def upload_document(tool_context: ToolContext, file_path: str = "") -> dict:
    """Upload a document to the backend for processing.

    The file is automatically extracted from the upload context.
    Only provide file_path if the user explicitly gives a file system path.

    Args:
        tool_context: The ADK tool context (automatically provided).
        file_path: Optional local file path fallback.

    Returns:
        dict with upload status.
    """
    file_bytes = None
    file_name = "document.pdf"

    # Try extracting from context (artifacts → inline_data → file_data)
    file_bytes, file_name = await _extract_file_from_context(tool_context)

    # Fallback: local file path
    if not file_bytes and file_path:
        file_name = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            file_bytes = f.read()

    if not file_bytes:
        return {"error": "No file found. Please upload a file or provide a file path."}

    # Send raw binary to backend
    mime_type = "text/csv" if file_name.endswith(".csv") else "application/pdf"
    files = {"file": (file_name, io.BytesIO(file_bytes), mime_type)}
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.post(f"{BACKEND_URL}/api/upload-document", files=files)
        resp.raise_for_status()
        return resp.json()


async def debug_context(tool_context: ToolContext) -> dict:
    """Debug tool: inspect what files are available in the current context.

    Returns detailed information about artifacts, user_content parts,
    and session events.
    """
    result = {"artifacts": {}, "user_content": None, "session_events_with_files": 0}

    # Check artifacts
    try:
        keys = await tool_context.list_artifacts()
        result["artifacts"]["keys"] = keys
        for key in (keys or []):
            art = await tool_context.load_artifact(key)
            if art and art.inline_data:
                result["artifacts"][key] = {
                    "mime_type": art.inline_data.mime_type,
                    "data_size_bytes": len(art.inline_data.data) if art.inline_data.data else 0,
                    "display_name": getattr(art.inline_data, "display_name", None),
                }
    except Exception as e:
        result["artifacts_error"] = str(e)

    # Check user_content
    uc = tool_context.user_content
    if uc and uc.parts:
        parts_info = []
        for i, part in enumerate(uc.parts):
            info = {"index": i}
            if part.text:
                info["type"] = "text"
                info["preview"] = part.text[:100]
            if hasattr(part, "inline_data") and part.inline_data:
                info["type"] = "inline_data"
                info["mime_type"] = part.inline_data.mime_type
                info["size"] = len(part.inline_data.data) if part.inline_data.data else 0
            if hasattr(part, "file_data") and part.file_data:
                info["type"] = "file_data"
                info["uri"] = part.file_data.file_uri
            parts_info.append(info)
        result["user_content"] = {"num_parts": len(uc.parts), "parts": parts_info}

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT
# ═══════════════════════════════════════════════════════════════════════════════


root_agent = Agent(
    model="gemini-2.0-flash",
    name="Your_Agent",
    description="Your agent description.",
    instruction="""
    ## File Handling — CRITICAL

    - When a user uploads a file directly in the chat, call the tool with NO
      file_path parameter. The file is automatically extracted from the
      artifact service.
    - Only pass file_path if the user explicitly types a file system path.
    - For multiple files, call each tool separately — the agent will find
      the correct file by name from the artifacts.
    """,
    tools=[upload_document, debug_context],
)
```

---

## Multi-File Upload Handling <a name="multi-file-upload-handling"></a>

When a user uploads multiple files, each file is stored as a **separate artifact**
with its original filename as the key.

### Example: 2 files uploaded

```python
artifact_keys = await tool_context.list_artifacts()
# Returns: ["Disclaimer Library.pdf", "mlr_input.pdf"]
```

### Targeting a Specific File

Use the `target_filename` parameter in `_extract_file_from_context`:

```python
async def upload_document(tool_context: ToolContext, file_path: str = "") -> dict:
    """Upload the main document (not disclaimers)."""
    # Look for a file that's NOT a disclaimer
    file_bytes, file_name = await _extract_file_from_context(
        tool_context, target_filename="mlr"  # partial match
    )
    ...

async def upload_disclaimers(tool_context: ToolContext, file_path: str = "") -> dict:
    """Upload disclaimer files."""
    # Look specifically for disclaimer files
    file_bytes, file_name = await _extract_file_from_context(
        tool_context, target_filename="disclaimer"  # partial match
    )
    ...
```

### Alternative: Let the LLM Decide

The agent's LLM can read the artifact keys and decide which file goes where
based on the filenames. Update your agent instruction:

```
When multiple files are uploaded:
1. Call list_artifacts to see available files
2. Match files to tools by filename:
   - Files with "disclaimer" in the name → upload_disclaimers
   - All other PDFs → upload_document
3. Call each tool in sequence
```

---

## Agent Instructions <a name="agent-instructions"></a>

### Minimal Instruction (Single File)

```python
instruction = """
When a user uploads a file, call `upload_document` with NO file_path.
The file is extracted automatically from the conversation context.
"""
```

### Full Instruction (Multi-File + Validation)

```python
instruction = """
You are a document processing agent.

## File Handling

- When a user uploads file(s) directly, call tools with NO file_path.
  Files are automatically extracted from the artifact service.
- Only pass file_path if the user explicitly provides a file system path.

## Workflow

1. User uploads document → call `upload_document` → call `validate_document`
2. User uploads disclaimers → call `upload_disclaimers`
3. User uploads both → call `upload_disclaimers` first, then `upload_document` → `validate_document`

## Multi-File Routing

When multiple files are uploaded:
- Files with "disclaimer" in the name → `upload_disclaimers`
- Other PDF files → `upload_document`
"""
```

---

## Deployment Configuration <a name="deployment-configuration"></a>

### requirements.txt

```
google-cloud-aiplatform[agent_engines,adk]
google-cloud-storage
google-genai>=1.69.0
python-dotenv
httpx
```

### deploy.py

```python
import vertexai
from vertexai import agent_engines
from your_agent.agent import root_agent

PROJECT = "your-project-id"
LOCATION = "us-central1"
BUCKET = "gs://your-bucket"

client = vertexai.Client(project=PROJECT, location=LOCATION)
app = agent_engines.AdkApp(agent=root_agent, enable_tracing=True)

remote_agent = client.agent_engines.create(
    agent=app,
    config={
        "requirements": [
            "google-cloud-aiplatform[agent_engines,adk]",
            "google-cloud-storage",
            "google-genai>=1.69.0",
            "python-dotenv",
            "httpx",
        ],
        "stagingBucket": BUCKET,
        "extraPackages": ["./your_agent/"],
        "displayName": "Your_Agent",
        "envVars": {
            "BACKEND_URL": "https://your-backend.run.app",
        },
        "pythonVersion": "3.11",
    },
)

print(f"Deployed: {remote_agent.api_resource.name}")
```

### update.py (Update Existing Engine)

```python
import vertexai
from vertexai import agent_engines
from your_agent.agent import root_agent

PROJECT = "your-project-id"
LOCATION = "us-central1"
BUCKET = "gs://your-bucket"
RESOURCE_NAME = "projects/PROJECT_NUM/locations/LOCATION/reasoningEngines/ENGINE_ID"

client = vertexai.Client(project=PROJECT, location=LOCATION)
app = agent_engines.AdkApp(agent=root_agent, enable_tracing=True)

remote_agent = client.agent_engines.update(
    name=RESOURCE_NAME,
    agent=app,
    config={
        "requirements": [...],
        "stagingBucket": BUCKET,
        "extraPackages": ["./your_agent/"],
        "displayName": "Your_Agent",
        "envVars": {...},
        "pythonVersion": "3.11",
    },
)
```

---

## Testing Strategy <a name="testing-strategy"></a>

### 1. Local Testing (ADK Dev UI)

```bash
cd your_project/agent
adk web
```

Upload a file → it arrives as `inline_data` in `user_content.parts`.

### 2. Deployed Testing (Gemini Enterprise)

1. Deploy agent to Vertex AI Agent Engine
2. Go to Google Cloud Console → Vertex AI → Agent Engine
3. Open your agent in the Gemini UI
4. Upload file + type your command
5. File arrives in the **Artifact Service**

### 3. Debug Tool

Always include a `debug_context` tool during development:

```python
async def debug_context(tool_context: ToolContext) -> dict:
    keys = await tool_context.list_artifacts()
    result = {"artifacts": keys}
    for key in (keys or []):
        art = await tool_context.load_artifact(key)
        if art and art.inline_data:
            result[key] = {
                "size": len(art.inline_data.data) if art.inline_data.data else 0,
                "mime": art.inline_data.mime_type,
            }
    return result
```

Upload a file and type "debug context" to verify files are arriving correctly.

---

## Troubleshooting <a name="troubleshooting"></a>

| Symptom | Cause | Fix |
|---------|-------|-----|
| `list_artifacts()` returns empty list | Allowlist not applied | Raise Google Cloud Support ticket |
| `inline_data` is None or empty | Artifact corrupted | Check artifact key spelling |
| Works in ADK UI but not Gemini | Different file delivery mechanism | Ensure code handles both artifacts AND inline_data |
| LLM hallucinates `/tmp/file.pdf` | Agent instruction missing | Add "call with NO file_path" to instruction |
| `load_artifact` raises ValueError | Artifact service not initialized | Ensure `enable_tracing=True` in AdkApp |
| File found but wrong one picked | Multi-file without targeting | Use `target_filename` parameter |
| Agent not called at all | Gemini handling request itself | Ensure agent is tagged with @ in Gemini UI |

---

## Prerequisites & Support Ticket <a name="prerequisites"></a>

### Allowlist Requirement

For the Artifact Service to receive the **original file binary** (not a
processed version), your Reasoning Engine must be **allowlisted** by the
Google Cloud product team.

### How to Request

1. Go to Google Cloud Console → Support → Create Case
2. Provide:
   - Project ID
   - Reasoning Engine resource name
   - Explain: "Our custom ADK agent needs access to the original uploaded
     file binary through the artifact service. The file_and_coding_agent
     is currently consuming the file before our agent can access it."
3. Request: "Please apply the allowlist for the remote agent feature on
   our Reasoning Engine."

### What the Allowlist Does

- The `file_and_coding_agent` still runs (handles routing)
- But the **original binary** is now stored in the Artifact Service
- Your agent retrieves it via `load_artifact()`

---

## Summary — The Complete Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    GEMINI ENTERPRISE UI                       │
│                                                              │
│  User: [uploads file.pdf] "Upload and validate"              │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              file_and_coding_agent (internal)                 │
│                                                              │
│  1. Processes file for Gemini's understanding                │
│  2. Stores original binary → Artifact Service (allowlist)    │
│  3. Routes text message to your custom agent                 │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              YOUR CUSTOM ADK AGENT                            │
│                                                              │
│  tool_context.user_content.parts = [Part(text="Upload...")]  │
│                                                              │
│  await tool_context.list_artifacts()                         │
│  → ["file.pdf"]                                              │
│                                                              │
│  await tool_context.load_artifact("file.pdf")                │
│  → Part(inline_data=Blob(data=b'%PDF...', mime='app/pdf'))   │
│                                                              │
│  Send raw bytes to backend → Process → Return results        │
└─────────────────────────────────────────────────────────────┘
```

---

