from fastapi import FastAPI, Security, HTTPException
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
import os

app = FastAPI(title="Gmail Tool Server", version="1.0.0")

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
    return build("gmail", "v1", credentials=creds)

class ListEmailsInput(BaseModel):
    max_results: int = 10
    query: str = "is:unread"

class EmailIdInput(BaseModel):
    email_id: str

class SendEmailInput(BaseModel):
    to: str
    subject: str
    body: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/list_emails", summary="List Gmail emails")
def list_emails(body: ListEmailsInput, auth: str = Security(api_key_header)):
    """List emails from Gmail. Query examples: 'is:unread', 'from:someone@example.com'"""
    verify_key(auth)
    try:
        service = get_service()
        result = service.users().messages().list(userId="me", q=body.query, maxResults=body.max_results).execute()
        messages = result.get("messages", [])
        if not messages:
            return {"result": "No emails found."}
        lines = []
        for msg in messages:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
            lines.append(f"Subject: {headers.get('Subject','N/A')} | From: {headers.get('From','N/A')} | Date: {headers.get('Date','N/A')} | ID: {msg['id']}")
        return {"result": "\n".join(lines)}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}

@app.post("/read_email", summary="Read full body of an email by ID")
def read_email(body: EmailIdInput, auth: str = Security(api_key_header)):
    """Read the full content of a Gmail email by its message ID."""
    verify_key(auth)
    try:
        service = get_service()
        msg = service.users().messages().get(userId="me", id=body.email_id, format="full").execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        email_body = ""
        for part in msg["payload"].get("parts", []):
            if part["mimeType"] == "text/plain":
                data = part["body"].get("data", "")
                email_body = base64.urlsafe_b64decode(data).decode("utf-8")
                break
        if not email_body:
            data = msg["payload"]["body"].get("data", "")
            email_body = base64.urlsafe_b64decode(data).decode("utf-8") if data else "No body content."
        return {"result": f"Subject: {headers.get('Subject','N/A')}\nFrom: {headers.get('From','N/A')}\nDate: {headers.get('Date','N/A')}\n\n{email_body}"}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}

@app.post("/send_email", summary="Send an email via Gmail")
def send_email(body: SendEmailInput, auth: str = Security(api_key_header)):
    """Send an email via Gmail."""
    verify_key(auth)
    try:
        service = get_service()
        message = MIMEText(body.body)
        message["to"] = body.to
        message["subject"] = body.subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"result": f"Email sent. Message ID: {result['id']}"}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}
