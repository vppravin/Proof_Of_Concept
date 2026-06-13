"""Tool callbacks for agent event logging."""

import json
import logging
from datetime import datetime, timezone
from google.cloud import storage as gcs_storage

logger = logging.getLogger(__name__)

_trace_folder = {"value": ""}


def _write_event(event: dict):
    folder = _trace_folder.get("value", "")
    if not folder:
        return
    try:
        client = gcs_storage.Client()
        bucket_name = folder.split("/")[2]
        prefix = folder.replace(f"gs://{bucket_name}/", "").strip("/")
        blob = client.bucket(bucket_name).blob(f"{prefix}/_events.jsonl")
        existing = blob.download_as_text() if blob.exists() else ""
        blob.upload_from_string(existing + json.dumps(event) + "\n", content_type="application/jsonl")
    except Exception as e:
        logger.warning(f"Event write failed: {e}")


def before_tool_cb(tool, args, tool_context):
    tool_name = tool.name if hasattr(tool, 'name') else str(tool)
    args_dict = dict(args) if args else {}
    if tool_name == "initialize_case" and "gcs_folder" in args_dict:
        _trace_folder["value"] = args_dict["gcs_folder"]
    elif not _trace_folder["value"] and "gcs_folder_uri" in args_dict:
        _trace_folder["value"] = args_dict["gcs_folder_uri"]
    input_summary = json.dumps(args_dict, default=str)[:200]
    _write_event({"ts": datetime.now(timezone.utc).isoformat(), "type": "tool_call", "tool": tool_name, "input": input_summary})


def after_tool_cb(tool, args, tool_context, tool_response):
    tool_name = tool.name if hasattr(tool, 'name') else str(tool)
    output_summary = json.dumps(tool_response, default=str)[:300] if tool_response else ""
    _write_event({"ts": datetime.now(timezone.utc).isoformat(), "type": "tool_result", "tool": tool_name, "output": output_summary})
