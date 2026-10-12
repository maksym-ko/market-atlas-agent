"""LangSmith tracing helpers. LangChain traces automatically when LANGSMITH_TRACING=true;
this module adds privacy masking, run metadata and user feedback."""
import os
import uuid

from app.llm import REGISTRY


def configure() -> None:
    """In strict privacy mode, traces keep structure, tool names and timings but no prompt/answer text."""
    if REGISTRY["privacy_mode"] == "strict":
        os.environ["LANGSMITH_HIDE_INPUTS"] = "true"
        os.environ["LANGSMITH_HIDE_OUTPUTS"] = "true"


def enabled() -> bool:
    return os.getenv("LANGSMITH_TRACING", "").lower() == "true" and bool(os.getenv("LANGSMITH_API_KEY"))


def run_config(thread_id: str, model: str, tags: list[str] | None = None) -> tuple[dict, str]:
    """Graph config with a known root run id, so feedback can be attached to the exact answer."""
    run_id = str(uuid.uuid4())
    graph_config = {"configurable": {"thread_id": thread_id, "model": model}, "recursion_limit": 25,
           "run_id": run_id, "run_name": "market-atlas-chat", "tags": tags or ["ui"],
           "metadata": {"model": model, "thread_id": thread_id, "privacy_mode": REGISTRY["privacy_mode"]}}
    return graph_config, run_id


def send_feedback(run_id: str | None, score: int, comment: str = "") -> bool:
    if not (enabled() and run_id):
        return False
    try:
        from langsmith import Client

        Client().create_feedback(run_id, key="user_rating", score=score, comment=comment[:2000] or None)
        return True
    except Exception:  # feedback must never break the chat
        return False


configure()
