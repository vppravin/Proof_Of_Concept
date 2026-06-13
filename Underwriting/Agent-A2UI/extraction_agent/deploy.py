import sys
import os
import vertexai
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp
from dotenv import load_dotenv
from google.api_core.exceptions import NotFound

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT = "gbu-demo-playground"
LOCATION = "us-central1"
BUCKET_URI = "gs://underwriting-workbench"
SERVICE_ACCOUNT = "146646146609-compute@developer.gserviceaccount.com"

AGENT_RESOURCE_NAME = "projects/146646146609/locations/us-central1/reasoningEngines/1756184502104752128"

vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=BUCKET_URI)

from extraction_agent.agent import root_agent

print("Wrapping agent...")
adk_app = AdkApp(agent=root_agent, enable_tracing=True)

CONFIG = dict(
    agent_engine=adk_app,
    display_name="Underwriting_Extraction_Agent_v2",
    description="Extracts structured fields from ACORD_125, ACORD_140, Loss Run, Email with Gemini-based normalization and GCS location risk enrichment",
    requirements=["cloudpickle", "google-cloud-aiplatform", "pydantic", "google-adk", "google-genai>=1.69.0", "google-cloud-storage", "vertexai", "python-dotenv==1.2.1"],
    extra_packages=["./extraction_agent/"],
    service_account=SERVICE_ACCOUNT,
    env_vars={"GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true", "PROJECT_ID": PROJECT, "LOCATION": LOCATION, "BUCKET_NAME": "underwriting-workbench"},
)

if AGENT_RESOURCE_NAME:
    try:
        agent_engines.get(AGENT_RESOURCE_NAME)
        print(f"Updating existing agent: {AGENT_RESOURCE_NAME}")
        remote_app = agent_engines.update(resource_name=AGENT_RESOURCE_NAME, **CONFIG)
    except NotFound:
        print("Not found, creating new...")
        remote_app = agent_engines.create(**CONFIG)
else:
    remote_app = agent_engines.create(**CONFIG)

print(f"\n✅ Done! {remote_app.resource_name}")
