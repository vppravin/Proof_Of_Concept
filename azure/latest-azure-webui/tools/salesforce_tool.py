"""
title: Salesforce Connector
description: Query and manage Salesforce records
author: WM
version: 1.0.0
"""

from simple_salesforce import Salesforce
from pydantic import BaseModel


class Tools:
    class Valves(BaseModel):
        SF_USERNAME: str = "midhunavarshini@virtusa.com"
        SF_PASSWORD: str = "Midhuna@21"
        SF_SECURITY_TOKEN: str = "ZubFIeR3VIf57NwnyNvOuRfz"

    def __init__(self):
        self.valves = self.Valves()

    def _sf(self):
        return Salesforce(
            username=self.valves.SF_USERNAME,
            password=self.valves.SF_PASSWORD,
            security_token=self.valves.SF_SECURITY_TOKEN,
        )

    def search_contacts(self, name: str) -> str:
        """Search Salesforce contacts by name."""
        sf = self._sf()
        result = sf.query(
            f"SELECT Id, FirstName, LastName, Email, Phone, Account.Name FROM Contact WHERE Name LIKE '%{name}%' LIMIT 10"
        )
        records = result.get("records", [])
        if not records:
            return "No contacts found."
        return "\n".join(
            [f"{r['FirstName']} {r['LastName']} | {r.get('Email','')} | {r.get('Phone','')} | {(r.get('Account') or {}).get('Name','')}" for r in records]
        )

    def search_accounts(self, name: str) -> str:
        """Search Salesforce accounts by name."""
        sf = self._sf()
        result = sf.query(
            f"SELECT Id, Name, Industry, Phone, Website FROM Account WHERE Name LIKE '%{name}%' LIMIT 10"
        )
        records = result.get("records", [])
        if not records:
            return "No accounts found."
        return "\n".join(
            [f"{r['Name']} | {r.get('Industry','')} | {r.get('Phone','')} | {r.get('Website','')}" for r in records]
        )

    def get_opportunities(self, account_name: str) -> str:
        """Get open opportunities for an account."""
        sf = self._sf()
        result = sf.query(
            f"SELECT Id, Name, StageName, Amount, CloseDate FROM Opportunity WHERE Account.Name LIKE '%{account_name}%' AND IsClosed = false LIMIT 10"
        )
        records = result.get("records", [])
        if not records:
            return "No open opportunities found."
        return "\n".join(
            [f"{r['Name']} | {r['StageName']} | ${r.get('Amount') or 0:,.0f} | Close: {r.get('CloseDate','')}" for r in records]
        )

    def create_lead(self, first_name: str, last_name: str, email: str, company: str) -> str:
        """Create a new lead in Salesforce."""
        sf = self._sf()
        result = sf.Lead.create({
            "FirstName": first_name,
            "LastName": last_name,
            "Email": email,
            "Company": company,
        })
        if result.get("success"):
            return f"Lead created successfully. ID: {result['id']}"
        return f"Failed to create lead: {result}"

    def run_soql(self, query: str) -> str:
        """Run a custom SOQL query."""
        sf = self._sf()
        result = sf.query(query)
        records = result.get("records", [])
        if not records:
            return "No records found."
        keys = [k for k in records[0].keys() if k != "attributes"]
        rows = [" | ".join(str(r.get(k, "")) for k in keys) for r in records]
        return "\n".join([" | ".join(keys)] + rows)
