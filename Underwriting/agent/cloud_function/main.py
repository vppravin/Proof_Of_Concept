"""Cloud Function: Auto-process new submissions in GCS.

Trigger: Eventarc — google.cloud.storage.object.v1.finalized
Scope: gs://underwriting-workbench/Input_Files/<folder>/

When a new file lands under Input_Files/, this function:
1. Extracts the submission folder path
2. Checks if already processed (_extracted_fields.json exists)
3. Calls the orchestrator via stream_query to process end-to-end
"""

import functions_framework
import json
import logging
from google.cloud import storage
from cloudevents.http import CloudEvent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("submission_trigger")

PROJECT_ID = "gbu-demo-playground"
LOCATION = "us-central1"
BUCKET_NAME = "underwriting-workbench"
INPUT_PREFIX = "Input_Files/"
ORCHESTRATOR_ENGINE_ID = "projects/146646146609/locations/us-central1/reasoningEngines/3721156916475330560"


def _is_already_processed(bucket_name: str, folder_path: str) -> bool:
    """Check if _extracted_fields.json exists in the folder."""
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(f"{folder_path}_extracted_fields.json")
    return blob.exists()


def _is_already_in_progress(gcs_folder_uri: str) -> bool:
    """Check if a case already exists for this folder in BigQuery."""
    from google.cloud import bigquery
    bq = bigquery.Client(project=PROJECT_ID)
    rows = list(bq.query(
        "SELECT case_id FROM `gbu-demo-playground.underwriting_workbench.submissions` WHERE gcs_folder = @f LIMIT 1",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("f", "STRING", gcs_folder_uri)
        ])
    ).result())
    return len(rows) > 0


def _call_orchestrator(gcs_folder_uri: str) -> str:
    """Call the orchestrator agent to process the submission."""
    import vertexai
    from datetime import datetime, timezone
    from vertexai import agent_engines

    vertexai.init(project=PROJECT_ID, location=LOCATION)
    agent = agent_engines.get(ORCHESTRATOR_ENGINE_ID)

    gcs_client = storage.Client()
    bucket_name = gcs_folder_uri.split("/")[2]
    prefix = gcs_folder_uri.replace(f"gs://{bucket_name}/", "").strip("/")
    thinking_blob = gcs_client.bucket(bucket_name).blob(f"{prefix}/_thinking.jsonl")

    response_parts = []
    for event in agent.stream_query(
        message=f"Process the submission for {gcs_folder_uri}",
        user_id="cloud-function-trigger",
    ):
        content = event.get("content", {})
        for part in content.get("parts", []):
            if "text" in part:
                text = part["text"].strip()
                if text:
                    response_parts.append(text)
                    entry = json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "text": text}) + "\n"
                    try:
                        existing = thinking_blob.download_as_text() if thinking_blob.exists() else ""
                        thinking_blob.upload_from_string(existing + entry, content_type="application/jsonl")
                    except Exception:
                        pass

    # Check if stream dropped before completion
    from google.cloud import bigquery
    bq = bigquery.Client(project=PROJECT_ID)
    rows = list(bq.query(
        "SELECT case_id, status, current_step FROM `gbu-demo-playground.underwriting_workbench.submissions` WHERE gcs_folder = @f LIMIT 1",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("f", "STRING", gcs_folder_uri)
        ])).result())
    if rows and rows[0].status == "Processing":
        case_id = rows[0].case_id
        step = rows[0].current_step
        logger.error(f"Stream dropped — case {case_id} stuck at {step}")
        bq.query(
            "INSERT INTO `gbu-demo-playground.underwriting_workbench.processing_errors` (error_id, gcs_folder, case_id, error_step, error_message, resolved, created_on) VALUES (@eid, @f, @cid, @step, @msg, FALSE, CURRENT_TIMESTAMP())",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("eid", "STRING", f"err-{case_id}-drop"),
                bigquery.ScalarQueryParameter("f", "STRING", gcs_folder_uri),
                bigquery.ScalarQueryParameter("cid", "STRING", case_id),
                bigquery.ScalarQueryParameter("step", "STRING", step),
                bigquery.ScalarQueryParameter("msg", "STRING", f"Agent stream dropped during {step}. Processing incomplete."),
            ])).result()

    return "\n".join(response_parts)


@functions_framework.cloud_event
def process_submission(cloud_event: CloudEvent):
    """Triggered by a new file in gs://underwriting-workbench/Input_Files/."""
    data = cloud_event.data
    file_name = data.get("name", "")
    bucket = data.get("bucket", "")

    logger.info(f"Event received: gs://{bucket}/{file_name}")

    # Only process files under Input_Files/
    if not file_name.startswith(INPUT_PREFIX):
        logger.info(f"Skipping — not under {INPUT_PREFIX}")
        return "Skipped — wrong prefix"

    # Skip intermediate files
    base_name = file_name.split("/")[-1]
    if base_name.startswith("_") or not base_name:
        logger.info(f"Skipping intermediate file: {base_name}")
        return "Skipped — intermediate file"

    # Extract folder path: Input_Files/Sample 1/file.pdf → Input_Files/Sample 1/
    parts = file_name.split("/")
    if len(parts) < 3:
        logger.info(f"Skipping — not in a submission folder")
        return "Skipped — no folder"

    folder_path = "/".join(parts[:2]) + "/"
    gcs_folder_uri = f"gs://{bucket}/{folder_path}"

    # Deduplication: write lock immediately with unique ID, wait, then check if we own it
    import time, uuid
    my_id = uuid.uuid4().hex
    gcs_client = storage.Client()
    lock_blob = gcs_client.bucket(bucket).blob(f"{folder_path}_processing.lock")

    # If lock already exists, skip
    if lock_blob.exists():
        logger.info(f"Lock exists — skipping: {folder_path}")
        return "Skipped — lock file exists"

    if _is_already_processed(bucket, folder_path):
        logger.info(f"Already processed: {folder_path}")
        return "Skipped — already processed"

    if _is_already_in_progress(gcs_folder_uri):
        logger.info(f"Already in BigQuery — skipping: {folder_path}")
        return "Skipped — already in progress"

    # Write lock with our ID
    lock_blob.upload_from_string(my_id, content_type="text/plain")

    # Wait for other triggers to also write
    time.sleep(10)

    # Re-read lock — if it's still our ID, we own it
    current_lock = lock_blob.download_as_text()
    if current_lock != my_id:
        logger.info(f"Lost lock race — another instance owns it: {folder_path}")
        return "Skipped — lost lock race"

    # Process
    try:
        logger.info(f"Processing submission: {gcs_folder_uri}")
        result = _call_orchestrator(gcs_folder_uri)
        logger.info(f"Done: {gcs_folder_uri}\n{result[:500]}")
        return f"Processed: {gcs_folder_uri}"
    except Exception as e:
        logger.error(f"Failed: {gcs_folder_uri} — {e}")
        return f"Error: {e}"
    finally:
        try:
            lock_blob.delete()
        except Exception:
            pass
