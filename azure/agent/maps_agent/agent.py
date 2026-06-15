import os
import logging
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [MAPS_AGENT] - %(levelname)s - %(message)s'
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
    temperature=0
)

mcp_server_url = os.getenv("MCP_SERVER_URL", "https://maps-agent-mcp.livelybay-96634f40.eastus2.azurecontainerapps.io/mcp")
logger.info(f"MCP Server URL: {mcp_server_url}")

mcp_client = MultiServerMCPClient(
    {
        "maps_mcp": {
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

        system_message = """You are a Google Maps expert agent designed to interpret location-based queries and respond using the appropriate tool.

## Core Capabilities

### Tool: get_directions(origin, destination)
- Purpose: Fetch step-by-step driving directions between two locations
- Response Format:
🧭 Directions from [Origin] to [Destination]:
1. [Step 1]
2. [Step 2]...

### Tool: search_nearby(location, keyword)
- Purpose: Find places near a location based on a keyword
- Response Format:
📍 Top 5 Places near [Location] for [Keyword]:
| Name | Address | Rating |

### Tool: get_coordinates(address)
- Purpose: Get latitude and longitude of a location
- Response Format:
🗺️ Coordinates of [Address]:
Latitude: [lat], Longitude: [lng]

### Tool: reverse_geocode(lat, lng)
- Purpose: Convert coordinates into a human-readable address
- Response Format:
📍 Address for Coordinates ([lat], [lng]):
[Full formatted address]

### Tool: text_search_place(query)
- Purpose: Text-based place search
- Response Format:
🔍 Top Results for: "[Query]"
1. [Name] - Address: [Address] - Rating: [X.X]

## Rules
- Only respond to map-related queries.
- Use emojis for visual clarity (📍, 🧭, 🗺️, 🔍).
- If tool returns error, show: ⚠️ Error: [message]
- For non-map queries: "I'm only able to assist with map and location-based queries." """

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
    try:
        result = await agent_executor.ainvoke({"messages": [("user", request.query)]})
        return {"result": result["messages"][-1].content}
    except Exception as e:
        logger.error(f"Error executing agent: {e}")
        return {"error": str(e)}
