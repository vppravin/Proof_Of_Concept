import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.config import AGENTS, AGENT_BY_ID, ROUTER_API_KEY
from app.router import build_agent, is_greeting, get_mention_agent, _call_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

http_client: httpx.AsyncClient = None
orchestrator = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client, orchestrator
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0))
    orchestrator = build_agent()
    logger.info("A2A Router started — %d agents registered", len(AGENTS))
    yield
    await http_client.aclose()


app = FastAPI(title="A2A Router Agent", version="3.0.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def verify_api_key(authorization: str | None):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != ROUTER_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


@app.get("/v1/models")
@app.get("/models")
async def list_models(authorization: str = Header(default=None)):
    verify_api_key(authorization)
    now = int(time.time())
    model_list = [
        {"id": "a2a-router", "object": "model", "created": now, "owned_by": "a2a-router",
         "description": "Multi-agent orchestration — routes to multiple specialist agents"},
    ] + [
        {"id": a.id, "object": "model", "created": now, "owned_by": "a2a-router", "description": a.description}
        for a in AGENTS
    ]
    return {"object": "list", "data": model_list}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, authorization: str = Header(default=None)):
    verify_api_key(authorization)
    body     = await request.json()
    messages = body.get("messages", [])
    stream   = body.get("stream", False)

    if not messages:
        raise HTTPException(status_code=400, detail="'messages' is required")

    last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")

    # Build conversation history for context (last 10 messages)
    history = [
        (m["role"] if m["role"] in ("user", "assistant") else "user", m["content"])
        for m in messages[-10:]
        if m.get("content")
    ]

    # Pure greeting — reply directly
    if is_greeting(last_user):
        reply = _general_reply(last_user)
        if stream:
            return StreamingResponse(_stream_text(reply), media_type="text/event-stream")
        return JSONResponse(content=_openai_response(reply))

    # @mention — bypass orchestrator, call agent directly
    agent, cleaned_query = get_mention_agent(last_user)
    if agent:
        logger.info("@mention route → %s", agent.id)
        if stream:
            return StreamingResponse(
                _stream_direct(agent, cleaned_query),
                media_type="text/event-stream",
                headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
            )
        result = _call_agent(agent.id, cleaned_query)
        return JSONResponse(content=_openai_response(result))

    # Orchestrator — LLM decides which tools to call
    logger.info("Orchestrator handling: %s", last_user[:80])
    if stream:
        return StreamingResponse(
            _orchestrate_stream(history),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    # Non-stream — collect full orchestrator response
    collected = []
    async for event in orchestrator.astream_events(
        {"messages": history}, version="v2"
    ):
        if event["event"] == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if content:
                collected.append(content)
    return JSONResponse(content=_openai_response("".join(collected).strip()))


async def _orchestrate_stream(history: list):
    """Stream orchestrator output — all tool calls inside one collapsed think block."""
    line_buffer = ""
    think_open = False
    tool_call_count = 0
    try:
        async for event in orchestrator.astream_events(
            {"messages": history}, version="v2"
        ):
            kind = event["event"]

            if kind == "on_tool_start":
                tool_name = event["name"]
                tool_input = event["data"].get("input", {}).get("prompt", "")
                logger.info("Orchestrator calling tool: %s", tool_name)
                tool_call_count += 1
                if not think_open:
                    yield f"data: {json.dumps(_chunk('<think>'))}\n\n"
                    think_open = True
                header = f'### Tool Call {tool_call_count}: {tool_name}\n'
                yield f"data: {json.dumps(_chunk(header))}\n\n"
                if tool_input:
                    input_line = f'**Input:** {tool_input}\n'
                    yield f"data: {json.dumps(_chunk(input_line))}\n\n"

            elif kind == "on_tool_end":
                tool_output = event["data"].get("output", "")
                if tool_output and think_open:
                    preview = str(tool_output)[:600].replace("\n", " ")
                    result_line = f'**Result preview:** {preview}...\n\n---\n'
                    yield f"data: {json.dumps(_chunk(result_line))}\n\n"

            elif kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if not content:
                    continue
                if think_open:
                    yield f"data: {json.dumps(_chunk('</think>'))}\n\n"
                    think_open = False
                line_buffer += content
                while "\n" in line_buffer:
                    line, line_buffer = line_buffer.split("\n", 1)
                    yield f"data: {json.dumps(_chunk(line + chr(10)))}\n\n"

        if think_open:
            yield f"data: {json.dumps(_chunk('</think>'))}\n\n"
        if line_buffer.strip():
            yield f"data: {json.dumps(_chunk(line_buffer))}\n\n"

    except Exception as e:
        logger.error("Orchestrator error: %s", e)
        if think_open:
            yield f"data: {json.dumps(_chunk('</think>'))}\n\n"
        yield f"data: {json.dumps(_chunk(f'Error: {str(e)}'))}\n\n"

    yield "data: [DONE]\n\n"


async def _stream_direct(agent, query: str):
    """For @mention — stream directly from a single agent's SSE endpoint."""
    url = agent.url.rstrip("/") + "/query"
    try:
        async with http_client.stream("POST", url, json={"query": query}, timeout=180) as resp:
            resp.raise_for_status()
            async for raw_line in resp.aiter_lines():
                line = raw_line.rstrip("\r")
                if not line.startswith("data:"):
                    continue
                text = line[5:].strip()
                if not text or text == "[DONE]":
                    continue
                if text in ("<think>", "</think>"):
                    continue
                try:
                    parsed = json.loads(text)
                    if "choices" in parsed:
                        yield f"data: {text}\n\n"
                        continue
                except (json.JSONDecodeError, TypeError):
                    pass
                yield f"data: {json.dumps(_chunk(text + chr(10)))}\n\n"
    except Exception as e:
        yield f"data: {json.dumps(_chunk(f'❌ Error: {str(e)}'))}\n\n"
    yield "data: [DONE]\n\n"


def _general_reply(text: str) -> str:
    greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "howdy"]
    if any(text.lower().strip().startswith(g) for g in greetings):
        return "Hello! I'm your WM A2A Assistant. I can orchestrate multiple specialist agents. Ask me anything!"
    return "I'm your WM A2A Assistant. Try asking about multiple accounts or leads in one query!"


async def _stream_text(text: str):
    yield f"data: {json.dumps(_chunk(text))}\n\n"
    yield "data: [DONE]\n\n"


def _openai_response(text: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "a2a-router",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
    }


def _chunk(text: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "a2a-router",
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "mode": "llm-orchestrated", "agents_registered": len(AGENTS)}


@app.get("/")
async def root():
    return {"service": "A2A Router Agent", "version": "3.0.0"}
