"""Classification tools — Gemini Flash for document type identification."""

import os
import json
import logging

from google.cloud import storage
import vertexai
from vertexai.generative_models import GenerativeModel, Part

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
LOCATION = os.getenv("LOCATION", "us-central1")
BUCKET_NAME = os.getenv("BUCKET_NAME", "underwriting-workbench")

vertexai.init(project=PROJECT_ID, location=LOCATION)
gcs_client = storage.Client(project=PROJECT_ID)
model = GenerativeModel("gemini-2.0-flash-001")

MIME_MAP = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "tiff": "image/tiff",
    "tif": "image/tiff",
    "txt": "text/plain",
}

SUPPORTED_TYPES = ["ACORD_125", "ACORD_140", "LOSS_RUN", "EMAIL"]

CLASSIFICATION_PROMPT = """You are an expert insurance document classifier.
Examine this document and classify it into exactly ONE of these types:

- ACORD_125 — ACORD 125 Commercial Insurance Application form.
- ACORD_140 — ACORD 140 Property Section form.
- LOSS_RUN — Loss run or claims history report.
- EMAIL — Email transcript or broker communication.
- UNKNOWN — Does not match any of the above.

Return ONLY a valid JSON object with these fields:
- classified_as (string): one of ACORD_125, ACORD_140, LOSS_RUN, EMAIL, UNKNOWN
- confidence (integer): 0 to 100
- reason (string): one sentence explaining why

Return only JSON, no explanation, no markdown."""


def _parse_gemini_response(raw_text: str) -> dict:
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()
    return json.loads(raw_text)


def list_submission_files(gcs_folder_uri: str) -> dict:
    """Lists all files in a GCS submission folder.

    Args:
        gcs_folder_uri: GCS folder URI e.g. gs://underwriting-workbench/Input_Files/Sample 1/

    Returns:
        Dict with list of files found, each with gcs_uri, filename, and size.
    """
    logger.info(f"Tool: list_submission_files for {gcs_folder_uri}")
    try:
        bucket_name, prefix = gcs_folder_uri.replace("gs://", "").split("/", 1)
        if not prefix.endswith("/"):
            prefix += "/"

        bucket = gcs_client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix=prefix))

        files = []
        for blob in blobs:
            if blob.name == prefix:
                continue
            filename = blob.name.split("/")[-1]
            if not filename or filename.startswith("_"):
                continue
            ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
            if ext not in MIME_MAP:
                files.append({"gcs_uri": f"gs://{bucket_name}/{blob.name}", "filename": filename, "size_bytes": blob.size, "valid": False, "reason": f"Unsupported format: .{ext}"})
                continue
            files.append({"gcs_uri": f"gs://{bucket_name}/{blob.name}", "filename": filename, "size_bytes": blob.size, "valid": True})

        return {"folder": gcs_folder_uri, "file_count": len(files), "files": files}
    except Exception as e:
        return {"error": str(e)}


def classify_document(gcs_uri: str) -> dict:
    """Classifies a single document by sending it to Gemini Flash.

    Args:
        gcs_uri: GCS URI of the file e.g. gs://underwriting-workbench/Input_Files/Sample 1/Acord125.pdf

    Returns:
        Dict with classified_as, confidence (0-100), and reason.
    """
    logger.info(f"Tool: classify_document for {gcs_uri}")
    try:
        ext = gcs_uri.lower().rsplit(".", 1)[-1]
        mime_type = MIME_MAP.get(ext, "application/pdf")

        file_part = Part.from_uri(uri=gcs_uri, mime_type=mime_type)
        response = model.generate_content([file_part, CLASSIFICATION_PROMPT])
        result = _parse_gemini_response(response.text)

        classified_as = result.get("classified_as", "UNKNOWN")
        if classified_as not in SUPPORTED_TYPES:
            classified_as = "UNKNOWN"

        return {
            "gcs_uri": gcs_uri,
            "filename": gcs_uri.split("/")[-1],
            "classified_as": classified_as,
            "confidence": result.get("confidence", 0),
            "reason": result.get("reason", ""),
        }
    except json.JSONDecodeError as e:
        return {"gcs_uri": gcs_uri, "classified_as": "UNKNOWN", "confidence": 0, "reason": f"Parse error: {e}"}
    except Exception as e:
        return {"gcs_uri": gcs_uri, "classified_as": "UNKNOWN", "confidence": 0, "reason": str(e)}
