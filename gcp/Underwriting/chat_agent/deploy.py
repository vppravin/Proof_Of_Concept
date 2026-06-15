"""Deploy script for Chat Agent to Vertex AI Agent Engine."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import vertexai
from vertexai import agent_engines

PROJECT_ID = "gbu-demo-playground"
LOCATION = "us-central1"

vertexai.init(project=PROJECT_ID, location=LOCATION, staging_bucket="gs://underwriting-workbench")

SERVICE_ACCOUNT = "146646146609-compute@developer.gserviceaccount.com"
# Set after first deploy
AGENT_RESOURCE_NAME = os.getenv("CHAT_AGENT_ID", "")


def deploy():
    from vertexai.preview.reasoning_engines import AdkApp
    from agent import agent

    adk_app = AdkApp(agent=agent, enable_tracing=True)

    config = dict(
        agent_engine=adk_app,
        requirements=[
            "cloudpickle",
            "google-cloud-aiplatform[adk]",
            "pydantic",
            "google-adk",
            "google-genai>=1.69.0",
            "google-cloud-storage",
            "google-cloud-bigquery",
            "vertexai",
            "python-dotenv==1.2.1",
        ],
        display_name="Underwriting Chat Agent",
        description="Professional underwriting chat assistant — Q&A, justification, urgency ranking.",
        extra_packages=["./tools.py"],
        service_account=SERVICE_ACCOUNT,
        env_vars={
            "PROJECT_ID": PROJECT_ID,
            "LOCATION": LOCATION,
            "BUCKET_NAME": "underwriting-workbench",
        },
    )

    if AGENT_RESOURCE_NAME:
        print(f"Updating existing agent: {AGENT_RESOURCE_NAME}")
        remote_agent = agent_engines.update(resource_name=AGENT_RESOURCE_NAME, **config)
        print(f"✅ Updated: {remote_agent.resource_name}")
    else:
        print("Creating new chat agent...")
        remote_agent = agent_engines.create(**config)
        print(f"✅ Created: {remote_agent.resource_name}")
        print(f"   Set CHAT_AGENT_ID={remote_agent.resource_name} for future updates")

    return remote_agent


if __name__ == "__main__":
    deploy()
