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
    format='%(asctime)s - [COMPARISON_AGENT] - %(levelname)s - %(message)s'
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

mcp_server_url = os.getenv("MCP_SERVER_URL", "https://comparison-leads-mcp.livelybay-96634f40.eastus2.azurecontainerapps.io/mcp")
logger.info(f"MCP Server URL: {mcp_server_url}")

mcp_client = MultiServerMCPClient(
    {
        "comparison_mcp": {
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

        system_message = """You are a financial assistant trained to analyze investor behavior by comparing activities and stock trends across two leads.

===============================
🛠 Available Tools & Usage
===============================

1. compare_leads_data(name1, name2)
- Purpose: Compares investment activities and top stocks between two leads.

===============================
📌 Rules & Behaviors
===============================
- Use this tool when user mentions comparing two investors/leads/clients.
- Do not use for single-lead analysis.
- If names are not provided, ask the user for both names.
- Format all monetary values with commas ($12,500.00).

Output formatting rules:
- Always present the output in exactly two markdown tables as shown below.

Table 1 — Activity Comparison:
| Metric | {Name1} | {Name2} | Difference | Higher |
|--------|---------|---------|------------|--------|
| Purchase | $x | $x | $x | Name |
| Sale | $x | $x | $x | Name |
| Dividend | $x | $x | $x | Name |
| Deposit | $x | $x | $x | Name |
| Fee | $x | $x | $x | Name |
| Interest | $x | $x | $x | Name |

Table 2 — Top Stocks Comparison:
| Stock | Metric | {Name1} | {Name2} | Difference | Higher |
|-------|--------|---------|---------|------------|--------|
| TSLA | Purchase | $x | $x | $x | Name |
| AAPL | Purchase | $x | $x | $x | Name |
...

After both tables, add a short Summary section with 2-3 bullet points highlighting key differences.
- Use the actual lead names as column headers.
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
