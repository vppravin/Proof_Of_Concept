from fastapi import FastAPI, Security, HTTPException
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from simple_salesforce import Salesforce
import os

app = FastAPI(title="Salesforce Tool Server", version="1.0.0")

API_KEY = os.environ.get("TOOL_API_KEY", "wm-router-2026-secret")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

def verify_key(auth: str = Security(api_key_header)):
    if not auth or auth.replace("Bearer ", "") != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

def sf():
    return Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
        domain="login"
    )

class NameInput(BaseModel):
    name: str

class SOQLInput(BaseModel):
    query: str

class LeadInput(BaseModel):
    first_name: str
    last_name: str
    email: str
    company: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/search_leads", summary="Search Salesforce leads by name")
def search_leads(body: NameInput, auth: str = Security(api_key_header)):
    """Search leads by name and return key details."""
    verify_key(auth)
    result = sf().query(f"SELECT Id, Name, Status, AnnualRevenue, LeadSource, Email, Phone, Company FROM Lead WHERE Name LIKE '%{body.name}%' LIMIT 10")
    records = result.get("records", [])
    if not records:
        return {"result": "No leads found."}
    return {"result": "\n".join(
        [f"{r.get('Name','')} | Status: {r.get('Status','')} | Revenue: ${r.get('AnnualRevenue') or 0:,.0f} | {r.get('Email','')} | {r.get('Company','')}" for r in records]
    )}

@app.post("/search_contacts", summary="Search Salesforce contacts by name")
def search_contacts(body: NameInput, auth: str = Security(api_key_header)):
    """Search contacts by name."""
    verify_key(auth)
    result = sf().query(f"SELECT Id, FirstName, LastName, Email, Phone, Account.Name FROM Contact WHERE Name LIKE '%{body.name}%' LIMIT 10")
    records = result.get("records", [])
    if not records:
        return {"result": "No contacts found."}
    return {"result": "\n".join(
        [f"{r['FirstName']} {r['LastName']} | {r.get('Email','')} | {r.get('Phone','')} | {(r.get('Account') or {}).get('Name','')}" for r in records]
    )}

@app.post("/search_accounts", summary="Search Salesforce accounts by name")
def search_accounts(body: NameInput, auth: str = Security(api_key_header)):
    """Search accounts by name."""
    verify_key(auth)
    result = sf().query(f"SELECT Id, Name, Industry, Phone, Website FROM Account WHERE Name LIKE '%{body.name}%' LIMIT 10")
    records = result.get("records", [])
    if not records:
        return {"result": "No accounts found."}
    return {"result": "\n".join(
        [f"{r['Name']} | {r.get('Industry','')} | {r.get('Phone','')} | {r.get('Website','')}" for r in records]
    )}

@app.post("/get_opportunities", summary="Get open opportunities for an account")
def get_opportunities(body: NameInput, auth: str = Security(api_key_header)):
    """Get open Salesforce opportunities for a given account name."""
    verify_key(auth)
    result = sf().query(f"SELECT Id, Name, StageName, Amount, CloseDate FROM Opportunity WHERE Account.Name LIKE '%{body.name}%' AND IsClosed = false LIMIT 10")
    records = result.get("records", [])
    if not records:
        return {"result": "No open opportunities found."}
    return {"result": "\n".join(
        [f"{r['Name']} | {r['StageName']} | ${r.get('Amount') or 0:,.0f} | Close: {r.get('CloseDate','')}" for r in records]
    )}

@app.post("/create_lead", summary="Create a new lead in Salesforce")
def create_lead(body: LeadInput, auth: str = Security(api_key_header)):
    """Create a new Salesforce lead."""
    verify_key(auth)
    result = sf().Lead.create({"FirstName": body.first_name, "LastName": body.last_name, "Email": body.email, "Company": body.company})
    if result.get("success"):
        return {"result": f"Lead created. ID: {result['id']}"}
    return {"result": f"Failed: {result}"}

@app.post("/run_soql", summary="Run a custom SOQL query")
def run_soql(body: SOQLInput, auth: str = Security(api_key_header)):
    """Execute any custom SOQL query against Salesforce."""
    verify_key(auth)
    result = sf().query(body.query)
    records = result.get("records", [])
    if not records:
        return {"result": "No records found."}
    keys = [k for k in records[0].keys() if k != "attributes"]
    rows = [" | ".join(str(r.get(k, "")) for k in keys) for r in records]
    return {"result": "\n".join([" | ".join(keys)] + rows)}
