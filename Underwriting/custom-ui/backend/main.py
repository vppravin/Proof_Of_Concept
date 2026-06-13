"""Smart Underwriting Workbench — Backend API."""

import json
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from google.cloud import bigquery
import vertexai
from vertexai import agent_engines

app = FastAPI(title="Smart Underwriting Workbench API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECT_ID = "gbu-demo-playground"
DATASET_ID = "underwriting_workbench"
TABLE_ID = f"{PROJECT_ID}.{DATASET_ID}.submissions"
ERRORS_TABLE = f"{PROJECT_ID}.{DATASET_ID}.processing_errors"
ORCHESTRATOR_ID = "projects/146646146609/locations/us-central1/reasoningEngines/3721156916475330560"
CHAT_AGENT_ID = "projects/146646146609/locations/us-central1/reasoningEngines/4629890082692661248"

bq_client = bigquery.Client(project=PROJECT_ID)
vertexai.init(project=PROJECT_ID, location="us-central1")


# ── Models ──

class ChatRequest(BaseModel):
    message: str
    user_id: str = "underwriter"
    session_id: Optional[str] = None
    history: list = []
    ui_context: Optional[dict] = None


# ── Dashboard API ──

@app.get("/api/submissions")
def get_submissions(status: str = "", assigned_to: str = "", limit: int = 50):
    """Get all submissions with optional filters."""
    where = []
    params = []
    if status:
        where.append("status = @status")
        params.append(bigquery.ScalarQueryParameter("status", "STRING", status))
    if assigned_to:
        where.append("LOWER(assigned_to) LIKE LOWER(@assigned_to)")
        params.append(bigquery.ScalarQueryParameter("assigned_to", "STRING", f"%{assigned_to}%"))

    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    query = f"SELECT * FROM `{TABLE_ID}` {where_clause} ORDER BY created_on DESC LIMIT {limit}"
    rows = list(bq_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
    return {"submissions": [dict(r) for r in rows], "count": len(rows)}


def _fix_json_field(val):
    """Ensure a JSON string field is valid JSON (handles Python dict format)."""
    if not val or not isinstance(val, str):
        return val
    try:
        json.loads(val)
        return val
    except (json.JSONDecodeError, ValueError):
        try:
            fixed = val.replace(": None", ": null").replace(": True", ": true").replace(": False", ": false").replace("'", '"')
            json.loads(fixed)
            return fixed
        except Exception:
            return val


@app.get("/api/submissions/{case_id}")
def get_submission(case_id: str):
    """Get a single submission by case ID."""
    query = f"SELECT * FROM `{TABLE_ID}` WHERE case_id = @case_id"
    params = [bigquery.ScalarQueryParameter("case_id", "STRING", case_id)]
    rows = list(bq_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
    if not rows:
        raise HTTPException(status_code=404, detail="Submission not found")
    row = dict(rows[0])
    for field in ("extracted_json", "uw_result_json", "classification_json", "client_history_json"):
        row[field] = _fix_json_field(row.get(field))
    return row


@app.get("/api/stats")
def get_stats():
    """Get dashboard statistics."""
    query = f"""
    SELECT
        COUNT(*) as total,
        COUNTIF(status = 'Assigned') as assigned,
        COUNTIF(status = 'Pending Classification') as pending,
        COUNTIF(status = 'Complete') as complete,
        COUNTIF(status = 'Declined') as declined,
        COUNTIF(priority = 'P0') as p0_count,
        COUNTIF(priority = 'P1') as p1_count,
        COUNTIF(priority = 'P2') as p2_count,
        COUNTIF(risk_level = 'High Risk') as high_risk,
        COUNTIF(risk_level = 'Medium Risk') as medium_risk,
        COUNTIF(risk_level = 'Low Risk') as low_risk,
        AVG(risk_score) as avg_risk_score,
        SUM(sum_insured) as total_sum_insured
    FROM `{TABLE_ID}`
    """
    rows = list(bq_client.query(query).result())
    return dict(rows[0]) if rows else {}


@app.get("/api/stats/by-status")
def get_stats_by_status():
    """Get submission counts by status for pie chart."""
    query = f"SELECT status, COUNT(*) as count FROM `{TABLE_ID}` GROUP BY status"
    rows = list(bq_client.query(query).result())
    return [dict(r) for r in rows]


@app.get("/api/stats/by-priority")
def get_stats_by_priority():
    """Get submission counts by priority for chart."""
    query = f"SELECT priority, COUNT(*) as count FROM `{TABLE_ID}` WHERE priority IS NOT NULL GROUP BY priority ORDER BY priority"
    rows = list(bq_client.query(query).result())
    return [dict(r) for r in rows]


@app.get("/api/stats/by-assignee")
def get_stats_by_assignee():
    """Get submission counts by assignee for chart."""
    query = f"SELECT assigned_to, COUNT(*) as count, COUNTIF(status='Assigned') as assigned, COUNTIF(status='Complete') as complete FROM `{TABLE_ID}` WHERE assigned_to IS NOT NULL GROUP BY assigned_to"
    rows = list(bq_client.query(query).result())
    return [dict(r) for r in rows]


@app.get("/api/stats/by-risk")
def get_stats_by_risk():
    """Get risk score distribution for chart."""
    query = f"SELECT risk_level, COUNT(*) as count FROM `{TABLE_ID}` WHERE risk_level IS NOT NULL GROUP BY risk_level"
    rows = list(bq_client.query(query).result())
    return [dict(r) for r in rows]


@app.get("/api/errors")
def get_errors(resolved: bool = False):
    """Get processing errors."""
    query = f"SELECT * FROM `{ERRORS_TABLE}` WHERE resolved = @resolved ORDER BY created_on DESC LIMIT 20"
    params = [bigquery.ScalarQueryParameter("resolved", "BOOL", resolved)]
    rows = list(bq_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
    return {"errors": [dict(r) for r in rows], "count": len(rows)}


@app.get("/api/submissions/{case_id}/files")
def get_submission_files(case_id: str):
    """List source PDF files for a submission from GCS."""
    from google.cloud import storage as gcs_storage
    query = f"SELECT gcs_folder, extracted_json FROM `{TABLE_ID}` WHERE case_id = @case_id"
    params = [bigquery.ScalarQueryParameter("case_id", "STRING", case_id)]
    rows = list(bq_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
    if not rows or not rows[0].gcs_folder:
        return {"files": [], "classifications": []}

    gcs_folder = rows[0].gcs_folder
    gcs = gcs_storage.Client(project=PROJECT_ID)
    bucket_name, prefix = gcs_folder.replace("gs://", "").split("/", 1)
    if not prefix.endswith("/"):
        prefix += "/"
    bucket = gcs.bucket(bucket_name)
    blobs = list(bucket.list_blobs(prefix=prefix))

    # Try to load classification data
    classifications = []
    try:
        cls_blob = bucket.blob(prefix + "_classification_results.json")
        if cls_blob.exists():
            classifications = json.loads(cls_blob.download_as_text()).get("classifications", [])
    except Exception:
        pass

    files = []
    for blob in blobs:
        filename = blob.name.split("/")[-1]
        if not filename or filename.startswith("_"):
            continue
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if ext in ("pdf", "png", "jpg", "jpeg", "tiff"):
            url = f"/api/files/{bucket_name}/{blob.name}"
            cls_info = next((c for c in classifications if c.get("filename") == filename), None)
            files.append({
                "filename": filename, "url": url, "size_bytes": blob.size, "type": ext,
                "classified_as": cls_info.get("classified_as") if cls_info else None,
                "confidence": cls_info.get("confidence") if cls_info else None,
            })
    return {"files": files, "gcs_folder": gcs_folder}


class DecisionRequest(BaseModel):
    decision: str
    decision_by: str = "Underwriter"
    notes: str = ""


@app.post("/api/submissions/{case_id}/decision")
def record_decision(case_id: str, req: DecisionRequest):
    """Record accept/decline decision on a submission."""
    decision = req.decision.strip().lower()
    if decision not in ("accept", "decline"):
        raise HTTPException(status_code=400, detail="Decision must be 'accept' or 'decline'")

    new_status = "Complete" if decision == "accept" else "Declined"
    now = datetime.now(timezone.utc).isoformat()

    query = f"""
        UPDATE `{TABLE_ID}`
        SET status = @status, decision = @decision, decision_by = @decision_by,
            decision_at = @decision_at, updated_on = @updated_on, decline_reason = @notes
        WHERE case_id = @case_id
    """
    bq_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("status", "STRING", new_status),
        bigquery.ScalarQueryParameter("decision", "STRING", decision),
        bigquery.ScalarQueryParameter("decision_by", "STRING", req.decision_by),
        bigquery.ScalarQueryParameter("decision_at", "TIMESTAMP", now),
        bigquery.ScalarQueryParameter("updated_on", "TIMESTAMP", now),
        bigquery.ScalarQueryParameter("case_id", "STRING", case_id),
        bigquery.ScalarQueryParameter("notes", "STRING", req.notes or None),
    ])).result()
    return {"case_id": case_id, "status": new_status, "decision": decision, "decision_by": req.decision_by}


class CaseChatRequest(BaseModel):
    message: str
    user_id: str = "underwriter"


@app.post("/api/submissions/{case_id}/chat")
async def case_chat(case_id: str, req: CaseChatRequest):
    """Stream chat for a specific case with persistent session."""
    async def stream():
        try:
            agent = agent_engines.get(ORCHESTRATOR_ID)

            # Get or create session_id for this case
            rows = list(bq_client.query(
                f"SELECT chat_session_id FROM `{TABLE_ID}` WHERE case_id = @cid",
                job_config=bigquery.QueryJobConfig(query_parameters=[
                    bigquery.ScalarQueryParameter("cid", "STRING", case_id)
                ])
            ).result())
            if not rows:
                yield f"data: {json.dumps({'error': 'Case not found'})}\n\n"
                return

            session_id = rows[0].chat_session_id

            # If no session exists, create one
            if not session_id:
                session = agent.create_session(user_id=case_id)
                session_id = session.get("id") or session.get("session_id")
                # Store session_id in BigQuery
                bq_client.query(
                    f"UPDATE `{TABLE_ID}` SET chat_session_id = @sid, updated_on = @now WHERE case_id = @cid",
                    job_config=bigquery.QueryJobConfig(query_parameters=[
                        bigquery.ScalarQueryParameter("sid", "STRING", session_id),
                        bigquery.ScalarQueryParameter("now", "TIMESTAMP", datetime.now(timezone.utc).isoformat()),
                        bigquery.ScalarQueryParameter("cid", "STRING", case_id),
                    ])
                ).result()

            # Prepend case context on every message so agent always knows which case
            message = f"[Case: {case_id}] {req.message}"

            # Stream query with session_id — engine maintains full history
            for event in agent.stream_query(message=message, user_id=case_id, session_id=session_id):
                content = event.get("content", {})
                for part in content.get("parts", []):
                    if "text" in part:
                        yield f"data: {json.dumps({'text': part['text']})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/submissions/{case_id}/chat-history")
def get_case_chat_history(case_id: str):
    """Get previous chat messages for a case from the agent session."""
    try:
        rows = list(bq_client.query(
            f"SELECT chat_session_id FROM `{TABLE_ID}` WHERE case_id = @cid",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("cid", "STRING", case_id)
            ])
        ).result())
        if not rows or not rows[0].chat_session_id:
            return {"messages": []}

        agent = agent_engines.get(ORCHESTRATOR_ID)
        session = agent.get_session(user_id=case_id, session_id=rows[0].chat_session_id)

        messages = []
        events = session.get("events", []) if isinstance(session, dict) else []
        for event in events:
            author = event.get("author", "")
            content = event.get("content", {})
            parts = content.get("parts", []) if isinstance(content, dict) else []
            for part in parts:
                if isinstance(part, dict):
                    text = part.get("text")
                    if text and text.strip():
                        # Skip the injected context prefix
                        if text.startswith("[CONTEXT:"):
                            continue
                        role = "user" if author == "user" else "agent"
                        messages.append({"role": role, "text": text})
        return {"messages": messages}
    except Exception as e:
        return {"messages": [], "error": str(e)}


# ── Chat API ──

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Stream chat with the chat agent (separate from processing agent)."""
    async def stream():
        try:
            context_parts = []
            # Inject UI context so agent knows what user is viewing
            if req.ui_context:
                ctx = req.ui_context
                ctx_str = f"[UI Context: User is on {ctx.get('view','dashboard')}"
                if ctx.get('caseId'): ctx_str += f", viewing case {ctx['caseId']}"
                if ctx.get('tab'): ctx_str += f", tab: {ctx['tab']}"
                ctx_str += ". When referencing cases, include the case ID formatted as [[CASE:NB-XX-XXXXX]] so the UI can make it clickable.]"
                context_parts.append(ctx_str)

            for h in req.history[-8:]:
                role = "User" if h.get("role") == "user" else "Assistant"
                context_parts.append(f"{role}: {h.get('text', '')}")

            if context_parts:
                full_message = "Previous conversation:\n" + "\n".join(context_parts) + "\n\nNow answer this new message:\n" + req.message
            else:
                full_message = req.message

            agent = agent_engines.get(CHAT_AGENT_ID)
            for event in agent.stream_query(message=full_message, user_id=req.user_id):
                content = event.get("content", {})
                for part in content.get("parts", []):
                    if "text" in part:
                        yield f"data: {json.dumps({'text': part['text']})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/submissions/{case_id}/justify")
def justify_submission(case_id: str):
    """Get justification — read from BigQuery if pre-generated, else call chat agent."""
    # Try pre-generated justification first
    rows = list(bq_client.query(
        f"SELECT justification_text FROM `{TABLE_ID}` WHERE case_id = @cid",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("cid", "STRING", case_id)
        ])).result())
    if rows and rows[0].justification_text:
        return {"justification": rows[0].justification_text}

    # Fallback: call chat agent
    try:
        agent = agent_engines.get(CHAT_AGENT_ID)
        response_text = []
        for event in agent.stream_query(
            message=f"Provide a detailed professional justification and recommendation for case {case_id}. Cover risk assessment, key factors, concerns, and your accept/decline recommendation with specific data.",
            user_id="ui-justify"
        ):
            content = event.get("content", {})
            for part in content.get("parts", []):
                if "text" in part:
                    response_text.append(part["text"])
        return {"justification": "".join(response_text)}
    except Exception as e:
        return {"justification": f"Unable to generate justification: {str(e)}"}


# ── Chat Session History ──

CHAT_TABLE = f"{PROJECT_ID}.{DATASET_ID}.chat_sessions"

@app.get("/api/errors/{error_id}")
def get_error_detail(error_id: str):
    """Get full error details."""
    rows = list(bq_client.query(
        f"SELECT * FROM `{ERRORS_TABLE}` WHERE error_id = @eid",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("eid", "STRING", error_id)
        ])).result())
    if not rows:
        raise HTTPException(status_code=404, detail="Error not found")
    row = dict(rows[0])
    for k, v in row.items():
        if hasattr(v, 'isoformat'): row[k] = v.isoformat()
    return row

@app.post("/api/errors/{error_id}/retry")
def retry_error(error_id: str):
    """Retry a failed submission — cleans up and re-triggers processing."""
    from google.cloud import storage as gcs_storage
    rows = list(bq_client.query(
        f"SELECT * FROM `{ERRORS_TABLE}` WHERE error_id = @eid",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("eid", "STRING", error_id)
        ])).result())
    if not rows:
        raise HTTPException(status_code=404, detail="Error not found")
    error = rows[0]
    gcs_folder = error.gcs_folder

    # Delete stuck submission if exists
    bq_client.query(
        f"DELETE FROM `{TABLE_ID}` WHERE gcs_folder = @f",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("f", "STRING", gcs_folder)
        ])).result()

    # Delete intermediate files (lock, extracted, classification) but keep PDFs
    gcs = gcs_storage.Client(project=PROJECT_ID)
    bucket_name = gcs_folder.split("/")[2]
    prefix = gcs_folder.replace(f"gs://{bucket_name}/", "").strip("/") + "/"
    bucket = gcs.bucket(bucket_name)
    for blob in bucket.list_blobs(prefix=prefix):
        if not blob.name.endswith(".pdf"):
            blob.delete()

    # Mark error as resolved
    bq_client.query(
        f"UPDATE `{ERRORS_TABLE}` SET resolved = TRUE WHERE error_id = @eid",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("eid", "STRING", error_id)
        ])).result()

    # Re-upload a trigger file to kick off Cloud Function
    trigger_blob = bucket.blob(f"{prefix}retry-trigger.txt")
    trigger_blob.upload_from_string(f"retry-{error_id}", content_type="text/plain")

    return {"retried": True, "gcs_folder": gcs_folder}

@app.post("/api/errors/{error_id}/resolve")
def resolve_error(error_id: str):
    """Mark error as manually resolved."""
    bq_client.query(
        f"UPDATE `{ERRORS_TABLE}` SET resolved = TRUE WHERE error_id = @eid",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("eid", "STRING", error_id)
        ])).result()
    return {"resolved": True}

class SaveSessionRequest(BaseModel):
    session_id: str
    title: str = ""
    messages: list = []

@app.get("/api/chat-sessions")
def list_chat_sessions(user_id: str = "default", limit: int = 20):
    """List previous chat sessions."""
    rows = list(bq_client.query(
        f"SELECT session_id, title, created_on, updated_on FROM `{CHAT_TABLE}` WHERE user_id = @uid ORDER BY updated_on DESC LIMIT {limit}",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("uid", "STRING", user_id)
        ])).result())
    return [{"session_id": r.session_id, "title": r.title, "created_on": r.created_on.isoformat(), "updated_on": r.updated_on.isoformat()} for r in rows]

@app.get("/api/chat-sessions/{session_id}")
def get_chat_session(session_id: str):
    """Load a specific chat session with messages."""
    rows = list(bq_client.query(
        f"SELECT * FROM `{CHAT_TABLE}` WHERE session_id = @sid",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("sid", "STRING", session_id)
        ])).result())
    if not rows:
        raise HTTPException(status_code=404, detail="Session not found")
    r = rows[0]
    return {"session_id": r.session_id, "title": r.title, "messages": json.loads(r.messages or "[]"), "created_on": r.created_on.isoformat()}

@app.post("/api/chat-sessions")
def save_chat_session(req: SaveSessionRequest):
    """Save or update a chat session. Auto-generates title using Gemini Flash."""
    from datetime import datetime, timezone
    from vertexai.generative_models import GenerativeModel
    now = datetime.now(timezone.utc).isoformat()

    # Auto-generate title if not provided or generic
    title = req.title
    if (not title or len(title) < 3 or title == "Untitled") and req.messages:
        try:
            convo = " | ".join([m.get("text", "")[:100] for m in req.messages[:6] if m.get("text")])
            model = GenerativeModel("gemini-2.0-flash")
            resp = model.generate_content(f"Generate a 3-4 word topic title for this conversation. Return ONLY the title, nothing else:\n{convo[:500]}")
            title = resp.text.strip().strip('"').strip("'")[:40]
        except:
            title = req.messages[0].get("text", "Chat")[:40] if req.messages else "Chat"

    existing = list(bq_client.query(
        f"SELECT session_id FROM `{CHAT_TABLE}` WHERE session_id = @sid",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("sid", "STRING", req.session_id)
        ])).result())
    if existing:
        bq_client.query(
            f"UPDATE `{CHAT_TABLE}` SET messages = @msgs, title = @title, updated_on = @now WHERE session_id = @sid",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("msgs", "STRING", json.dumps(req.messages)),
                bigquery.ScalarQueryParameter("title", "STRING", title),
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                bigquery.ScalarQueryParameter("sid", "STRING", req.session_id),
            ])).result()
    else:
        bq_client.query(
            f"INSERT INTO `{CHAT_TABLE}` (session_id, user_id, title, messages, created_on, updated_on) VALUES (@sid, 'default', @title, @msgs, @now, @now)",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("sid", "STRING", req.session_id),
                bigquery.ScalarQueryParameter("title", "STRING", title),
                bigquery.ScalarQueryParameter("msgs", "STRING", json.dumps(req.messages)),
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
            ])).result()
    return {"saved": True, "title": title}

@app.delete("/api/chat-sessions/{session_id}")
def delete_chat_session(session_id: str):
    """Delete a chat session."""
    bq_client.query(
        f"DELETE FROM `{CHAT_TABLE}` WHERE session_id = @sid",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("sid", "STRING", session_id)
        ])).result()
    return {"deleted": True}


class ApproveRequest(BaseModel):
    classifications: list = []  # [{filename, classified_as}] — underwriter's override
    comment: str = ""

@app.post("/api/submissions/{case_id}/approve")
def approve_pending(case_id: str, req: ApproveRequest = ApproveRequest()):
    """Approve a pending classification with underwriter's override and continue processing."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    # If underwriter provided classification overrides, save them
    if req.classifications:
        bq_client.query(
            f"UPDATE `{TABLE_ID}` SET classification_json = @cls, status = 'Processing', current_step = 'extraction', updated_on = @now WHERE case_id = @cid",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("cls", "STRING", json.dumps(req.classifications)),
                bigquery.ScalarQueryParameter("cid", "STRING", case_id),
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
            ])).result()
    else:
        bq_client.query(
            f"UPDATE `{TABLE_ID}` SET status = 'Processing', current_step = 'extraction', updated_on = @now WHERE case_id = @cid",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("cid", "STRING", case_id),
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
            ])).result()

    # Trigger reprocessing
    rows = list(bq_client.query(
        f"SELECT gcs_folder FROM `{TABLE_ID}` WHERE case_id = @cid",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("cid", "STRING", case_id)
        ])).result())
    if rows and rows[0].gcs_folder:
        from google.cloud import storage as gcs_storage
        gcs = gcs_storage.Client(project=PROJECT_ID)
        bucket_name = rows[0].gcs_folder.split("/")[2]
        prefix = rows[0].gcs_folder.replace(f"gs://{bucket_name}/", "").strip("/") + "/"
        bucket = gcs.bucket(bucket_name)
        lock = bucket.blob(f"{prefix}_processing.lock")
        if lock.exists(): lock.delete()
        bucket.blob(f"{prefix}approved-trigger.txt").upload_from_string(f"approved-{case_id}", content_type="text/plain")
    return {"approved": True}

class RejectRequest(BaseModel):
    reason: str = "Rejected at classification"

@app.post("/api/submissions/{case_id}/reject")
def reject_pending(case_id: str, req: RejectRequest = RejectRequest()):
    """Reject a pending submission with reason."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    bq_client.query(
        f"UPDATE `{TABLE_ID}` SET status = 'Declined', decline_reason = @reason, updated_on = @now WHERE case_id = @cid",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("cid", "STRING", case_id),
            bigquery.ScalarQueryParameter("reason", "STRING", req.reason),
            bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
        ])).result()
    return {"rejected": True}

@app.get("/api/submissions/{case_id}/trace")
def get_trace(case_id: str):
    """Get processing trace for a submission."""
    rows = list(bq_client.query(
        f"SELECT gcs_folder FROM `{TABLE_ID}` WHERE case_id = @cid",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("cid", "STRING", case_id)
        ])).result())
    if not rows or not rows[0].gcs_folder:
        return {"trace": []}
    gcs_folder = rows[0].gcs_folder
    bucket_name = gcs_folder.split("/")[2]
    prefix = gcs_folder.replace(f"gs://{bucket_name}/", "").strip("/")
    from google.cloud import storage as gcs_storage
    gcs = gcs_storage.Client(project=PROJECT_ID)
    blob = gcs.bucket(bucket_name).blob(f"{prefix}/_trace.jsonl")
    if not blob.exists():
        return {"trace": []}
    lines = blob.download_as_text().strip().split("\n")
    trace = []
    for line in lines:
        try: trace.append(json.loads(line))
        except: pass
    return {"trace": trace}

@app.get("/api/submissions/{case_id}/logs")
def get_agent_logs(case_id: str):
    """Get agent execution logs from GCS _events.jsonl."""
    rows = list(bq_client.query(
        f"SELECT gcs_folder FROM `{TABLE_ID}` WHERE case_id = @cid",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("cid", "STRING", case_id)
        ])).result())
    if not rows or not rows[0].gcs_folder:
        return {"logs": []}
    gcs_folder = rows[0].gcs_folder
    try:
        from google.cloud import storage as gcs_storage
        gcs_client = gcs_storage.Client(project=PROJECT_ID)
        bucket_name = gcs_folder.split("/")[2]
        prefix = gcs_folder.replace(f"gs://{bucket_name}/", "").strip("/")
        blob = gcs_client.bucket(bucket_name).blob(f"{prefix}/_thinking.jsonl")
        if not blob.exists():
            return {"logs": []}
        content = blob.download_as_text()
        logs = [json.loads(line) for line in content.strip().split("\n") if line.strip()]
        return {"logs": logs}
    except Exception as e:
        return {"logs": [], "error": str(e)}


@app.get("/api/files/{bucket}/{path:path}")
def proxy_gcs_file(bucket: str, path: str):
    """Proxy GCS files through the backend."""
    from google.cloud import storage as gcs_storage
    from fastapi.responses import Response
    gcs = gcs_storage.Client(project=PROJECT_ID)
    blob = gcs.bucket(bucket).blob(path)
    content = blob.download_as_bytes()
    ext = path.lower().rsplit(".", 1)[-1] if "." in path else ""
    mime = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "tiff": "image/tiff"}.get(ext, "application/octet-stream")
    return Response(content=content, media_type=mime, headers={"Content-Disposition": f"inline; filename={path.split('/')[-1]}"})


# ── Serve React static files (production) ──

if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
