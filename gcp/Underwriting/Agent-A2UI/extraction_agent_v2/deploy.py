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

AGENT_RESOURCE_NAME = "projects/146646146609/locations/us-central1/reasoningEngines/8617150253566525440"  # Set after first deploy

vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=BUCKET_URI)

from extraction_agent_v2.agent import root_agent

print("Wrapping agent...")
adk_app = AdkApp(agent=root_agent, enable_tracing=True)

CONFIG = dict(
    agent_engine=adk_app,
    display_name="Underwriting_Extraction_Agent_v2_DocAI",
    description="Extracts structured fields from ACORD 125/140 using Document AI Form Parser. Saves results to GCS.",
    requirements=["cloudpickle", "google-cloud-aiplatform", "pydantic", "google-adk", "google-genai>=1.69.0", "google-cloud-storage", "google-cloud-documentai", "vertexai", "python-dotenv==1.2.1"],
    extra_packages=["./extraction_agent_v2/", "./extraction_agent/"],
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
    print("Creating agent for the first time...")
    remote_app = agent_engines.create(**CONFIG)

print(f"\n✅ Done! {remote_app.resource_name}")
print(f"Set AGENT_RESOURCE_NAME = \"{remote_app.resource_name}\"")
