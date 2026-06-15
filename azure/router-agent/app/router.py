import json
import logging
import re

from openai import AzureOpenAI

from app.config import (
    AGENT_BY_ID, AGENTS, AgentConfig,
    AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_DEPLOYMENT, AZURE_OPENAI_ENDPOINT,
)

logger = logging.getLogger(__name__)

_openai = AzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    api_version=AZURE_OPENAI_API_VERSION,
)

_MENTION_RE = re.compile(r"@([\w-]+)", re.IGNORECASE)

_AGENT_LIST = "\n".join(
    f"- {a.id}: {a.description}" for a in AGENTS
)

_SYSTEM_PROMPT = f"""You are a routing assistant. Given a user message, return ONLY valid JSON.

If the message is a greeting, small talk, or not related to any agent below, return: {{"agent_id": "general"}}

Otherwise return the best matching agent ID from this list:
{_AGENT_LIST}

Return format: {{"agent_id": "<id>"}}
Never explain. Never add text outside the JSON."""


def resolve_agent(messages: list[dict]) -> tuple[AgentConfig, list[dict]]:
    last_user = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
    )

    # @mention — direct route, strip the mention from the message
    match = _MENTION_RE.search(last_user)
    if match:
        mention_id = match.group(1).lower()
        agent = AGENT_BY_ID.get(mention_id)
        if agent:
            cleaned = _MENTION_RE.sub("", last_user).strip()
            forwarded = [
                {**m, "content": cleaned} if m.get("role") == "user" and m["content"] == last_user else m
                for m in messages
            ]
            logger.info("@mention route → %s", agent.id)
            return agent, forwarded

    # LLM-based routing — include recent conversation context so follow-ups resolve correctly
    recent = [{"role": m["role"], "content": m["content"]} for m in messages[-6:] if m.get("role") in ("user", "assistant")]
    routing_messages = [{"role": "system", "content": _SYSTEM_PROMPT}] + recent

    try:
        resp = _openai.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=routing_messages,
            max_tokens=50,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        agent_id = json.loads(raw)["agent_id"]
        if agent_id == "general":
            logger.info("LLM route → general (conversational)")
            return None, messages
        agent = AGENT_BY_ID.get(agent_id)
        if agent:
            logger.info("LLM route → %s", agent.id)
            return agent, messages
    except Exception as e:
        logger.warning("LLM routing failed: %s — falling back to agent-360", e)

    # Fallback
    return AGENTS[0], messages
