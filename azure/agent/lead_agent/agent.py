import os
import logging
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()  # Fallback for local development

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [LEAD_AGENT] - %(levelname)s - %(message)s'
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
    deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
    temperature=0
)

# MCP Server URL
mcp_server_url = os.getenv("MCP_SERVER_URL", "https://lead-agent-mcp.livelybay-96634f40.eastus2.azurecontainerapps.io/mcp")
logger.info(f"MCP Server URL: {mcp_server_url}")

# Initialize MCP Client
mcp_client = MultiServerMCPClient(
    {
        "lead_mcp": {
            "transport": "http",
            "url": mcp_server_url
        }
    }
)

class QueryRequest(BaseModel):
    query: str

# Global variables for tools and agent
tools = None
agent_executor = None

async def initialize_agent():
    """Initialize MCP client and create agent"""
    global tools, agent_executor
    
    try:
        logger.info("Initializing MCP client and loading tools...")
        tools = await mcp_client.get_tools()
        logger.info(f"Loaded {len(tools)} tools from MCP server")
        
        system_message = """You are a lead prioritization assistant. Use the get_salesforce_leads tool to fetch sales leads.

After retrieving leads, analyze and present them according to these rules:
- Sort by Annual Revenue (highest first)
- Format revenue with commas (e.g., $1,200,000)
- Include: Name, External ID, Revenue, Source, Email, and Address
- Be concise and business-friendly"""
        
        agent_executor = create_react_agent(llm, tools, prompt=system_message)
        logger.info("✅ Agent initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize agent: {e}")
        raise

@app.on_event("startup")
async def startup_event():
    """Initialize agent on startup"""
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