# Architecture

Where each piece lives, the agent's tools, and the HTTP endpoints. The overview is in the [README](../README.md).

## Components

| Piece | File |
|---|---|
| World Bank client: fixed base URL, validated codes, pagination, retries, disk cache | `app/wb.py` |
| Snapshot of the score indicators + indicator catalog (~1,500 WDI indicators) | `scripts/sync_data.py`, `app/snapshot.py` |
| Methodology RAG: World Bank documentation passages, Pinecone with metadata filters, cited answers | `app/methodology.py`, `scripts/index_methodology.py` |
| Full World Bank dataset in SQLite (~9M values): bulk loader, queries, benchmark | `app/warehouse.py`, `scripts/load_wdi.py`, `scripts/bench_wdi.py` |
| Deterministic metrics and score with plain-language sentences | `app/analytics.py`, `app/scoring.py` |
| Indicator search (RAG): aliases, then Pinecone semantic search, keyword fallback; retrieval eval | `app/indicators.py`, `app/vectorstore.py`, `scripts/index_indicators.py` |
| Country groups (EU27, G7, World Bank regions and income levels) | `app/groups.py` |
| 13 market tools, served over MCP and loaded by the agent with `langchain-mcp-adapters` | `app/tools.py`, `servers/market_server.py`, `app/runtime.py` |
| MCP SDK compatibility (`FastMCP` in mcp 1.x, renamed `MCPServer` in 2.x) | `servers/_mcp.py` |
| Web research (Tavily) as a second MCP server: allowlisted domains, redacted queries, untrusted results | `servers/research_server.py`, `app/redact.py` |
| ARIMA forecasts (auto order by AIC, 80/95% ranges) and the Taylor rule (HP-filter output gap) | `app/forecast.py` |
| LangGraph agent with a hard approval gate and SQLite checkpoints | `app/graph.py`, `app/runtime.py` |
| Model registry with privacy classes (`strict` / `demo`) | `models.yaml`, `app/llm.py` |
| Plotly charts built only from stored `data_ref`s | `app/charts.py` |
| NiceGUI UI: main page (map, country panel, chat with charts, 👍/👎), approval cards, report library, curator page, standalone chart page | `app/ui/` |
| JSON API and OpenAI-compatible endpoint for Open WebUI | `app/server.py`, `app/openai_compat.py` |
| LangSmith tracing (run metadata, 👍/👎 as feedback, hidden inputs/outputs in strict mode) | `app/tracing.py` |
| Learning from feedback: 👎 → proposed alias / eval case → curator approves at `/admin` | `app/feedback.py`, `app/ui/admin.py` |
| Saved reports with Markdown export rebuilt from stored data | `app/reports.py`, `app/db.py` |
| Golden evals scored from traces (tools, indicator, countries, safety, citations, number grounding) | `evals/run_evals.py` |
| Retrieval evals (hit@1, hit@5, MRR) for indicator search and methodology passages | `evals/retrieval.py` |
| Security: CSRF Origin check, security headers, XSS-safe Markdown, argument validation, parameterized SQL | `app/security.py`, `app/db.py`, `tests/security/` |

## Agent tools

| Tool | Gated | Purpose |
|---|---|---|
| `search_indicators` | | Plain language → World Bank indicator codes (semantic search) |
| `country_groups` | | "EU", "G7", a region or income level → ISO3 codes |
| `get_series` | | Values by country and year (ISO3, ISO2 or country names); returns a `data_ref` |
| `rank_countries` | | Rank by latest value, average or change, optionally within a group |
| `score_markets` | | The attractiveness score above |
| `search_methodology` | | World Bank documentation passages with citations (definitions, methodology, country notes) |
| `related_indicators` | | Which of ~1,500 indicators move with this one across countries (scans the full dataset) |
| `make_chart` | | Line or bar chart from a `data_ref` |
| `highlight_countries` | | Highlight countries on the map |
| `forecast_series` | ✅ | ARIMA forecast |
| `taylor_rule` | ✅ | Implied policy rate |
| `save_report` | ✅ | Save a report to the library |
| `list_reports` | | List saved reports |
| `research_external` | | Tavily search on official domains (research server) |

## HTTP endpoints

| Path | What |
|---|---|
| `/` | The app |
| `/admin` | Curator page (needs `ADMIN_PASSWORD`) |
| `/chart/<id>` | A single chart (used by Open WebUI replies, `app/ui/chart.py`) |
| `GET /api/scores` | All scores and ranks for the current snapshot |
| `GET /api/country/<ISO3>` | One country's score, explained signal by signal |
| `POST /api/feedback` | 👍/👎 on an answer |
| `GET /v1/models`, `POST /v1/chat/completions` | OpenAI-compatible API (Bearer `OPENAI_COMPAT_KEY`) |
