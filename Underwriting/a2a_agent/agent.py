"""A2A Agent — Exposes the underwriting chat agent via Agent2Agent protocol."""
import os
import google.auth
from a2a.types import AgentSkill
from vertexai.preview.reasoning_engines.templates.a2a import create_agent_card
from vertexai.preview.reasoning_engines import A2aAgent

from executor import create_executor

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

# Define skills
skills = [
    AgentSkill(
        id="query_submissions",
        name="Query Submissions",
        description="Search and filter insurance submissions by priority, risk score, status, broker, or line of business.",
        tags=["Insurance", "Underwriting", "Submissions"],
        examples=["Show me all P0 priority submissions", "List submissions with risk score above 5"],
    ),
    AgentSkill(
        id="explain_risk",
        name="Explain Risk Score",
        description="Explain the risk score breakdown for a specific submission.",
        tags=["Insurance", "Risk", "Underwriting"],
        examples=["Explain the risk score for NB-26-34682"],
    ),
    AgentSkill(
        id="portfolio_stats",
        name="Portfolio Statistics",
        description="Get portfolio-level statistics including total submissions, risk distribution, and priority breakdown.",
        tags=["Insurance", "Analytics", "Portfolio"],
        examples=["Give me portfolio statistics"],
    ),
    AgentSkill(
        id="submission_detail",
        name="Submission Details",
        description="Get full details of a specific submission.",
        tags=["Insurance", "Underwriting", "Details"],
        examples=["Show me details for NB-26-34682"],
    ),
]

# Create AgentCard
agent_card = create_agent_card(
    agent_name="Smart Underwriter Agent",
    description="AI-powered underwriting assistant with real-time access to submission data, risk explanations, and portfolio analytics.",
    skills=skills,
)

# Create A2A Agent
a2a_agent = A2aAgent(
    agent_card=agent_card,
    agent_executor_builder=create_executor,
)
