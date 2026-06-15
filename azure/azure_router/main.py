import json
import logging
import time
import uuid

from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from agent import build_agent, AGENT_DESCRIPTIONS
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

ROUTER_API_KEY = os.getenv("ROUTER_API_KEY", "wm-router-2026-secret")

agent_executor = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent_executor
    agent_executor = build_agent()
    logger.info("✅ Azure Router Agent started")
    yield

app = FastAPI(title="Azure Router Agent", version="1.0.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def verify(authorization: str | None):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    _, _, token = authorization.partition(" ")
    if token != ROUTER_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


@app.get("/")
async def root():
    return {"service": "Azure Router Agent", "version": "1.0.0"}


@app.get("/health")
async def health():
    return {"status": "ok", "agents": list(AGENT_DESCRIPTIONS.keys())}


@app.get("/v1/models")
@app.get("/models")
async def models():
    now = int(time.time())
    return {"object": "list", "data": [
        {"id": "router", "object": "model", "created": now, "owned_by": "azure-router",
         "description": "Multi-agent router — handles complex multi-step queries"}
    ] + [
        {"id": k, "object": "model", "created": now, "owned_by": "azure-router", "description": v}
        for k, v in AGENT_DESCRIPTIONS.items()
    ]}


@app.post("/v1/chat/completions")
async def chat(request: Request, authorization: str = Header(default=None)):
    verify(authorization)
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    if not messages:
        raise HTTPException(status_code=400, detail="'messages' is required")

    user_text = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")

    try:
        history = [(m["role"], m["content"]) for m in messages if m.get("role") in ("user", "assistant")]
        result = await agent_executor.ainvoke({"messages": history})
        reply = result["messages"][-1].content
    except Exception as e:
        logger.error("Agent error: %s", e)
        reply = f"❌ Error: {str(e)}"

    if stream:
        return StreamingResponse(_stream(reply), media_type="text/event-stream")

    return JSONResponse(content={
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "router",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
    })


async def _stream(text: str):
    chunk = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "router",
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}],
    }
    yield f"data: {json.dumps(chunk)}\n\n"
    yield "data: [DONE]\n\n"


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
