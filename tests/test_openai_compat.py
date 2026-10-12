"""OpenAI-compatible endpoint (/v1) for Open WebUI: auth, approval by reply, chart links."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app import db, openai_compat, runtime
from app.graph import build_graph
from tests.test_graph import FakeLLM


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPENAI_COMPAT_KEY", "secret")
    app = FastAPI()
    app.include_router(openai_compat.router, prefix="/v1")
    return TestClient(app)


def test_endpoint_requires_key(client, monkeypatch):
    body = {"messages": [{"role": "user", "content": "hi"}]}
    assert client.post("/v1/chat/completions", json=body).status_code == 401
    monkeypatch.delenv("OPENAI_COMPAT_KEY")
    assert client.post("/v1/chat/completions", json=body, headers={"Authorization": "Bearer x"}).status_code == 403


def test_gated_tool_waits_for_approve_reply(client, monkeypatch):
    ref = db.put_ref("scores", {"rows": []})
    save = AIMessage("", tool_calls=[{"name": "save_report", "id": "c1",
                                      "args": {"title": "T", "data_refs": [ref], "summary": "S"}}])
    llm = FakeLLM([save, AIMessage("Saved it.")])
    graph = build_graph(runtime.inproc_tools(), InMemorySaver(), llm_factory=lambda _: llm)

    async def fake_graph():
        return graph

    monkeypatch.setattr(runtime, "get_graph", fake_graph)
    headers = {"Authorization": "Bearer secret"}
    first = [{"role": "user", "content": "save a report"}]
    response = client.post("/v1/chat/completions", json={"messages": first}, headers=headers).json()
    assert "Reply **approve**" in response["choices"][0]["message"]["content"] and db.list_reports() == []
    history = first + [{"role": "assistant", "content": "..."}, {"role": "user", "content": "approve"}]
    response = client.post("/v1/chat/completions", json={"messages": history, "stream": True}, headers=headers)
    assert "Saved it." in response.text and response.text.strip().endswith("[DONE]")
    assert [report["title"] for report in db.list_reports()] == ["T"]


def test_chart_results_become_links():
    from langchain_core.messages import ToolMessage
    text = openai_compat._render([ToolMessage(content='{"chart_id": "C-0123abcd"}', tool_call_id="x")])
    assert text == "[📈 Open chart](/chart/C-0123abcd)"


def test_citation_markers_become_passage_links():
    from langchain_core.messages import ToolMessage
    passages = '{"passages": [{"cite": "[1](https://data.worldbank.org/a)"}]}'
    text = openai_compat._render([ToolMessage(content=passages, tool_call_id="x"), AIMessage(content="GDP【1】.")])
    assert text == "GDP[1](https://data.worldbank.org/a)."
