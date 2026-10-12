"""Model registry, plain-language model errors, and LangSmith tracing helpers."""
from app import tracing


def test_model_errors_are_explained_in_plain_words():
    from app.llm import enabled_models, explain_error

    assert "local" in enabled_models("strict")  # a local model works even in strict privacy mode
    assert "Ollama isn't running" in explain_error(ConnectionError("Failed to connect to Ollama"), "local")
    assert "make ollama" in explain_error(Exception("model 'qwen3:8b' not found"), "local")
    assert "rate limit" in explain_error(Exception("Error code: 429 - free-models-per-day"), "gemma-4-31b")
    assert explain_error(ValueError("boom"), "gemma-4-31b").startswith("Something went wrong")


def test_tracing_is_a_no_op_without_langsmith(monkeypatch):
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    graph_config, run_id = tracing.run_config("t", "m")
    assert graph_config["run_id"] == run_id and graph_config["metadata"]["model"] == "m"
    assert tracing.send_feedback(run_id, 1) is False
