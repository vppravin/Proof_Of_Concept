"""
title: Gmail Connector
description: Read and send Gmail emails
author: WM
version: 1.0.0
"""

import base64
from email.mime.text import MIMEText
from pydantic import BaseModel
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class Tools:
    class Valves(BaseModel):
        GOOGLE_CLIENT_ID: str = "<your-client-id>"
        GOOGLE_CLIENT_SECRET: str = "<your-client-secret>"
        GOOGLE_REFRESH_TOKEN: str = "<your-refresh-token>"

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
        return build("gmail", "v1", credentials=creds)

    def list_emails(self, max_results: int = 10, query: str = "is:unread") -> str:
        """List emails from Gmail inbox. Query examples: 'is:unread', 'from:someone@example.com'"""
        try:
            service = self._service()
            result = service.users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute()
            messages = result.get("messages", [])
            if not messages:
                return "No emails found."
            lines = []
            for msg in messages:
                detail = service.users().messages().get(
                    userId="me", id=msg["id"], format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]
                ).execute()
                headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
                lines.append(
                    f"**{headers.get('Subject', 'No Subject')}**\n"
                    f"• From: {headers.get('From', 'N/A')}\n"
                    f"• Date: {headers.get('Date', 'N/A')}\n"
                    f"• ID: {msg['id']}"
                )
            return "\n\n".join(lines)
        except Exception as e:
            return f"Error: {str(e)}"

    def read_email(self, email_id: str) -> str:
        """Read the full body of an email by its ID."""
        try:
            service = self._service()
            msg = service.users().messages().get(
                userId="me", id=email_id, format="full"
            ).execute()
            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            parts = msg["payload"].get("parts", [])
            body = ""
            for part in parts:
                if part["mimeType"] == "text/plain":
                    data = part["body"].get("data", "")
                    body = base64.urlsafe_b64decode(data).decode("utf-8")
                    break
            if not body:
                data = msg["payload"]["body"].get("data", "")
                body = base64.urlsafe_b64decode(data).decode("utf-8") if data else "No body content."
            return (
                f"**Subject:** {headers.get('Subject', 'N/A')}\n"
                f"**From:** {headers.get('From', 'N/A')}\n"
                f"**Date:** {headers.get('Date', 'N/A')}\n\n"
                f"{body}"
            )
        except Exception as e:
            return f"Error: {str(e)}"

    def send_email(self, to: str, subject: str, body: str) -> str:
        """Send an email via Gmail."""
        try:
            service = self._service()
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            result = service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
            return f"Email sent successfully. Message ID: {result['id']}"
        except Exception as e:
            return f"Error: {str(e)}"
