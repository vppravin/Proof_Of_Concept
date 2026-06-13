import functions_framework
from flask import jsonify, request
from google.cloud import storage
import base64
import re
import os

PROJECT_ID = os.environ.get("PROJECT_ID", "gbu-demo-playground")
BUCKET_NAME = os.environ.get("BUCKET_NAME", "underwriting-workbench")
API_KEY = os.environ.get("INTAKE_API_KEY", "uw-intake-2026")


def _sanitize_folder_name(subject: str) -> str:
    """Extract a clean folder name from email subject."""
    # Remove common prefixes
    clean = re.sub(r'(?i)^(re:|fwd?:|new submission|submission)\s*[-–:]?\s*', '', subject).strip()
    # Take first meaningful part (insured name)
    clean = re.split(r'\s*[-–|]\s*', clean)[0].strip()
    # Sanitize for GCS
    clean = re.sub(r'[^a-zA-Z0-9\s_-]', '', clean).strip()
    clean = re.sub(r'\s+', '_', clean)
    return clean[:50] or "Unknown_Submission"


@functions_framework.http
def email_intake(request):
    """Receives email data from Apps Script and uploads attachments to GCS."""
    # Simple API key check
    key = request.headers.get("X-API-Key") or request.args.get("key")
    if key != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No JSON body"}), 400

    subject = data.get("subject", "Unknown")
    sender = data.get("sender", "unknown")
    attachments = data.get("attachments", [])

    if not attachments:
        return jsonify({"error": "No attachments found"}), 400

    # Filter only PDFs
    pdf_attachments = [a for a in attachments if a.get("mimeType", "").lower() == "application/pdf"]
    if not pdf_attachments:
        return jsonify({"error": "No PDF attachments"}), 400

    # Create folder name from subject
    folder_name = _sanitize_folder_name(subject)
    gcs_prefix = f"Input_Files/{folder_name}/"

    # Upload to GCS
    gcs = storage.Client(project=PROJECT_ID)
    bucket = gcs.bucket(BUCKET_NAME)

    uploaded = []
    for att in pdf_attachments:
        filename = att.get("name", "document.pdf")
        content = base64.b64decode(att["data"])
        blob = bucket.blob(f"{gcs_prefix}{filename}")
        blob.upload_from_string(content, content_type="application/pdf")
        uploaded.append(filename)

    return jsonify({
        "status": "success",
        "folder": f"gs://{BUCKET_NAME}/{gcs_prefix}",
        "files_uploaded": uploaded,
        "subject": subject,
        "sender": sender,
    }), 200
