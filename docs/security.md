# Security

Threats and the controls and tests for each. The overview is in the [README](../README.md).

| Risk | Control | Test |
|---|---|---|
| CSRF | Origin check on POST/PUT/PATCH/DELETE and WebSocket handshakes (`ALLOWED_ORIGINS`) | `tests/security` |
| XSS | Model output rendered through an `nh3` allowlist; no `<img>` (blocks data leaks); https links only; security headers | `tests/security` |
| Prompt injection | Approval gate, strict argument validation, data treated as data in the system prompt | `tests/test_graph.py`, evals |
| SSRF | Fixed base URL, validated codes, no redirects, response size limit, no URL parameters in tools | `tests/security` |
| Invented links | A link in an answer is shown only if its URL came from a tool result; others are removed (`strip_unsourced_links`) | `tests/security` |
| SQL injection | Parameterized queries only; the LLM never writes SQL | `tests/security` |
| Data leaks via web search | Redaction, domain allowlist, results marked untrusted | `tests/test_research.py` |

If you open the app from another host name (not `localhost:8080`), add it to `ALLOWED_ORIGINS` in `.env`, or the WebSocket will be refused.

Data: World Bank Open Data (CC BY 4.0).
