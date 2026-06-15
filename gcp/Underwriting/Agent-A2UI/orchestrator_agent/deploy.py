import os
import sys
import vertexai
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp
from dotenv import load_dotenv
from google.api_core.exceptions import NotFound

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

PROJECT = "gbu-demo-playground"
LOCATION = "us-central1"
BUCKET_URI = "gs://underwriting-workbench"

# After first deployment, set this for updates
AGENT_RESOURCE_NAME = "projects/146646146609/locations/us-central1/reasoningEngines/8799392106847141888"

SERVICE_ACCOUNT = "146646146609-compute@developer.gserviceaccount.com"

vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=BUCKET_URI)

import orchestrator_agent.agent as agent_module

print("Wrapping agent for deployment...")
adk_app = AdkApp(agent=agent_module.root_agent, enable_tracing=True)

DEPLOY_CONFIG = dict(
    agent_engine=adk_app,
    display_name="Underwriting_Orchestrator_Agent",
    description="Orchestrates the full underwriting workbench — classifies, extracts, evaluates rules, fetches client history, saves to BigQuery, and records accept/decline decisions",
    requirements=[
        "cloudpickle",
        "google-cloud-aiplatform",
        "pydantic",
        "google-adk",
        "google-genai>=1.69.0",
        "google-cloud-storage",
        "google-cloud-bigquery",
        "vertexai",
        "python-dotenv==1.2.1",
        "openpyxl",
    ],
    extra_packages=[
        "./orchestrator_agent/",
        "./classification_agent/",
        "./extraction_agent/",
        "./rules_update_agent/",
        "./client_history_agent/",
        "./uw_rules_agent/",
        "./submission_agent/",
    ],
    service_account=SERVICE_ACCOUNT,
    env_vars={
        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
        "PROJECT_ID": PROJECT,
        "LOCATION": LOCATION,
        "BUCKET_NAME": "underwriting-workbench",
        "BQ_DATASET": "underwriting_workbench",
    },
)

if AGENT_RESOURCE_NAME:
    try:
        print(f"Checking if agent exists: {AGENT_RESOURCE_NAME}")
        existing_agent = agent_engines.get(AGENT_RESOURCE_NAME)
        print("Agent found. Updating existing agent...")
        remote_app = agent_engines.update(resource_name=AGENT_RESOURCE_NAME, **DEPLOY_CONFIG)
    except NotFound:
        print("Agent not found. Creating new agent...")
        AGENT_RESOURCE_NAME = None

if not AGENT_RESOURCE_NAME:
    print("Creating agent for the first time...")
    remote_app = agent_engines.create(**DEPLOY_CONFIG)

print(f"\n✅ Deployment successful!")
print(f"Reasoning Engine: {remote_app.resource_name}")
print(f"Display Name: Underwriting_Orchestrator_Agent")
print(f"\n⚠️  Set AGENT_RESOURCE_NAME for future updates:")
print(f'AGENT_RESOURCE_NAME = "{remote_app.resource_name}"')
