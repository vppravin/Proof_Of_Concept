import os
import logging
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [360_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

llm = AzureChatOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-15-preview",
    deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT", "wm-gpt4o"),
    temperature=0,
    streaming=True
)

mcp_server_url = os.getenv("MCP_SERVER_URL", "https://agent-360-mcp.livelybay-96634f40.eastus2.azurecontainerapps.io/mcp")
logger.info(f"MCP Server URL: {mcp_server_url}")

mcp_client = MultiServerMCPClient(
    {
        "agent_360_mcp": {
            "transport": "http",
            "url": mcp_server_url
        }
    }
)

class QueryRequest(BaseModel):
    query: str

tools = None
agent_executor = None

async def initialize_agent():
    global tools, agent_executor
    try:
        logger.info("Initializing MCP client and loading tools...")
        tools = await mcp_client.get_tools()
        logger.info(f"Loaded {len(tools)} tools from MCP server")

        system_message = """When the user provides a customer's full name (e.g., "Peter Griffin"), call the tool "agent_360_summary_with_pdf" with the name as a string parameter.

This tool will:
- Analyze the customer's financial data across SDI, SMA, Checking, Savings, Managed, and Funds
- Generate AI-powered insights for each section
- Create a detailed PDF report
- Return a URL to view/download the PDF

Respond with only the PDF report URL returned from the tool. Do not add extra interpretation or summary.

Output formatting rules:
- If the response contains structured data with multiple fields that can be represented as rows and columns, use a markdown table.
- If the response is a single value, URL, or narrative text, output it as plain text without forcing a table.
- Never suppress or omit any data from the tool response."""

        agent_executor = create_react_agent(llm, tools, prompt=system_message)
        logger.info("✅ Agent initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize agent: {e}")
        raise

@app.on_event("startup")
async def startup_event():
    await initialize_agent()

@app.get("/health")
async def health():
    return {"status": "healthy", "tools_loaded": len(tools) if tools else 0}

@app.post("/query")
async def query(request: QueryRequest):
    logger.info(f"Processing query: {request.query}")

    if agent_executor is None:
        return {"error": "Agent not initialized. Please wait for startup to complete."}

    async def event_generator():
        line_buffer = ""
        try:
            async for event in agent_executor.astream_events(
                {"messages": [("user", request.query)]}, version="v2"
            ):
                if event["event"] == "on_chat_model_stream":
                    content = event["data"]["chunk"].content
                    if not content:
                        continue
                    line_buffer += content
                    while "\n" in line_buffer:
                        line, line_buffer = line_buffer.split("\n", 1)
                        yield f"data: {line}\n\n"

            if line_buffer.strip():
                yield f"data: {line_buffer}\n\n"

        except Exception as e:
            logger.error(f"Error executing agent: {e}")
            yield f"data: ❌ Error: {str(e)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                              headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})
