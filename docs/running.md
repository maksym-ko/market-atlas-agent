# Running the app

Commands, models, configuration and integrations. The overview is in the [README](../README.md).

## Commands

| Command | What it does |
|---|---|
| `make data` | Freeze the score indicators (`data/snapshot.json`) and the indicator catalog (`data/indicators.json`) |
| `make index` | Upload the indicator catalog to Pinecone for semantic search (optional, needs `PINECONE_API_KEY`) |
| `make index-docs` | Build methodology passages and upload them to Pinecone (needs `make wdi`) |
| `make wdi` | Download the full World Bank dataset and load it into `data/wdi.db` (optional) |
| `make bench` | Query timings on `data/wdi.db` |
| `make test` | Run the test suite (no keys needed) |
| `make ui` | Start the web app on port 8080 (`PORT` to change it) |
| `make ollama` | Download the local model (`qwen3:8b`) |
| `make eval` | Golden evals on the default model |
| `make eval-search` | Retrieval evals for indicator search and methodology passages: keyword vs. semantic (hit@1, hit@5, MRR) |
| `make docker` | Build the image and run it with your `.env` |
| `make reset` | Forget chats, reports, feedback and the API cache |

## Models

Configured in `models.yaml` and selectable in the header:

| Key | Provider | Privacy | Notes |
|---|---|---|---|
| `nemotron-3.5-lightning` | OpenRouter (free) | `may_log` | default without an Anthropic key |
| `nemotron-3-super-120b` | OpenRouter (free) | `may_log` | the free endpoint returned 404 on 2026-10-23 |
| `gemma-4-31b` | OpenRouter (free) | `may_log` | |
| `claude-haiku-4.5` | Anthropic | `no_train` | **default** when `ANTHROPIC_API_KEY` is set |
| `local` | Ollama (`qwen3:8b`) | `local` | default without keys; runs on your machine, no limits |

Free OpenRouter models share a limit of 50 requests a day per account without credits; one golden-eval run uses about 40.

## Local models (Ollama)

No API key, no daily limits, and nothing leaves your machine, so it's also allowed in `strict` privacy mode.

1. Install [Ollama](https://ollama.com) and start it.
2. `make ollama` downloads `qwen3:8b` (~5 GB, needs ~8 GB of free RAM).
3. `make ui`. Without cloud keys it's the default model; otherwise pick it in the header.

Expect 20–80 s per question on a laptop (the first one also loads the model). `num_ctx` and `reasoning` in `models.yaml` trade speed for quality: set `reasoning: true` to let qwen3 think before answering. To try another Ollama model, add an entry with `provider: ollama` and a model that supports tool calling. Ollama on another machine or Docker on the same one: set `OLLAMA_BASE_URL`. `make docker` with the local model needs it too: put `OLLAMA_BASE_URL=http://host.docker.internal:11434` in `.env`.

If the chat says "Ollama isn't running" or "isn't downloaded yet", do step 1 or 2.

## Configuration

All settings live in `.env` (see `.env.example`). Everything is optional except a model key, and even that isn't needed with a local model. Every variable is listed in [docs/configuration.md](configuration.md).

## Forecasts

- **ARIMA forecast:** "Make an ARIMA forecast of Ukraine's GDP per capita for the next 10 years". The model order is picked by AIC on log values, and the chart shows 80% and 95% ranges.
- **Taylor rule:** `i = r* + π + 0.5·(π − π*) + 0.5·gap`, with the output gap from an HP filter on real GDP. The World Bank doesn't publish policy rates, so to compare with the actual NBU rate, add `data/policy_rates/UKR.csv` with columns `year,rate` from official NBU data. The app never invents these numbers. With `TAVILY_API_KEY` set, the agent can also look the rate up on bank.gov.ua, labeled as external and cited.

## MCP

The agent loads its tools from two MCP servers over stdio. Each server is one persistent session, owned by a single long-lived task in `app/runtime.py`. Set `TOOLS_TRANSPORT=inproc` to call the same tools as Python functions instead (tests and evals do this). Use them from Claude Desktop:

```json
{"mcpServers": {
  "market":   {"command": "uv", "args": ["--directory", "/path/to/repo", "run", "python", "-m", "servers.market_server"]},
  "research": {"command": "uv", "args": ["--directory", "/path/to/repo", "run", "python", "-m", "servers.research_server"]}
}}
```

An MCP client has no approval gate of its own, so rely on its tool-approval prompts.

## Web research

`research_external` answers facts the World Bank doesn't publish (e.g. the NBU policy rate) via Tavily. It only searches official domains: central banks, IMF, OECD, BIS and the EU. Emails, URLs, phone numbers, IDs, amounts and anything listed in `PRIVATE_TERMS` are removed before the query leaves. Results are marked untrusted and cited.

## Open WebUI

Set `OPENAI_COMPAT_KEY`, then add an OpenAI connection in Open WebUI with base URL `http://<host>:8080/v1` and that key. Charts come back as links to `/chart/<id>`. For gated tools, reply **approve** or **reject**. The map and the editable approval cards are only in the main UI.

## Docker and CI

```bash
make docker          # build + run on http://localhost:8080 with your .env
```

GitHub Actions runs the tests, `bandit`, `pip-audit` and the Docker build on every push and pull request.
