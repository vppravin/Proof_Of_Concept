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

from app.config import AGENTS, ROUTER_API_KEY
from app.router import resolve_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

http_client: httpx.AsyncClient = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
    logger.info("Router Agent started ✅ — %d agents registered", len(AGENTS))
    yield
    await http_client.aclose()

app = FastAPI(
    title="Router Agent",
    description="Smart routing layer for 11 specialist agents",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        {"id": "router", "object": "model", "created": now,
         "owned_by": "router-agent",
         "description": "Auto-routes to the best specialist agent"},
    ] + [
        {"id": a.id, "object": "model", "created": now,
         "owned_by": "router-agent", "description": a.description}
        for a in AGENTS
    ]
    return {"object": "list", "data": model_list}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, authorization: str = Header(default=None)):
    verify_api_key(authorization)

    body      = await request.json()
    messages  = body.get("messages", [])
    stream    = body.get("stream", False)

    if not messages:
        raise HTTPException(status_code=400, detail="'messages' is required")

    agent, forwarded_messages = resolve_agent(messages)

    # Handle general/conversational messages directly
    if agent is None:
        user_text = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        reply = _general_reply(user_text)
        if stream:
            return StreamingResponse(_stream_text(reply, "router"), media_type="text/event-stream")
        return JSONResponse(content=_openai_response(reply, "router"))

    logger.info("Forwarding to: %s | stream=%s", agent.id, stream)

    # Build query with conversation history for context
    user_text = next((m["content"] for m in reversed(forwarded_messages) if m.get("role") == "user"), "")
    if len(messages) > 1:
        history = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages if m.get("role") in ("user", "assistant"))
        forward_payload = {"query": f"{history}\n\nLatest question: {user_text}"}
    else:
        forward_payload = {"query": user_text}
    target_url = f"{agent.url.rstrip('/')}/query"

    if stream:
        return StreamingResponse(
            _stream_from_agent(target_url, forward_payload, agent.id),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    try:
        resp = await http_client.post(target_url, json=forward_payload)
        resp.raise_for_status()
        data = resp.json()
        result_text = data.get("result", str(data))
        return JSONResponse(content=_openai_response(result_text, agent.id))

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Agent '{agent.id}' error: {e.response.text}",
        )
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach '{agent.id}': {str(e)}")


def _general_reply(text: str) -> str:
    greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "howdy"]
    if any(text.lower().strip().startswith(g) for g in greetings):
        return "Hello! I'm your WM AI Assistant. I can help you with financial summaries, stock prices, fund performance, maps, Salesforce leads, and more. What would you like to know?"
    return "I'm your WM AI Assistant. I can help with: 360 financial reports, SMA/SDI/Checking accounts, stocks, mutual funds, maps, Salesforce leads and tasks, and lead comparisons. How can I help?"


async def _stream_text(text: str, agent_id: str):
    chunk = _sse_chunk(text, agent_id)
    yield f"data: {json.dumps(chunk)}\n\n"
    yield "data: [DONE]\n\n"


def _openai_response(text: str, agent_id: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": agent_id,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
    }


async def _stream_from_agent(url: str, payload: dict, agent_id: str):
    try:
        async with http_client.stream("POST", url, json=payload, timeout=120) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                # Pipe SSE stream directly through
                async for line in resp.aiter_lines():
                    line = line.rstrip("\r")
                    if line.startswith("data:"):
                        text = line[5:].strip()
                        if text == "[DONE]":
                            continue
                        # If agent already emits a valid OpenAI chunk, pass it through as-is
                        # so tool_calls deltas reach Open WebUI intact
                        try:
                            parsed = json.loads(text)
                            if "choices" in parsed:
                                yield f"data: {text}\n\n"
                                continue
                        except (json.JSONDecodeError, TypeError):
                            pass
                        # Plain text line — wrap it
                        chunk = _sse_chunk(text + "\n", agent_id)
                        yield f"data: {json.dumps(chunk)}\n\n"
            else:
                body = await resp.aread()
                data = json.loads(body)
                text = data.get("result", str(data))
                chunk = _sse_chunk(text, agent_id)
                yield f"data: {json.dumps(chunk)}\n\n"
    except Exception as e:
        err = _sse_chunk(f"\n\n❌ Agent '{agent_id}' error: {str(e)}", agent_id)
        yield f"data: {json.dumps(err)}\n\n"
    finally:
        yield "data: [DONE]\n\n"


def _sse_chunk(text: str, agent_id: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": agent_id,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "agents_registered": len(AGENTS), "agents": [a.id for a in AGENTS]}

@app.get("/")
async def root():
    return {"service": "Router Agent", "version": "1.0.0"}