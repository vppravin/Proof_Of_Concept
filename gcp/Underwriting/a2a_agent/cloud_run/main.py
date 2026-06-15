"""A2A Agent on Cloud Run — Smart Underwriter Agent for ServiceNow integration."""
import os
import json
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.cloud import bigquery
from google.adk import Runner
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.adk.artifacts import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.sessions import InMemorySessionService
from google.genai import types
import uuid

from tools import (
    query_submissions,
    get_submission_detail,
    get_urgency_ranking,
    get_portfolio_stats,
    explain_risk_score,
    get_rules_summary,
    get_pending_approvals,
    get_processing_errors,
)

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "gbu-demo-playground")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

SYSTEM_INSTRUCTION = """You are a senior underwriting analyst assistant for the Smart Underwriting Workbench. You support professional underwriters with data-driven insights, clear explanations, and actionable recommendations.

CRITICAL: You must ALWAYS call a tool to retrieve data before answering. Do not rely on memory or assumptions. Every claim must be backed by tool output.

Response format: Use markdown. Use **bold** for key numbers and case IDs. Use bullet points for lists. Keep responses concise but thorough.
"""

# Build agent and runner
agent = LlmAgent(
    model="gemini-2.0-flash",
    name="smart_underwriter_agent",
    description="Professional underwriting chat assistant.",
    instruction=SYSTEM_INSTRUCTION,
    tools=[
        FunctionTool(query_submissions),
        FunctionTool(get_submission_detail),
        FunctionTool(get_urgency_ranking),
        FunctionTool(get_portfolio_stats),
        FunctionTool(explain_risk_score),
        FunctionTool(get_rules_summary),
        FunctionTool(get_pending_approvals),
        FunctionTool(get_processing_errors),
    ],
)

runner = Runner(
    app_name="smart_underwriter_agent",
    agent=agent,
    artifact_service=InMemoryArtifactService(),
    session_service=InMemorySessionService(),
    memory_service=InMemoryMemoryService(),
)

app = FastAPI(title="Smart Underwriter A2A Agent")


# Agent Card (discovery endpoint)
AGENT_CARD = {
    "name": "Smart Underwriter Agent",
    "description": "AI-powered underwriting assistant with real-time access to submission data, risk explanations, and portfolio analytics.",
    "url": os.environ.get("SERVICE_URL", ""),
    "skills": [
        {"id": "query_submissions", "name": "Query Submissions", "description": "Search and filter insurance submissions."},
        {"id": "explain_risk", "name": "Explain Risk Score", "description": "Explain risk score breakdown for a submission."},
        {"id": "portfolio_stats", "name": "Portfolio Statistics", "description": "Get portfolio-level statistics."},
        {"id": "submission_detail", "name": "Submission Details", "description": "Get full details of a submission."},
    ],
    "capabilities": {"streaming": False},
    "defaultInputModes": ["text"],
    "defaultOutputModes": ["text"],
}


@app.get("/.well-known/agent-card.json")
async def get_agent_card():
    """A2A discovery endpoint."""
    return JSONResponse(content=AGENT_CARD)


@app.post("/a2a/message")
async def send_message(request: Request):
    """A2A message endpoint — receives a message, returns agent response."""
    body = await request.json()
    message = body.get("message", {})
    parts = message.get("parts", [])
    user_text = ""
    for part in parts:
        if "text" in part:
            user_text = part["text"]
            break

    if not user_text:
        return JSONResponse(content={"error": "No text in message"}, status_code=400)

    user_id = message.get("metadata", {}).get("user_id", "servicenow_user")
    session_id = body.get("sessionId", str(uuid.uuid4()))

    # Get or create session
    session = await runner.session_service.get_session(
        app_name=runner.app_name, user_id=user_id, session_id=session_id
    )
    if not session:
        session = await runner.session_service.create_session(
            app_name=runner.app_name, user_id=user_id, session_id=session_id
        )

    content = types.Content(role="user", parts=[types.Part(text=user_text)])

    # Run agent
    final_event = None
    async for event in runner.run_async(
        session_id=session.id, user_id=user_id, new_message=content
    ):
        if event.is_final_response():
            final_event = event

    if final_event and final_event.content and final_event.content.parts:
        response_text = "".join(
            part.text for part in final_event.content.parts if hasattr(part, "text") and part.text
        )
        return JSONResponse(content={
            "task": {
                "id": str(uuid.uuid4()),
                "sessionId": session.id,
                "state": "completed",
                "artifacts": [{"parts": [{"text": response_text}]}],
            }
        })

    return JSONResponse(content={
        "task": {"id": str(uuid.uuid4()), "state": "failed", "error": "No response generated"}
    }, status_code=500)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
