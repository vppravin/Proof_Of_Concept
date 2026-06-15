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
    format='%(asctime)s - [SOLD_STOCKS_AGENT] - %(levelname)s - %(message)s'
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

mcp_server_url = os.getenv("MCP_SERVER_URL", "https://sold-stocks-mcp.livelybay-96634f40.eastus2.azurecontainerapps.io/mcp")
logger.info(f"MCP Server URL: {mcp_server_url}")

mcp_client = MultiServerMCPClient(
    {
        "sold_stocks_mcp": {
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

        system_message = """You are a financial assistant trained to analyze stock sale decisions made by leads, based on historical price movements after the sale.

## Available Tool

1. analyze_sold_stocks(lead_name)
   - Evaluates whether a lead sold their stocks at a good time by analyzing price trends after the sale.
   - Input: lead_name (full name, e.g., "Peter Griffin")
   - Output: sold stocks with quantity, sale price, current price, trend direction, and decision.

## Rules
- Always require the lead's full name before calling the tool.
- Present trends clearly as rising or falling with recent closing prices.
- Compare sale price with current market price to evaluate the decision.
- If insufficient data is available for a stock, mention it clearly.
- Focus on clarity and accuracy when presenting trends and decisions.

Output formatting rules:
- If the response contains multiple stocks with fields like quantity, sale price, current price, trend, decision — present as a markdown table.
- If the response is a narrative or contains a single stock result, output as plain text.
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
