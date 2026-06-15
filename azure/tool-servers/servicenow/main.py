from fastapi import FastAPI, Security, HTTPException
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
import requests
import os

app = FastAPI(title="ServiceNow Tool Server", version="1.0.0")

API_KEY = os.environ.get("TOOL_API_KEY", "wm-router-2026-secret")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

SN_INSTANCE = os.environ.get("SN_INSTANCE", "")
SN_USERNAME = os.environ.get("SN_USERNAME", "")
SN_PASSWORD = os.environ.get("SN_PASSWORD", "")
SN_BASE_URL = f"https://{SN_INSTANCE}.service-now.com/api/now/table"

def verify_key(auth: str = Security(api_key_header)):
    if not auth or auth.replace("Bearer ", "") != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

def sn_get(path: str, params: dict = {}):
    resp = requests.get(
        f"{SN_BASE_URL}/{path}",
        auth=(SN_USERNAME, SN_PASSWORD),
        headers={"Accept": "application/json"},
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("result", [])

def sn_post(path: str, payload: dict):
    resp = requests.post(
        f"{SN_BASE_URL}/{path}",
        auth=(SN_USERNAME, SN_PASSWORD),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("result", {})

def sn_patch(path: str, payload: dict):
    resp = requests.patch(
        f"{SN_BASE_URL}/{path}",
        auth=(SN_USERNAME, SN_PASSWORD),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("result", {})

class IncidentNumberInput(BaseModel):
    number: str

class GetIncidentsInput(BaseModel):
    limit: int = 10
    state: str = ""

class CreateIncidentInput(BaseModel):
    short_description: str
    description: str = ""
    urgency: str = "3"

class UpdateIncidentInput(BaseModel):
    number: str
    state: str = ""
    notes: str = ""

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/get_incidents", summary="Get ServiceNow incidents")
def get_incidents(body: GetIncidentsInput, auth: str = Security(api_key_header)):
    """Get ServiceNow incidents. State: 1=New, 2=In Progress, 3=On Hold, 6=Resolved, 7=Closed"""
    verify_key(auth)
    try:
        params = {"sysparm_limit": body.limit, "sysparm_display_value": "true"}
        if body.state:
            params["sysparm_query"] = f"state={body.state}"
        records = sn_get("incident", params)
        if not records:
            return {"result": "No incidents found."}
        lines = []
        for r in records:
            assigned = r.get("assigned_to", {})
            assigned_name = assigned.get("display_value", "Unassigned") if isinstance(assigned, dict) else assigned or "Unassigned"
            lines.append(
                f"{r.get('number','N/A')}: {r.get('short_description','N/A')} | "
                f"State: {r.get('state','N/A')} | Priority: {r.get('priority','N/A')} | "
                f"Assigned: {assigned_name}"
            )
        return {"result": "\n".join(lines)}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}

@app.post("/get_incident", summary="Get a specific ServiceNow incident by number")
def get_incident(body: IncidentNumberInput, auth: str = Security(api_key_header)):
    """Get full details of a ServiceNow incident by number (e.g. INC0001234)."""
    verify_key(auth)
    try:
        params = {"sysparm_query": f"number={body.number}", "sysparm_display_value": "true", "sysparm_limit": 1}
        records = sn_get("incident", params)
        if not records:
            return {"result": f"No incident found with number {body.number}."}
        r = records[0]
        assigned = r.get("assigned_to", {})
        assigned_name = assigned.get("display_value", "Unassigned") if isinstance(assigned, dict) else assigned or "Unassigned"
        return {"result": (
            f"Number: {r.get('number')}\n"
            f"Description: {r.get('short_description')}\n"
            f"State: {r.get('state')} | Priority: {r.get('priority')} | Category: {r.get('category')}\n"
            f"Assigned To: {assigned_name}\n"
            f"Details: {r.get('description', 'N/A')}\n"
            f"Created: {r.get('sys_created_on')} | Updated: {r.get('sys_updated_on')}"
        )}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}

@app.post("/create_incident", summary="Create a ServiceNow incident")
def create_incident(body: CreateIncidentInput, auth: str = Security(api_key_header)):
    """Create a new ServiceNow incident. Urgency: 1=High, 2=Medium, 3=Low"""
    verify_key(auth)
    try:
        r = sn_post("incident", {
            "short_description": body.short_description,
            "description": body.description,
            "urgency": body.urgency,
        })
        return {"result": f"Incident created: {r.get('number')} | {r.get('short_description')}"}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}

@app.post("/update_incident", summary="Update a ServiceNow incident")
def update_incident(body: UpdateIncidentInput, auth: str = Security(api_key_header)):
    """Update state or add work notes to a ServiceNow incident by number."""
    verify_key(auth)
    try:
        # First get the sys_id
        params = {"sysparm_query": f"number={body.number}", "sysparm_fields": "sys_id", "sysparm_limit": 1}
        records = sn_get("incident", params)
        if not records:
            return {"result": f"No incident found with number {body.number}."}
        sys_id = records[0].get("sys_id")
        payload = {}
        if body.state:
            payload["state"] = body.state
        if body.notes:
            payload["work_notes"] = body.notes
        sn_patch(f"incident/{sys_id}", payload)
        return {"result": f"Incident {body.number} updated successfully."}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}
