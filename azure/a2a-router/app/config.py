import os
from dataclasses import dataclass


@dataclass
class AgentConfig:
    id: str
    name: str
    description: str
    url: str
    keywords: list


AGENTS: list[AgentConfig] = [
    AgentConfig(
        id="agent-360",
        name="360° Financial Summary Agent",
        description=(
            "Generates a comprehensive 360-degree financial summary PDF for a customer. "
            "Queries SDI, SMA, Checking, Savings, Managed, and Funds account tables. "
            "Returns a PDF URL with AI-generated insights per section."
        ),
        url=os.getenv("AGENT_360_URL", "https://agent-360.livelybay-96634f40.eastus2.azurecontainerapps.io"),
        keywords=["360", "summary", "pdf", "financial report", "full report", "overview", "all accounts"],
    ),
    AgentConfig(
        id="comparison-leads-agent",
        name="Lead Comparison Agent",
        description=(
            "Compares investment activities and top stocks between two sales leads. "
            "Shows activity-wise differences (Purchase, Sale, Dividend) and top stock comparison side by side."
        ),
        url=os.getenv("COMPARISON_LEADS_AGENT_URL", "https://comparison-leads-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
        keywords=["compare", "comparison", "two leads", "vs", "versus", "difference between"],
    ),
    AgentConfig(
        id="fund-agent",
        name="Mutual Fund Agent",
        description=(
            "Analyzes mutual fund performance for a customer. "
            "Fetches NAV, units, invested amount, current value, and returns. "
            "Compares performance against historical benchmarks."
        ),
        url=os.getenv("FUND_AGENT_URL", "https://fund-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
        keywords=["fund", "mutual fund", "NAV", "units", "returns", "benchmark", "invested"],
    ),
    AgentConfig(
        id="lead-agent-stream",
        name="Salesforce Leads Stream Agent",
        description=(
            "Fetches and prioritizes sales leads from Salesforce with streaming response. "
            "Sorts by Annual Revenue, shows lead name, ID, source, email, and address."
        ),
        url=os.getenv("LEAD_AGENT_STREAM_URL", "https://lead-agent-stream.livelybay-96634f40.eastus2.azurecontainerapps.io"),
        keywords=["leads", "salesforce", "sales lead", "lead list", "priority leads", "revenue"],
    ),
    AgentConfig(
        id="maps-agent",
        name="Maps & Location Agent",
        description=(
            "Google Maps expert for all location-based queries. "
            "Handles directions, nearby places search, coordinates lookup, reverse geocoding, and text-based place search."
        ),
        url=os.getenv("MAPS_AGENT_URL", "https://maps-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
        keywords=["map", "location", "directions", "nearby", "address", "geocode", "place", "navigate", "route"],
    ),
    AgentConfig(
        id="sdi-agent",
        name="SDI Account Agent",
        description=(
            "Analyzes Self-Directed Investment (SDI) account activity for a customer. "
            "Provides activity summary and identifies highest purchased, sold, and dividend stocks."
        ),
        url=os.getenv("SDI_AGENT_URL", "https://sdi-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
        keywords=["SDI", "self-directed", "self directed investment", "sdi account"],
    ),
    AgentConfig(
        id="sma-agent",
        name="SMA Account Agent",
        description=(
            "Analyzes Structured Managed Account (SMA) activity. "
            "Provides activity type breakdown, target vs actual comparison, monthly trends, and investment breakdown."
        ),
        url=os.getenv("SMA_AGENT_URL", "https://sma-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
        keywords=["SMA", "structured managed", "managed account", "target vs actual", "monthly trend"],
    ),
    AgentConfig(
        id="sold-stocks-agent",
        name="Sold Stocks Analysis Agent",
        description=(
            "Evaluates whether a lead sold their stocks at the right time. "
            "Compares sale price vs current market price and shows post-sale price trend."
        ),
        url=os.getenv("SOLD_STOCKS_AGENT_URL", "https://sold-stocks-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
        keywords=["sold stocks", "sell timing", "right time", "post sale", "stock sale analysis"],
    ),
    AgentConfig(
        id="stocks-agent",
        name="Stocks & Market Data Agent",
        description=(
            "Provides real-time stock prices, trends, and chart generation. "
            "Uses Finnhub and Alpha Vantage APIs. Generates and stores charts in Azure Blob."
        ),
        url=os.getenv("STOCKS_AGENT_URL", "https://stocks-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
        keywords=["stock price", "stock trend", "chart", "real-time", "market", "ticker", "finnhub"],
    ),
    AgentConfig(
        id="checking-agent",
        name="Checking Account Agent",
        description=(
            "Analyzes customer checking account transactions. "
            "Provides home expenses, goal investments, money inflow, and complete account summary."
        ),
        url=os.getenv("CHECKING_AGENT_URL", "https://checking-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
        keywords=["checking", "checking account", "transactions", "expenses", "deposits", "inflow", "goal"],
    ),
    AgentConfig(
        id="sfdc-task-agent",
        name="Salesforce Task Agent",
        description=(
            "Automates Salesforce task creation for leads. "
            "Takes lead name, subject, and due date. Converts IST to UTC, validates lead, returns task ID."
        ),
        url=os.getenv("SFDC_TASK_AGENT_URL", "https://sfdc-task-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"),
        keywords=["task", "create task", "salesforce task", "follow up", "due date", "sfdc"],
    ),
]


AGENT_BY_ID: dict[str, AgentConfig] = {a.id: a for a in AGENTS}

# Azure OpenAI
AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT", "wm-gpt4o")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

# Router Auth
ROUTER_API_KEY = os.getenv("ROUTER_API_KEY", "change-me-in-production")
