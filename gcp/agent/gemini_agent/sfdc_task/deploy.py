import os
import sys
import vertexai
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp
from dotenv import load_dotenv
from google.api_core.exceptions import NotFound

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent as sfdc_agent

# Load environment variables
load_dotenv()

# Initialize Vertex AI
PROJECT = "gbu-demo-playground"
LOCATION = "us-central1"
BUCKET_URI = "gs://wm_agent"

# 🔒 FIXED agent resource (DO NOT CHANGE)
# TODO: After first deployment, add the resource name here
AGENT_RESOURCE_NAME = ("projects/146646146609/"
    "locations/us-central1/"
    "reasoningEngines/5513810020250157056")  # Set this after first deployment

vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=BUCKET_URI)

print("Wrapping agent for deployment...")
adk_app = AdkApp(agent=sfdc_agent.root_agent, enable_tracing=True)

print("Deploying to Vertex AI Reasoning Engine...")

if AGENT_RESOURCE_NAME:
    try:
        print(f"Checking if agent exists: {AGENT_RESOURCE_NAME}")
        existing_agent = agent_engines.get(AGENT_RESOURCE_NAME)

        print("Agent found. Updating existing agent...")
        remote_app = agent_engines.update(
            resource_name=AGENT_RESOURCE_NAME,
            agent_engine=adk_app,
            display_name=sfdc_agent.root_agent.name,
            description="SFDC Task Manager with retry logic and logging",
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
            extra_packages=["./sfdc_task/"],
            env_vars={
                "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
                "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
                "MCP_SERVER_URL": "https://mcp-sfdctask-146646146609.us-central1.run.app/sse",
            },
        )
    except NotFound:
        print("Agent not found. Creating new agent...")
        AGENT_RESOURCE_NAME = None

if not AGENT_RESOURCE_NAME:
    print("Creating agent for the first time...")
    remote_app = agent_engines.create(
        agent_engine=adk_app,
        display_name=sfdc_agent.root_agent.name,
        description="SFDC Task Manager with retry logic and logging",
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
        extra_packages=["./sfdc_task/"],
        env_vars={
            "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
            "MCP_SERVER_URL": "https://mcp-sfdctask-146646146609.us-central1.run.app/sse",
        },
    )

print("\n✅ Deployment successful")
print(f"Reasoning Engine: {remote_app.resource_name}")
print(f"Display Name: sfdc_agent.root_agent.name")
print("\n⚠️  IMPORTANT: Copy the resource name above and set AGENT_RESOURCE_NAME in this file for future updates")
