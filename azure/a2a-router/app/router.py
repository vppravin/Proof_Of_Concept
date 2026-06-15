import logging
import re
import httpx
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent

from app.config import (
    AGENTS, AGENT_BY_ID,
    AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_DEPLOYMENT, AZURE_OPENAI_ENDPOINT,
)

logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"@([\w-]+)", re.IGNORECASE)

llm = AzureChatOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    api_version=AZURE_OPENAI_API_VERSION,
    deployment_name=AZURE_OPENAI_DEPLOYMENT,
    temperature=0,
    streaming=True,
)


def _call_agent(agent_id: str, prompt: str) -> str:
    """Synchronously call an Azure agent /query endpoint and collect SSE response."""
    agent = AGENT_BY_ID.get(agent_id)
    if not agent:
        return f"Error: agent '{agent_id}' not found."
    url = agent.url.rstrip("/") + "/query"
    collected = []
    try:
        with httpx.Client(timeout=180) as client:
            with client.stream("POST", url, json={"query": prompt}) as resp:
                resp.raise_for_status()
                for raw_line in resp.iter_lines():
                    line = raw_line.rstrip("\r")
                    if not line.startswith("data:"):
                        continue
                    text = line[5:].strip()
                    if not text or text == "[DONE]":
                        continue
                    # skip think blocks
                    if text in ("<think>", "</think>"):
                        continue
                    collected.append(text + "\n")
    except Exception as e:
        logger.error("Error calling agent %s: %s", agent_id, e)
        return f"Error from {agent_id}: {str(e)}"
    result = "".join(collected).strip()
    logger.info("Agent %s returned %d chars", agent_id, len(result))
    return result or f"No response from {agent_id}."


# ── One LangChain tool per agent ──────────────────────────────────────────────

@tool
def get_prioritized_leads(prompt: str) -> str:
    """Fetches and prioritizes sales leads from Salesforce sorted by Annual Revenue.
    Shows lead name, source, email, and address."""
    return _call_agent("lead-agent-stream", prompt)

@tool
def task_creation(prompt: str) -> str:
    """Creates a follow-up Salesforce task for a lead.
    Requires lead name, subject, and due date."""
    return _call_agent("sfdc-task-agent", prompt)

@tool
def returns_on_fund(prompt: str) -> str:
    """Retrieves mutual fund returns, NAV, invested amount, current value,
    and benchmark comparison for a customer."""
    return _call_agent("fund-agent", prompt)

@tool
def map_assistant(prompt: str) -> str:
    """Handles all location queries: directions, nearby places, coordinates,
    reverse geocoding, and text-based place search."""
    return _call_agent("maps-agent", prompt)

@tool
def sma_activity(prompt: str) -> str:
    """Analyzes Structured Managed Account (SMA) activity for a customer.
    Covers activity type breakdown, target vs actual comparison,
    monthly trends, and investment breakdown."""
    # Extract customer name from prompt and always request full SMA data
    full_prompt = f"{prompt} — show activity type breakdown, target vs actual comparison, monthly trend analysis, and actual investment breakdown"
    return _call_agent("sma-agent", full_prompt)

@tool
def stocks_info(prompt: str) -> str:
    """Provides real-time stock prices, trend analysis, and chart generation
    for one or more stock tickers or company names."""
    return _call_agent("stocks-agent", prompt)

@tool
def sdi_activity(prompt: str) -> str:
    """Analyzes Self-Directed Investment (SDI) account activity for a customer.
    Covers activity summary, highest purchased stock, highest sold stock,
    and highest dividend stock."""
    full_prompt = f"{prompt} — show activity summary, highest purchased stock, highest sold stock, and highest dividend stock"
    return _call_agent("sdi-agent", full_prompt)

@tool
def checking_activity(prompt: str) -> str:
    """Analyzes checking account transactions for a customer.
    Covers home expenses, goal investments, money inflow, and full account summary."""
    return _call_agent("checking-agent", prompt)

@tool
def _360_view(prompt: str) -> str:
    """Generates a comprehensive 360-degree financial summary PDF for a customer
    across SDI, SMA, Checking, Savings, Managed, and Fund accounts.
    Returns a PDF URL."""
    return _call_agent("agent-360", prompt)

@tool
def lead_comparison(prompt: str) -> str:
    """Compares investment activities and top stocks between two leads.
    Shows activity-wise differences (Purchase, Sale, Dividend) side by side."""
    return _call_agent("comparison-leads-agent", prompt)

@tool
def stock_sales(prompt: str) -> str:
    """Evaluates whether a lead sold their stocks at the right time.
    Compares sale price vs current market price and shows post-sale price trend."""
    return _call_agent("sold-stocks-agent", prompt)


TOOLS = [
    get_prioritized_leads,
    task_creation,
    returns_on_fund,
    map_assistant,
    sma_activity,
    stocks_info,
    sdi_activity,
    checking_activity,
    _360_view,
    lead_comparison,
    stock_sales,
]

_INSTRUCTION = """You are a multi-agent routing assistant for a Wealth Management AI system.
Your job is to understand the user's intent, call the correct tools silently, and present results in a clean professional format.

===============================
🎯 Multi-Step Query Handling
===============================
CRITICAL: Always call tools ONE AT A TIME. After each tool call, read the result before deciding the next tool to call.
Never call multiple tools simultaneously. The output of one tool may be needed as input to the next.

Steps:
1. Identify ALL tools needed for the full request.
2. Call tools silently — NEVER narrate or announce tool calls in your response.
   FORBIDDEN phrases: "I will now call", "Fetching", "Now I will", "Let me retrieve", "Step 1", "Step 2", "Calling tool", "I will first".
3. Use tool results to inform the next tool call.
4. Repeat until all tools have been called.
5. Present ALL results together in one single structured response only after ALL tools have completed.

===============================
📋 Output Formatting Rules — STRICT
===============================
For MULTI-TOOL responses:
- Start directly with the data. Zero preamble, zero narration, zero step announcements.
- Use bold section headers: **── SECTION NAME ──**
- Separate each section with: ---
- ALL numerical data MUST be in markdown tables with proper column alignment.
- Tables must include ALL raw data rows returned by the tool — never summarize or truncate data rows.
- After each data table, add a **Key Insights** block with max 3 bullet points.
- Insights must cite specific numbers from the table directly above — no generic statements.
- For comparisons, always use a side-by-side markdown table.
- For PDF/chart URLs display as: 📄 **Report**: [View PDF](url)
- End every multi-tool response with a **── SUMMARY ──** section: 3-5 lines covering the most critical findings across all sections.
- Never repeat data already shown in a table.

For SINGLE-TOOL responses:
- Follow the individual agent's own formatting — do not reformat.

===============================
🛠 Tool Selection Rules
===============================
- sma_activity      → SMA account. When user asks for summary or full SMA data, the prompt must request: activity type breakdown, target vs actual comparison, monthly trend analysis, AND actual investment breakdown — all in one call.
- sdi_activity      → SDI account. When user asks for summary or full SDI data, the prompt must request: activity summary, highest purchased stock, highest sold stock, AND highest dividend stock — all in one call.
- stocks_info       → real-time stock prices, trends, charts (needs ticker or company name)
- lead_comparison   → compare TWO leads side by side
- returns_on_fund   → mutual fund NAV, returns, benchmark comparison
- checking_activity → checking account expenses, inflow, goal investments
- _360_view         → full 360 financial report PDF for a customer
- get_prioritized_leads → Salesforce leads list sorted by revenue
- task_creation     → create Salesforce task for a lead
- map_assistant     → directions, nearby places, location search
- stock_sales       → evaluate if a lead sold stocks at the right time

===============================
📌 Routing Rules
===============================
- Always include the customer's full name in the prompt passed to each tool.
- For sma_activity, always pass: "<Full Name> — show activity type breakdown, target vs actual comparison, monthly trend analysis, and actual investment breakdown".
- For sdi_activity, always pass: "<Full Name> — show activity summary, highest purchased stock, highest sold stock, and highest dividend stock".
- For comparison tools, pass both names clearly.
- For stocks_info, use ticker symbols or company names extracted from previous tool results or from the user query.
- Return [] only for pure greetings with no data request.
- Never call a tool without sufficient context (name, ticker, etc.)."""


def build_agent():
    return create_react_agent(llm, TOOLS, prompt=_INSTRUCTION)


def is_greeting(text: str) -> bool:
    greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "howdy", "thanks", "thank you"]
    return any(text.lower().strip().startswith(g) for g in greetings) and len(text.strip()) < 60


def get_mention_agent(last_user: str):
    """Returns (agent, cleaned_query) if @mention found, else (None, None)."""
    match = _MENTION_RE.search(last_user)
    if match:
        agent = AGENT_BY_ID.get(match.group(1).lower())
        if agent:
            cleaned = _MENTION_RE.sub("", last_user).strip()
            return agent, cleaned
    return None, None
