"""Deploy the A2A underwriting chat agent to Agent Runtime."""
import vertexai
from vertexai.preview import reasoning_engines

PROJECT_ID = "gbu-demo-playground"
LOCATION = "us-central1"

vertexai.init(project=PROJECT_ID, location=LOCATION, staging_bucket="gs://underwriting-workbench")

from agent import a2a_agent

remote_agent = reasoning_engines.ReasoningEngine.create(
    a2a_agent,
    requirements=[
        "google-cloud-aiplatform[adk,agent_engines]==1.144.0",
        "a2a-sdk==0.3.26",
        "google-cloud-bigquery",
        "google-cloud-storage",
        "protobuf==6.33.6",
    ],
    extra_packages=[
        "./tools.py",
        "./executor.py",
    ],
    display_name="smart_underwriter_agent",
    description="A2A-enabled Smart Underwriter Agent for ServiceNow integration",
)

print(f"✅ Deployed: {remote_agent.resource_name}")
