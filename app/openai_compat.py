"""OpenAI-compatible endpoint so Open WebUI (or any OpenAI client) can chat with the same graph.

Auth: `Authorization: Bearer $OPENAI_COMPAT_KEY` (endpoint disabled when unset; no cookies, so no CSRF).
Charts come back as links to /chart/<id>. Gated tools pause: the reply asks the user to answer
"approve" or "reject", and the next message resumes the same thread."""
import hashlib
import hmac
import json
import os
import time
import uuid

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, Field

from app import methodology, runtime, tracing
from app.llm import DEFAULT_MODEL, enabled_models

router = APIRouter()
APPROVE_WORDS = {"approve", "approved", "yes", "ok", "go", "go ahead", "так"}


class Msg(BaseModel):
    role: str
    content: str | list = ""


class ChatRequest(BaseModel):
    model: str = DEFAULT_MODEL
    messages: list[Msg] = Field(min_length=1, max_length=200)
    stream: bool = False


def _auth(authorization: str | None):
    key = os.getenv("OPENAI_COMPAT_KEY", "")
    if not key:
        raise HTTPException(403, "OpenAI-compatible endpoint is disabled: set OPENAI_COMPAT_KEY")
    if not hmac.compare_digest((authorization or "").removeprefix("Bearer ").strip(), key):
        raise HTTPException(401, "Invalid API key")


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))


def _thread_id(request: ChatRequest) -> str:
    """Open WebUI resends the whole history; the first user message identifies the conversation."""
    first = next((_text(message.content) for message in request.messages if message.role == "user"), "")
    return "owui-" + hashlib.sha256(f"{request.model}|{first}".encode()).hexdigest()[:24]


def _render(new_messages) -> str:
    parts, passages = [], []
    for message in new_messages:
        if message.type == "tool":
            try:
                data = json.loads(_text(message.content))
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and data.get("chart_id"):
                parts.append(f"[📈 Open chart](/chart/{data['chart_id']})")
            if isinstance(data, dict) and data.get("passages"):
                passages = data["passages"]
        elif message.type == "ai" and _text(message.content).strip():
            parts.append(methodology.link_citations(_text(message.content).strip(), passages))
    return "\n\n".join(parts)


async def answer(request: ChatRequest) -> str:
    model = request.model if request.model in enabled_models() else DEFAULT_MODEL
    graph = await runtime.get_graph()
    thread = _thread_id(request)
    graph_config, _ = tracing.run_config(thread, model, tags=["openai-compat"])
    last = _text(request.messages[-1].content).strip()[:1000]
    state = await graph.aget_state(graph_config)
    before = len(state.values.get("messages", [])) if state.values else 0
    if state.interrupts:  # a gated tool is waiting for this reply
        approved = last.lower().strip(" .!") in APPROVE_WORDS
        out = await graph.ainvoke(Command(resume={"approved": approved, "reason": "chat reply"}), graph_config)
    else:
        out = await graph.ainvoke({"messages": [("user", last)]}, graph_config)
    text = _render(out["messages"][before:])
    if "__interrupt__" in out:
        pending = out["__interrupt__"][0].value["pending"]
        lines = [
            f"- **{call['tool']}** {json.dumps(call.get('args') or {'title': call.get('title')})}" for call in pending
        ]
        text += "\n\n⚠️ Approval needed:\n" + "\n".join(lines) + "\n\nReply **approve** or **reject**."
    return text or "(no answer)"


@router.get("/models")
def models(authorization: str | None = Header(None)):
    _auth(authorization)
    return {"object": "list", "data": [{"id": model_key, "object": "model", "owned_by": "market-atlas", "name": label}
                                       for model_key, label in enabled_models().items()]}


@router.post("/chat/completions")
async def chat(request: ChatRequest, authorization: str | None = Header(None)):
    _auth(authorization)
    text = await answer(request)
    completion_id, now = f"chatcmpl-{uuid.uuid4().hex[:12]}", int(time.time())
    if not request.stream:
        return {"id": completion_id, "object": "chat.completion", "created": now, "model": request.model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                             "finish_reason": "stop"}]}

    def sse():  # one content chunk, then stop: enough for Open WebUI's streaming mode
        chunk = {"id": completion_id, "object": "chat.completion.chunk", "created": now, "model": request.model,
                 "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]}
        yield f"data: {json.dumps(chunk)}\n\n"
        chunk["choices"][0] = {"index": 0, "delta": {}, "finish_reason": "stop"}
        yield f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")
