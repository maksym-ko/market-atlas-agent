# Retrieval (RAG)

Indicator search and methodology Q&A: how they work, the eval results, and the design reasoning. The overview is in the [README](../README.md).

## Indicator search

Users say "jobless rate", the World Bank says `SL.UEM.TOTL.ZS`. Every data question starts with `search_indicators`, so its quality caps the whole agent.

1. **Aliases:** built-in ones ("inflation") and ones learned from 👎 feedback and approved by a curator. Exact and instant.
2. **Semantic search with Pinecone.** `make index` uploads the 1,498 indicators (name, topics, definition) to a Pinecone index with integrated embedding (`llama-text-embed-v2`, 1024 dimensions, cosine), so Pinecone embeds both the records and each query. "babies dying before age one" → infant mortality.
3. **Keyword search as the fallback**, used when Pinecone is off: strict privacy mode, no key, or an error.

| Concern | How it's handled |
|---|---|
| Privacy | Pinecone is a cloud service and receives the query text, so it's used only in `privacy_mode: demo`. In `strict` mode search is keyword-only. |
| Availability | 3 s timeout; any error falls back to keyword search. Pinecone is never a single point of failure. |
| Re-runs | Upserts are idempotent (`_id` = indicator code). The namespace is named after a hash of the catalog, so a changed catalog goes to a new namespace, and `data/vector_index.json` switches search over only after the upload finishes. |
| Prompt injection | Retrieved names and definitions are returned as data, like every tool result. |

### Eval results

`make eval-search`: 45 queries with the codes that count as correct (`evals/retrieval.jsonl`). 33 are everyday paraphrases ("jobless rate"), 12 are exact terms where keywords should be strong (acronyms like "PPP", "M2", "NEET", and a raw indicator code).

| Search | hit@1 | hit@5 | MRR |
|---|---|---|---|
| keyword | 38% | 60% | 0.46 |
| **semantic (Pinecone)** | **71%** | **100%** | **0.82** |

hit@1 / hit@5: share of queries with a correct code at rank 1 / in the top 5. MRR: mean of 1/rank of the first correct code. The agent sees the top 5, so hit@5 is what decides whether it can answer.

Hybrid search (keyword + semantic, fused with RRF) was tried and removed; see [below](#indicator-search-why-not-hybrid-search).

## Methodology Q&A: corpus

Numbers need context: "how is GDP per capita calculated?", "what are the limits of poverty data?", "why does Ukraine's series look different?". The `search_methodology` tool answers these from the World Bank's own documentation and cites it.

**Corpus** (`make index-docs`, built from the bulk zip that `make wdi` downloads, so nothing is scraped):

| Source file | Passages | What's in it |
|---|---|---|
| `WDISeries.csv` | 8,782 | Per indicator: definition, methodology, limitations, source, development relevance |
| `WDIcountry-series.csv` | 2,288 | What the World Bank notes about one country's series, e.g. Ukraine's national accounts "based on … official statistics of Ukraine and Russian Federation". 7,939 notes; identical notes for one country are grouped into one passage listing the indicators they apply to. |
| `WDICountry.csv` | 251 | Per country: latest census, accounting standards, special notes |


## Indicator search: why not hybrid search

The first version merged keyword and semantic rankings with reciprocal rank fusion (RRF), the usual hybrid-search design. The eval showed it made results worse at every keyword weight, even on the exact-term queries:

| Variant (hit@1 / hit@5 / MRR) | paraphrases (33) | exact terms (12) | all (45) |
|---|---|---|---|
| keyword only | 33% / 48% / 0.38 | 50% / 92% / 0.66 | 38% / 60% / 0.46 |
| semantic only | 79% / 100% / 0.87 | 50% / 100% / 0.69 | 71% / 100% / 0.82 |
| RRF, keyword weight 1.0 | 58% / 85% / 0.68 | 50% / 92% / 0.68 | 56% / 87% / 0.68 |
| RRF, keyword weight 0.5 | 70% / 88% / 0.76 | 50% / 100% / 0.71 | 64% / 91% / 0.75 |
| RRF, keyword weight 0.1 | 76% / 97% / 0.83 | 50% / 100% / 0.69 | 69% / 98% / 0.79 |

The keyword ranker is substring matching over short names, so it's noisy. Common words like "income" or "people" match dozens of indicators, and fusion lifts those above the right semantic hit. The embedding model also handles acronyms and codes well enough here. Fusion was removed. It would be worth revisiting with a proper keyword ranker (BM25), or with a reranker over the semantic top 20, measured on a larger eval set. 45 queries are enough to see a 40-point gap, not to tune weights.

## Methodology Q&A

### Pipeline

- **Chunking:** sections are split on sentence boundaries into passages of up to ~1,200 characters. Each passage is prefixed with its document title and section ("GDP per capita (current US$) (NY.GDP.PCAP.CD). Limitations: …"), so a chunk that says "this indicator" still embeds and reads as being about GDP per capita.
- **Index:** the same Pinecone index as indicator search, in its own namespace. Each passage carries metadata (`indicators` list, `country`, `section`, `url`), so the tool can filter: a question about Ukraine's GDP searches only passages tagged with both. If a filter returns nothing, the tool retries without it.
- **Generation:** the tool returns numbered passages, each with a ready-made citation (`[1](https://data.worldbank.org/…)`), marked untrusted. The system prompt makes the model answer only from them, copy citations exactly, and say so when they don't cover the question. Ready-made citations exist because in testing, the model "fixed" `/country/UA` into `/country/UKR`, a URL that wasn't in the sources. General questions about an indicator leave out country-specific notes, which otherwise pulled Russia and Ukraine notes into a question about GDP per capita.
- **Citation markers:** some models cite as `【1】`, `【2†L1-L4】` or a bare `[1]` instead of copying the link. Before an answer is shown (main UI and `/v1`), `methodology.link_citations` replaces each marker with the matching passage's link from the latest `search_methodology` result. Numbers with no matching passage stay as written. The eval's citation check runs on the answer after this step, as the user sees it; a model that cites nothing at all still fails.
- **Sources panel:** the chat shows the retrieved passages under the answer (📚 Sources), built from the tool result, not from the model's text. Provenance doesn't depend on the model following instructions: the local 8B model often answers correctly but leaves out inline citations.
- **Fallback:** the passages are also stored locally (`data/docs.jsonl`), so strict privacy mode, no key, or a Pinecone error falls back to keyword search over the same text.
- **Upload:** ~1.8M tokens of embeddings. Pinecone rate-limits tokens per minute, so the upload retries with exponential backoff instead of failing.

### Evals

- **Retrieval** (`make eval-search`, 12 questions with the passage that answers each, `evals/docs_retrieval.jsonl`, no filters):

| Search | hit@1 | hit@5 | MRR |
|---|---|---|---|
| keyword (fallback) | 17% | 33% | 0.24 |
| **semantic (Pinecone)** | **92%** | **92%** | **0.92** |

  The one miss is a near-duplicate: the World Bank's three poverty lines ($3.00, $4.20 and $8.30 a day) have almost identical methodology texts, and none of them is named "extreme". Search returns the right indicator at rank 2, but its methodology section, not its limitations. With the indicator filter, which the agent passes once `search_indicators` has given it the code, the limitations passage comes back third.

- **Chat** (`make eval`): two methodology conversations in `evals/golden.jsonl`. Besides the usual checks, a **citation check** fails a case if the answer cites any URL that didn't come from a tool result (an invented source), or cites nothing when citations are required. On the local model it caught both failure modes during development: an edited URL, and a correct answer with no citations.
