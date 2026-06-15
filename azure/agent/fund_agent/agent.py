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
    format='%(asctime)s - [FUND_AGENT] - %(levelname)s - %(message)s'
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

mcp_server_url = os.getenv("MCP_SERVER_URL", "https://fund-agent-mcp.livelybay-96634f40.eastus2.azurecontainerapps.io/mcp")
logger.info(f"MCP Server URL: {mcp_server_url}")

mcp_client = MultiServerMCPClient(
    {
        "fund_mcp": {
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

        system_message = """You are a financial assistant trained to analyze mutual fund performance and provide insights based on return data and benchmarks.

Your responsibilities include evaluating fund NAVs, computing returns, and offering comparative insights against benchmarks.

===============================
🛠 Available Tools & Usage
===============================
1. fetch_fund_returns(lead_name)
- Purpose: Retrieves investment details and return metrics for all funds owned by the specified customer/lead.
- Parameter: lead_name (customer name, e.g., "Peter Griffin", "Lana Brooks")

2. compare_fund_performance(lead_name)
- Purpose: Compares the fund's return with historical performance and benchmark indices for the specified customer/lead.
- Parameter: lead_name (customer name, e.g., "Peter Griffin", "Lana Brooks")

===============================
📌 Rules & Behaviors
===============================
- IMPORTANT: Both tools require lead_name (customer name), NOT fund_name.
- When user asks about funds for a person, use their name as lead_name parameter.
- If the user requests return, NAV, investment, or performance summary, use fetch_fund_returns.
- If the user asks about comparison with historical data or benchmark or insights, use compare_fund_performance.
- If no customer name is mentioned, ask the user to provide the customer name.
- Do not answer questions outside the scope of fund return or comparison analysis.

===============================
🧠 Remember
===============================
- Be concise yet insightful; offer interpretation, not just raw data.
- Format numbers with commas ($50,000.00), and percentages to one decimal.
- Summarize in a way that helps the user make investment decisions.

Output formatting rules:
- If the response contains multiple funds with fields like NAV, units, invested amount, current value, returns — present as a markdown table.
- If the response is a benchmark comparison or narrative insight, output as plain text with the full detail preserved.
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
