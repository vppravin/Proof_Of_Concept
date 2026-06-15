from fastapi import FastAPI, Security, HTTPException
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import os

app = FastAPI(title="Google Calendar Tool Server", version="1.0.0")

API_KEY = os.environ.get("TOOL_API_KEY", "wm-router-2026-secret")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

def verify_key(auth: str = Security(api_key_header)):
    if not auth or auth.replace("Bearer ", "") != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

def get_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("calendar", "v3", credentials=creds)

CALENDAR_ID = os.environ.get("CALENDAR_ID", "primary")

class EventInput(BaseModel):
    title: str
    start_datetime: str
    end_datetime: str
    description: str = ""
    location: str = ""

class EventIdInput(BaseModel):
    event_id: str

class MaxResultsInput(BaseModel):
    max_results: int = 10

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/list_events", summary="List upcoming Google Calendar events")
def list_events(body: MaxResultsInput, auth: str = Security(api_key_header)):
    """List upcoming events from Google Calendar."""
    verify_key(auth)
    try:
        service = get_service()
        now = datetime.now(timezone.utc).isoformat()
        events = service.events().list(
            calendarId=CALENDAR_ID, timeMin=now,
            maxResults=body.max_results, singleEvents=True, orderBy="startTime"
        ).execute()
        items = events.get("items", [])
        if not items:
            return {"result": "No upcoming events found."}
        lines = []
        for e in items:
            start = e["start"].get("dateTime", e["start"].get("date", ""))
            lines.append(f"{e.get('summary','No Title')} | Start: {start} | Location: {e.get('location','N/A')}")
        return {"result": "\n".join(lines)}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}

@app.post("/create_event", summary="Create a Google Calendar event")
def create_event(body: EventInput, auth: str = Security(api_key_header)):
    """Create a new event in Google Calendar. Datetime format: 2024-01-15T10:00:00"""
    verify_key(auth)
    try:
        service = get_service()
        event = {
            "summary": body.title,
            "location": body.location,
            "description": body.description,
            "start": {"dateTime": body.start_datetime, "timeZone": "UTC"},
            "end": {"dateTime": body.end_datetime, "timeZone": "UTC"},
        }
        result = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        return {"result": f"Event created: {result.get('summary')} | Link: {result.get('htmlLink')}"}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}

@app.post("/delete_event", summary="Delete a Google Calendar event by ID")
def delete_event(body: EventIdInput, auth: str = Security(api_key_header)):
    """Delete a Google Calendar event by its event ID."""
    verify_key(auth)
    try:
        get_service().events().delete(calendarId=CALENDAR_ID, eventId=body.event_id).execute()
        return {"result": f"Event {body.event_id} deleted successfully."}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}
