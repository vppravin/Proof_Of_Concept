import os
import vertexai
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp
from dotenv import load_dotenv
from google.api_core.exceptions import NotFound
from agent import root_agent

# Load environment variables
load_dotenv()

# Initialize Vertex AI
PROJECT = "gbu-demo-playground"
LOCATION = "us-central1"
BUCKET_URI = "gs://wm_agent"

# 🔒 FIXED agent resource (DO NOT CHANGE)
AGENT_RESOURCE_NAME = (
    "projects/146646146609/"
    "locations/us-central1/"
    "reasoningEngines/6508120375480549376"
)

vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=BUCKET_URI)

print("Wrapping agent for deployment...")
adk_app = AdkApp(agent=root_agent, enable_tracing=True)

print("Deploying to Vertex AI Reasoning Engine...")

try:
    print(f"Checking if agent exists: {AGENT_RESOURCE_NAME}")
    existing_agent = agent_engines.get(AGENT_RESOURCE_NAME)

    print("Agent found. Updating existing agent...")
    remote_app = agent_engines.update(
        resource_name=AGENT_RESOURCE_NAME,
        agent_engine=adk_app,
        display_name=root_agent.name,
        description="Lead Prioritizer agent with retry logic and logging",
        requirements=[
            "cloudpickle",
            "google-cloud-aiplatform",
            "pydantic",
            "google-adk==1.28.0",
            "google-genai==1.69.0",
            "python-dotenv==1.2.1",
            "mcp",
            "httpx-sse",
        ],
        extra_packages=["."],
        env_vars={
            "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
            "MCP_SERVER_URL": "https://mcp-leadagent-146646146609.us-central1.run.app/sse",
        },
    )

except NotFound:
    print("Agent not found. Creating agent for the first time...")
    remote_app = agent_engines.create(
        agent_engine=adk_app,
        display_name=root_agent.name,
        description="Lead Prioritizer agent with retry logic and logging",
        requirements=[
            "cloudpickle",
            "google-cloud-aiplatform",
            "pydantic",
            "google-adk==1.28.0",
            "google-genai==1.69.0",
            "python-dotenv==1.2.1",
            "mcp",
            "httpx-sse",
        ],
        extra_packages=["."],
        env_vars={
            "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
            "MCP_SERVER_URL": "https://mcp-leadagent-146646146609.us-central1.run.app/sse",
        },
    )

print("\n✅ Deployment successful")
print(f"Reasoning Engine: {remote_app.resource_name}")
print(f"Display Name: {root_agent.name}")
