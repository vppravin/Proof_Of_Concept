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

- ACORD_125 — ACORD 125 Commercial Insurance Application form. This is the main application containing: applicant/insured information, mailing address, FEIN, SIC code, line of business, broker/agency details, policy dates, premises addresses, employees, nature of business, loss history summary, prior carrier information, and general information questions. It typically says "COMMERCIAL INSURANCE APPLICATION" and "ACORD 125" on it.

- ACORD_140 — ACORD 140 Property Section form. This is the property supplement attached to ACORD 125 containing: detailed building/premises information — construction type, year built, number of stories, total area, roof type, fire protection, sprinklers, burglar alarm, building improvements, coverage amounts (Building, Business Personal Property), causes of loss, coinsurance, deductibles, and exposures. It typically says "PROPERTY SECTION" and "ACORD 140" and "ATTACH TO ACORD 125" on it.

- LOSS_RUN — Loss run or claims history report (contains detailed claim dates, amounts, descriptions, policy periods)

- EMAIL — Email transcript or broker communication (contains email headers like From/To/Subject, conversation thread)

- UNKNOWN — Does not match any of the above

Return ONLY a valid JSON object with these fields:
- classified_as (string): one of ACORD_125, ACORD_140, LOSS_RUN, EMAIL, UNKNOWN
- confidence (integer): a number from 0 to 100 representing how confident you are in the classification. 90-100 = very certain, 70-89 = fairly certain, 50-69 = uncertain, below 50 = guessing.
- reason (string): one sentence explaining why

Return only JSON, no explanation, no markdown."""


def _parse_gcs_path(gcs_uri: str):
    path = gcs_uri.replace("gs://", "")
    return path.split("/", 1)


def _parse_gemini_response(raw_text: str) -> dict:
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()
    return json.loads(raw_text)


# ── Tool functions ─────────────────────────────────────────────────────────

def list_submission_files(gcs_folder_uri: str) -> dict:
    """Lists all files in a GCS submission folder and validates they exist.

    Args:
        gcs_folder_uri: GCS folder URI e.g. gs://underwriting-workbench/submissions/NB-25-34677/

    Returns:
        Dict with list of files found, each with gcs_uri, filename, and size.
    """
    logger.info(f"Tool: list_submission_files for {gcs_folder_uri}")
    try:
        if not gcs_folder_uri.startswith("gs://"):
            return {"error": f"Invalid GCS URI: {gcs_folder_uri}"}

        bucket_name, prefix = _parse_gcs_path(gcs_folder_uri)
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
                logger.warning(f"Unsupported file format: {filename}")
                files.append({
                    "gcs_uri": f"gs://{bucket_name}/{blob.name}",
                    "filename": filename,
                    "size_bytes": blob.size,
                    "valid": False,
                    "reason": f"Unsupported format: .{ext}",
                })
                continue
            files.append({
                "gcs_uri": f"gs://{bucket_name}/{blob.name}",
                "filename": filename,
                "size_bytes": blob.size,
                "valid": True,
            })

        logger.info(f"Found {len(files)} files in {gcs_folder_uri}")
        return {"folder": gcs_folder_uri, "file_count": len(files), "files": files}
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        return {"error": str(e)}


def classify_document(gcs_uri: str) -> dict:
    """Classifies a single document by reading its first page via Gemini Flash.

    Args:
        gcs_uri: GCS URI of the file e.g. gs://underwriting-workbench/submissions/NB-25-34677/form.pdf

    Returns:
        Dict with classified_as, confidence, and reason.
    """
    logger.info(f"Tool: classify_document for {gcs_uri}")
    try:
        if not gcs_uri.startswith("gs://"):
            return {"gcs_uri": gcs_uri, "error": f"Invalid GCS URI: {gcs_uri}"}

        ext = gcs_uri.lower().rsplit(".", 1)[-1]
        mime_type = MIME_MAP.get(ext, "application/pdf")

        file_part = Part.from_uri(uri=gcs_uri, mime_type=mime_type)
        response = model.generate_content([file_part, CLASSIFICATION_PROMPT])
        result = _parse_gemini_response(response.text)

        classified_as = result.get("classified_as", "UNKNOWN")
        if classified_as not in SUPPORTED_TYPES:
            classified_as = "UNKNOWN"

        logger.info(f"Classified {gcs_uri} as {classified_as}")
        return {
            "gcs_uri": gcs_uri,
            "filename": gcs_uri.split("/")[-1],
            "classified_as": classified_as,
            "confidence": result.get("confidence", "Low"),
            "reason": result.get("reason", ""),
        }
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error classifying {gcs_uri}: {e}")
        return {"gcs_uri": gcs_uri, "classified_as": "UNKNOWN", "confidence": "Low", "reason": f"Parse error: {e}"}
    except Exception as e:
        logger.error(f"Classification error for {gcs_uri}: {e}")
        return {"gcs_uri": gcs_uri, "classified_as": "UNKNOWN", "confidence": "Low", "reason": str(e)}


def classify_submission(gcs_folder_uri: str) -> dict:
    """Lists all files in a submission folder, validates, and classifies each by content.

    Args:
        gcs_folder_uri: GCS folder URI e.g. gs://underwriting-workbench/submissions/NB-25-34677/

    Returns:
        Dict with classifications for each file, ready for human approval.
    """
    logger.info(f"Tool: classify_submission for {gcs_folder_uri}")

    listing = list_submission_files(gcs_folder_uri)
    if "error" in listing:
        return listing
    if listing["file_count"] == 0:
        return {"error": f"No files found in {gcs_folder_uri}"}

    classifications = []
    for f in listing["files"]:
        if not f.get("valid", False):
            classifications.append({
                "filename": f["filename"],
                "gcs_uri": f["gcs_uri"],
                "classified_as": "UNKNOWN",
                "confidence": "N/A",
                "reason": f.get("reason", "Unsupported format"),
                "valid": False,
            })
            continue
        result = classify_document(f["gcs_uri"])
        result["valid"] = True
        classifications.append(result)

    return {
        "folder": gcs_folder_uri,
        "file_count": len(classifications),
        "classifications": classifications,
        "status": "awaiting_approval",
    }
