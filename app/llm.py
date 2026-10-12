import os
from functools import cache

import yaml
from langchain.chat_models import init_chat_model

from app.config import ROOT

REGISTRY = yaml.safe_load((ROOT / "models.yaml").read_text())
DEFAULT_MODEL = REGISTRY["default"]
ALLOWED = {"strict": {"zdr", "no_log_no_train", "local"},
           "demo": {"zdr", "no_log_no_train", "local", "no_train", "may_log"}}


def enabled_models(privacy_mode: str | None = None) -> dict[str, str]:
    allowed = ALLOWED[privacy_mode or REGISTRY["privacy_mode"]]
    return {model_key: model["label"] for model_key, model in REGISTRY["models"].items()
            if model.get("enabled", True) and model["privacy"] in allowed}


@cache
def get_llm(model_key: str | None = None):
    model_key = model_key or DEFAULT_MODEL
    if model_key not in enabled_models():
        raise ValueError(f"Model {model_key!r} is not allowed (disabled or blocked by privacy_mode)")
    model = REGISTRY["models"][model_key]
    common = {"temperature": 0, "max_retries": 2, "timeout": 60}
    match model["provider"]:
        case "anthropic":
            return init_chat_model(model["model"], model_provider="anthropic", **common)
        case "openrouter":
            return init_chat_model(model["model"], model_provider="openai", base_url="https://openrouter.ai/api/v1",
                                   api_key=os.environ["OPENROUTER_API_KEY"], **common)
        case "ollama":  # local: no API key, nothing leaves the machine
            from langchain_ollama import ChatOllama

            return ChatOllama(
                model=model["model"],
                base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
                temperature=0,
                num_ctx=model.get("num_ctx", 16384),
                reasoning=model.get("reasoning", False),
                keep_alive="30m",
                client_kwargs={"timeout": 300},
            )
    raise ValueError(f"Unknown provider {model['provider']!r}")


def explain_error(error: Exception, model_key: str | None = None) -> str:
    """Plain-language message for common model errors; falls back to the raw error."""
    model = REGISTRY["models"].get(model_key or DEFAULT_MODEL, {})
    text = f"{type(error).__name__}: {error}"
    if model.get("provider") == "ollama":
        if "connect" in text.lower():
            return "Ollama isn't running. Start the Ollama app (or `ollama serve`) and try again."
        if "not found" in text.lower():
            return f"The local model `{model['model']}` isn't downloaded yet. Run `make ollama` and try again."
    if "429" in text or "RateLimit" in text:
        return ("The model's rate limit is reached (free OpenRouter models allow 50 requests a day without "
                "credits). Pick another model in the header, for example the local one.")
    return f"Something went wrong: `{text[:300]}`"
