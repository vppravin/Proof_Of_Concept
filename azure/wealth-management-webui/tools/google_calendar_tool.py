"""
title: Google Calendar Connector
description: View and create Google Calendar events
author: WM
version: 1.0.0
"""

import json
from datetime import datetime, timezone
from pydantic import BaseModel
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class Tools:
    class Valves(BaseModel):
        GOOGLE_CLIENT_ID: str = "<your-client-id>"
        GOOGLE_CLIENT_SECRET: str = "<your-client-secret>"
        GOOGLE_REFRESH_TOKEN: str = "<your-refresh-token>"
        CALENDAR_ID: str = "primary"

    def __init__(self):
        self.valves = self.Valves()

    def _service(self):
        creds = Credentials(
            token=None,
            refresh_token=self.valves.GOOGLE_REFRESH_TOKEN,
            client_id=self.valves.GOOGLE_CLIENT_ID,
            client_secret=self.valves.GOOGLE_CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
        )
        return build("calendar", "v3", credentials=creds)

    def list_events(self, max_results: int = 10) -> str:
        """List upcoming Google Calendar events."""
        try:
            service = self._service()
            now = datetime.now(timezone.utc).isoformat()
            events = service.events().list(
                calendarId=self.valves.CALENDAR_ID,
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            items = events.get("items", [])
            if not items:
                return "No upcoming events found."
            lines = []
            for e in items:
                start = e["start"].get("dateTime", e["start"].get("date", ""))
                lines.append(f"**{e.get('summary', 'No Title')}**\n• Start: {start}\n• Location: {e.get('location', 'N/A')}\n• Description: {e.get('description', 'N/A')}")
            return "\n\n".join(lines)
        except Exception as e:
            return f"Error: {str(e)}"

    def create_event(self, title: str, start_datetime: str, end_datetime: str, description: str = "", location: str = "") -> str:
        """Create a Google Calendar event. Datetime format: 2024-01-15T10:00:00"""
        try:
            service = self._service()
            event = {
                "summary": title,
                "location": location,
                "description": description,
                "start": {"dateTime": start_datetime, "timeZone": "UTC"},
                "end": {"dateTime": end_datetime, "timeZone": "UTC"},
            }
            result = service.events().insert(calendarId=self.valves.CALENDAR_ID, body=event).execute()
            return f"Event created: {result.get('summary')} | Link: {result.get('htmlLink')}"
        except Exception as e:
            return f"Error: {str(e)}"

    def delete_event(self, event_id: str) -> str:
        """Delete a Google Calendar event by event ID."""
        try:
            service = self._service()
            service.events().delete(calendarId=self.valves.CALENDAR_ID, eventId=event_id).execute()
            return f"Event {event_id} deleted successfully."
        except Exception as e:
            return f"Error: {str(e)}"
