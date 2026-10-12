# Configuration

All settings live in `.env` (see `.env.example`). Everything is optional except a model key, and even that isn't needed with a local model.

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` | Model provider keys |
| `ALLOWED_ORIGINS` | Origins allowed for POST and WebSocket requests (CSRF check) |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | LangSmith tracing |
| `LANGSMITH_ENDPOINT` | LangSmith API URL, only for a non-default region or self-hosted LangSmith |
| `ADMIN_PASSWORD` | Turns on the curator page `/admin` |
| `STORAGE_SECRET` | Session cookie secret. Random on each start when empty, so sessions reset on restart |
| `OPENAI_COMPAT_KEY` | Turns on `/v1` for Open WebUI |
| `TAVILY_API_KEY` | Turns on `research_external` |
| `PRIVATE_TERMS` | Comma-separated names removed from web queries |
| `OLLAMA_BASE_URL` | Ollama server for local models (default `http://localhost:11434`) |
| `PINECONE_API_KEY`, `PINECONE_INDEX` | Semantic search for indicators (`make index`) and methodology passages (`make index-docs`); used only in `privacy_mode: demo` |
| `TOOLS_TRANSPORT` | `mcp` (default) or `inproc` |
| `HOST` | Bind address (default `127.0.0.1`; Docker uses `0.0.0.0`) |
| `MARKET_DATA_DIR` | Data directory (default `./data`) |
