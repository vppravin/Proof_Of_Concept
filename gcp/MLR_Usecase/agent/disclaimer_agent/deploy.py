import os
import sys
import vertexai
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent as disclaimer_agent

load_dotenv()

PROJECT = "gbu-demo-playground"
LOCATION = "us-central1"
BUCKET_URI = "gs://wm_agent"

vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=BUCKET_URI)

print("Wrapping agent for deployment...")
adk_app = AdkApp(agent=disclaimer_agent.root_agent, enable_tracing=True)

print("Deploying to Vertex AI Reasoning Engine...")
remote_app = agent_engines.create(
    adk_app,
    display_name=disclaimer_agent.root_agent.name,
    description="MLR Disclaimer Validation Agent - scans content, validates disclaimers, auto-edits documents",
    requirements=[
        "cloudpickle",
        "google-cloud-aiplatform",
        "pydantic",
        "google-adk==1.28.0",
        "google-genai==1.69.0",
        "python-dotenv==1.2.1",
        "mcp==1.26.0",
        "httpx-sse==0.4.3",
    ],
    extra_packages=["./disclaimer_agent/"],
    env_vars={
        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
        "MCP_SERVER_URL": "https://mcp-disclaimer-agent-146646146609.us-central1.run.app/mcp",
    },
)

print(f"\n✅ Successfully deployed!")
print(f"Reasoning Engine: {remote_app.resource_name}")
print(f"Display Name: {disclaimer_agent.root_agent.name}")
