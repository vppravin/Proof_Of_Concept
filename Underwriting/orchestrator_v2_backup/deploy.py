"""Deploy script for Orchestrator v2 to Vertex AI Agent Engine."""

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
AGENT_RESOURCE_NAME = "projects/146646146609/locations/us-central1/reasoningEngines/3721156916475330560"


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
            "google-cloud-documentai",
            "google-cloud-bigquery",
            "openpyxl",
            "vertexai",
            "python-dotenv==1.2.1",
        ],
        display_name="Orchestrator Agent v2 (Single LLM)",
        description="Unified orchestrator — all tools inline, zero sub-agents.",
        extra_packages=[
            "./tools_classification.py",
            "./tools_extraction.py",
            "./tools_location_risk.py",
            "./tools_client_history.py",
            "./tools_rules.py",
            "./tools_submission.py",
        ],
        service_account=SERVICE_ACCOUNT,
        env_vars={
            "PROJECT_ID": PROJECT_ID,
            "LOCATION": LOCATION,
            "BUCKET_NAME": "underwriting-workbench",
            "BQ_DATASET": "underwriting_workbench",
            "DOCAI_PROCESSOR": "projects/146646146609/locations/us/processors/5580fe010b37636d",
        },
    )

    print(f"Updating existing agent: {AGENT_RESOURCE_NAME}")
    remote_agent = agent_engines.update(resource_name=AGENT_RESOURCE_NAME, **config)
    print(f"✅ Updated: {remote_agent.resource_name}")
    return remote_agent


if __name__ == "__main__":
    deploy()
