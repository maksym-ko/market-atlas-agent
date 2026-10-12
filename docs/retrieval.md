# Retrieval details

The design reasoning and eval results behind the README's [Indicator search](../README.md#indicator-search-rag-with-pinecone) and [Methodology Q&A](../README.md#methodology-qa-rag-with-citations) sections.

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
- **Citation markers:** some models cite as `【1】`, `【2†L1-L4】` or a bare `[1]` instead of copying the link. Before an answer is shown (main UI and `/v1`), `methodology.link_citations` replaces each marker with the matching passage's link from the latest `search_methodology` result. Numbers with no matching passage stay as written. The eval's citation check runs on the model's raw text, so it still measures whether the model cites by itself.
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
