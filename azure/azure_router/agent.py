import os
import httpx
import logging
from langchain_openai import AzureChatOpenAI
from langchain.tools import tool
from langgraph.prebuilt import create_react_agent

logger = logging.getLogger(__name__)

AGENT_URLS = {
    "agent-360":               os.getenv("AGENT_360_URL",               "https://agent-360.livelybay-96634f40.eastus2.azurecontainerapps.io"),
    "comparison-leads-agent":  os.getenv("COMPARISON_LEADS_AGENT_URL",  "https://comparison-leads-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
    "fund-agent":              os.getenv("FUND_AGENT_URL",              "https://fund-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
    "lead-agent":              os.getenv("LEAD_AGENT_URL",              "https://lead-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
    "maps-agent":              os.getenv("MAPS_AGENT_URL",              "https://maps-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
    "sdi-agent":               os.getenv("SDI_AGENT_URL",               "https://sdi-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
    "sma-agent":               os.getenv("SMA_AGENT_URL",               "https://sma-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
    "sold-stocks-agent":       os.getenv("SOLD_STOCKS_AGENT_URL",       "https://sold-stocks-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
    "stocks-agent":            os.getenv("STOCKS_AGENT_URL",            "https://stocks-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
    "checking-agent":          os.getenv("CHECKING_AGENT_URL",          "https://checking-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
    "sfdc-task-agent":         os.getenv("SFDC_TASK_AGENT_URL",         "https://sfdc-task-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
}

AGENT_DESCRIPTIONS = {
    "agent-360":              "Generates comprehensive 360° financial summary PDF for a customer across SDI, SMA, Checking, Savings, Managed, and Funds.",
    "comparison-leads-agent": "Compares investment activities and top stocks between two leads side by side.",
    "fund-agent":             "Analyzes mutual fund performance — NAV, returns, benchmark comparison.",
    "lead-agent":             "Fetches and prioritizes sales leads from Salesforce by revenue.",
    "maps-agent":             "Handles all location queries — directions, nearby places, coordinates, geocoding.",
    "sdi-agent":              "Analyzes SDI account — activity summary, highest purchased/sold/dividend stocks.",
    "sma-agent":              "Analyzes SMA account — activity breakdown, target vs actual, monthly trends.",
    "sold-stocks-agent":      "Evaluates if a lead sold stocks at the right time vs current market price.",
    "stocks-agent":           "Real-time stock prices, trends, and chart generation via Finnhub/Alpha Vantage.",
    "checking-agent":         "Analyzes checking account — home expenses, goal investments, money inflow.",
    "sfdc-task-agent":        "Creates Salesforce follow-up tasks for leads with due date and subject.",
}


MAX_TOOL_RESPONSE = 4000

def _call_agent(agent_id: str, prompt: str) -> str:
    url = f"{AGENT_URLS[agent_id].rstrip('/')}/query"
    try:
        resp = httpx.post(url, json={"query": prompt}, timeout=120)
        resp.raise_for_status()
        result = resp.json().get("result", str(resp.json()))
        if len(result) > MAX_TOOL_RESPONSE:
            result = result[:MAX_TOOL_RESPONSE] + "\n...[truncated]"
        return result
    except Exception as e:
        return f"❌ Error calling {agent_id}: {str(e)}"


@tool
def agent_360(prompt: str) -> str:
    """Generates a comprehensive 360° financial summary PDF for a customer. Use when asked for full financial overview, 360 view, or complete report."""
    return _call_agent("agent-360", prompt)

@tool
def comparison_leads(prompt: str) -> str:
    """Compares investment activities and top stocks between two leads. Use when asked to compare two people."""
    return _call_agent("comparison-leads-agent", prompt)

@tool
def fund_performance(prompt: str) -> str:
    """Analyzes mutual fund performance — NAV, returns, benchmark. Use for fund/NAV/investment return queries."""
    return _call_agent("fund-agent", prompt)

@tool
def salesforce_leads(prompt: str) -> str:
    """Fetches and prioritizes sales leads from Salesforce. Use for lead list or prioritization queries."""
    return _call_agent("lead-agent", prompt)

@tool
def maps_location(prompt: str) -> str:
    """Handles location queries — directions, nearby places, coordinates. Use for any map/location/navigation query."""
    return _call_agent("maps-agent", prompt)

@tool
def sdi_account(prompt: str) -> str:
    """Analyzes SDI account activity — summary, highest purchased/sold/dividend stocks."""
    return _call_agent("sdi-agent", prompt)

@tool
def sma_account(prompt: str) -> str:
    """Analyzes SMA account — activity breakdown, target vs actual ($500K), monthly trends."""
    return _call_agent("sma-agent", prompt)

@tool
def sold_stocks(prompt: str) -> str:
    """Evaluates if a lead sold stocks at the right time by comparing sale price vs current market."""
    return _call_agent("sold-stocks-agent", prompt)

@tool
def stock_market(prompt: str) -> str:
    """Gets real-time stock prices, trends, and generates charts. Use for stock price/trend/chart queries."""
    return _call_agent("stocks-agent", prompt)

@tool
def checking_account(prompt: str) -> str:
    """Analyzes checking account — home expenses, goal investments, money inflow."""
    return _call_agent("checking-agent", prompt)

@tool
def sfdc_task(prompt: str) -> str:
    """Creates Salesforce follow-up tasks for leads. Use when asked to create a task or follow-up."""
    return _call_agent("sfdc-task-agent", prompt)


TOOLS = [
    agent_360, comparison_leads, fund_performance, salesforce_leads,
    maps_location, sdi_account, sma_account, sold_stocks,
    stock_market, checking_account, sfdc_task,
]

SYSTEM_PROMPT = """You are a Wealth Management AI Assistant with access to 11 specialist tools.

For EVERY user request:
1. Identify ALL tools needed to fully answer the request
2. Call each tool with a clear, specific prompt including any names/parameters mentioned
3. Aggregate all results into a single well-formatted response

For multi-step requests (using words like "and", "also", "then", "compare"):
- Execute ALL required tools, not just the first one
- Present results in clearly labeled sections with emojis

For greetings or general questions, respond directly without calling any tool.

Always include the customer name when calling financial tools."""


def build_agent():
    llm = AzureChatOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version="2024-02-15-preview",
        deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT", "wm-gpt4o"),
        temperature=0,
    )
    return create_react_agent(llm, TOOLS, prompt=SYSTEM_PROMPT)
