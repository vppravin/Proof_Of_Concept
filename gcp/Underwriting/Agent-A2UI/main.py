"""A2UI Underwriting Workbench — FastAPI entry point for Cloud Run."""

import logging
import os

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from agent import UnderwritingAgent
from agent_executor import UnderwritingAgentExecutor
from dotenv import load_dotenv
import uvicorn

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def serve():
    """Starts the A2A server."""
    try:
        host = "0.0.0.0"
        port = int(os.environ.get("PORT", 8080))
        external_facing_base_url = os.environ.get("AGENT_URL", f"http://{host}:{port}")

        agent = UnderwritingAgent(base_url=external_facing_base_url)
        agent_executor = UnderwritingAgentExecutor(agent=agent)
        request_handler = DefaultRequestHandler(
            agent_executor=agent_executor,
            task_store=InMemoryTaskStore(),
        )
        server = A2AStarletteApplication(
            agent_card=agent.agent_card, http_handler=request_handler
        )
        app = server.build()

        print(f"Running Underwriting Workbench on {host}:{port}")
        uvicorn.run(app, host=host, port=port)

    except Exception as e:
        logger.error(f"Server startup error: {e}")
        exit(1)


if __name__ == "__main__":
    serve()
