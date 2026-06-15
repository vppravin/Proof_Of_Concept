import sys
import os
import vertexai
from vertexai import agent_engines
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT = "gbu-demo-playground"
LOCATION = "us-central1"
BUCKET_URI = "gs://wm_agent"
ENGINE_ID = "1891494801065377792"
RESOURCE_NAME = f"projects/146646146609/locations/{LOCATION}/reasoningEngines/{ENGINE_ID}"

from mlr_agent.agent import root_agent

client = vertexai.Client(project=PROJECT, location=LOCATION)

print(f"Loading existing agent engine: {ENGINE_ID}")
remote_agent = client.agent_engines.get(name=RESOURCE_NAME)

print("Wrapping updated agent...")
app = agent_engines.AdkApp(agent=root_agent, enable_tracing=True)

print("Updating agent engine (this takes a few minutes)...")
remote_agent = client.agent_engines.update(
    name=RESOURCE_NAME,
    agent=app,
    config={
        "requirements": [
            "google-cloud-aiplatform[agent_engines,adk]",
            "google-cloud-storage",
            "google-genai>=1.69.0",
            "python-dotenv==1.2.1",
            "httpx",
        ],
        "stagingBucket": BUCKET_URI,
        "extraPackages": ["./mlr_agent/"],
        "displayName": "MLR_Document_Validator_Agent",
        "description": "MLR Document Validator Agent - uploads documents, runs compliance validation, and provides detailed review results",
        "envVars": {
            "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
            "BACKEND_URL": "https://backend-fastapi-1090458629658.us-central1.run.app",
            "GCS_UPLOAD_BUCKET": "mlr_document",
            "GCS_UPLOAD_PREFIX": "agent_uploads",
        },
        "pythonVersion": "3.11",
    },
)

print(f"\n✅ Successfully updated!")
print(f"Reasoning Engine: {remote_agent.api_resource.name}")
print(f"Display Name: MLR_Document_Validator_Agent")
