"""
title: ServiceNow Connector
description: Query and manage ServiceNow incidents and tasks
author: WM
version: 1.0.0
"""

import pysnow
from pydantic import BaseModel


class Tools:
    class Valves(BaseModel):
        SN_INSTANCE: str = "<your-instance>"
        SN_USERNAME: str = "<your-username>"
        SN_PASSWORD: str = "<your-password>"

    def __init__(self):
        self.valves = self.Valves()

    def _client(self):
        return pysnow.Client(
            instance=self.valves.SN_INSTANCE,
            user=self.valves.SN_USERNAME,
            password=self.valves.SN_PASSWORD,
        )

    def get_incidents(self, limit: int = 10, state: str = "") -> str:
        """Get ServiceNow incidents. State: 1=New, 2=In Progress, 3=On Hold, 6=Resolved, 7=Closed"""
        try:
            client = self._client()
            table = client.resource(api_path="/table/incident")
            query = {}
            if state:
                query["state"] = state
            response = table.get(query=query, limit=limit)
            records = response.all()
            if not records:
                return "No incidents found."
            lines = []
            for r in records:
                lines.append(
                    f"**{r.get('number', 'N/A')}: {r.get('short_description', 'N/A')}**\n"
                    f"• State: {r.get('state', 'N/A')}\n"
                    f"• Priority: {r.get('priority', 'N/A')}\n"
                    f"• Assigned To: {r.get('assigned_to', {}).get('display_value', 'Unassigned')}\n"
                    f"• Created: {r.get('sys_created_on', 'N/A')}"
                )
            return "\n\n".join(lines)
        except Exception as e:
            return f"Error: {str(e)}"

    def get_incident(self, number: str) -> str:
        """Get a specific ServiceNow incident by number (e.g. INC0001234)."""
        try:
            client = self._client()
            table = client.resource(api_path="/table/incident")
            response = table.get(query={"number": number})
            r = response.one()
            return (
                f"**{r.get('number')}: {r.get('short_description')}**\n"
                f"• State: {r.get('state')}\n"
                f"• Priority: {r.get('priority')}\n"
                f"• Category: {r.get('category')}\n"
                f"• Assigned To: {r.get('assigned_to', {}).get('display_value', 'Unassigned')}\n"
                f"• Description: {r.get('description', 'N/A')}\n"
                f"• Created: {r.get('sys_created_on')}\n"
                f"• Updated: {r.get('sys_updated_on')}"
            )
        except Exception as e:
            return f"Error: {str(e)}"

    def create_incident(self, short_description: str, description: str = "", urgency: str = "3") -> str:
        """Create a ServiceNow incident. Urgency: 1=High, 2=Medium, 3=Low"""
        try:
            client = self._client()
            table = client.resource(api_path="/table/incident")
            result = table.create(payload={
                "short_description": short_description,
                "description": description,
                "urgency": urgency,
            })
            r = result.one()
            return f"Incident created: {r.get('number')} | {r.get('short_description')}"
        except Exception as e:
            return f"Error: {str(e)}"

    def update_incident(self, number: str, state: str = "", notes: str = "") -> str:
        """Update a ServiceNow incident state or add notes."""
        try:
            client = self._client()
            table = client.resource(api_path="/table/incident")
            payload = {}
            if state:
                payload["state"] = state
            if notes:
                payload["work_notes"] = notes
            response = table.get(query={"number": number})
            response.update(payload)
            return f"Incident {number} updated successfully."
        except Exception as e:
            return f"Error: {str(e)}"
