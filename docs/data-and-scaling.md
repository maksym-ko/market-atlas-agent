# Data storage and scaling

## Where data lives

All paths are under `data/` (`MARKET_DATA_DIR`).

| What | Where | Size |
|---|---|---|
| **Full World Bank dataset** (all development indicators, all economies, 1960–2025) | `wdi.db` (SQLite, read-only), built by `make wdi` | 9,045,734 values, 212 MB |
| The 4 score indicators and the indicator catalog | `snapshot.json`, `indicators.json` | ~1.5 MB |
| World Bank API responses (when `wdi.db` doesn't have the data) | `cache/` (JSON files) | a few MB |
| Data refs, charts, reports, feedback, curator proposals, learned aliases | `app.db` (SQLite) | KBs |
| Chat state (LangGraph checkpoints) | `state.db` (SQLite) | KBs |
| Methodology passages (local copy of what's in Pinecone) | `docs.jsonl` | 10 MB |
| Which Pinecone namespaces are live (written by `make index` / `make index-docs`) | `vector_index.json` | bytes |

## The full dataset in SQLite

`make wdi` downloads the World Bank's bulk file (283 MB, wide format: one row per country × indicator, one column per year) and loads it into a long fact table:

```sql
observations(indicator_id, country_id, year, value)  PRIMARY KEY (indicator_id, country_id, year) WITHOUT ROWID
countries(id, iso3, iso2, name, region, income_level, is_aggregate)
indicators(id, code, name, topic, unit)
```

- **Load:** streamed from the zip (never fully in memory), empty cells dropped, inserted in 50k-row batches with journaling and fsync off, into a temp file that replaces `wdi.db` atomically. A failed load leaves the old database untouched. 9M rows load in ~13 s (~700k rows/s).
- **Schema:** integer keys instead of repeated text codes keep the fact table small. Its primary key `(indicator, country, year)` serves every query as a range lookup, so there are no secondary indexes to maintain. `WITHOUT ROWID` stores rows inside that key's B-tree, so lookups don't need a second read. Aggregates such as "World" or "EU" are flagged (`is_aggregate`), never mixed into country rankings.
- **Use:** `get_series` and `rank_countries` read from `wdi.db` when it has the indicator, and fall back to the live API when it doesn't. Each answer says which (`data_from`). The app opens the file read-only.
- **Analytical query:** `related_indicators` correlates one indicator with all ~1,500 others across countries in a single SQL statement (`warehouse.RELATED_SQL`): CTEs average each country over the window (`GROUP BY` over ~2M rows), self-join to pair each indicator with the target country by country, rank both sides with `RANK() OVER (PARTITION BY …)`, and aggregate the sums for Spearman's ρ. A test checks the result against pandas.

`make bench` (MacBook, M2, 16 GB; warm cache):

| Query | Access | Result rows | Median time |
|---|---|---|---|
| Series: 2 countries, 1 indicator, 20 years | primary-key range | 40 | 0.4 ms |
| All countries, 1 indicator, all years (rankings) | primary-key range | 6,224 | 10 ms |
| Related indicators: 1 vs all ~1,500, 10 years | scan + group by over 2.1M rows | 1,359 | 1.1 s (2.3 s cold) |

## When to move off SQLite

Lookups stay fast at any size here: they're primary-key ranges. The scan is the part that grows. SQLite stores rows, not columns, so a scan reads every column of every row it touches. Options, by size:

| Data size | Choice | Why |
|---|---|---|
| ~10⁷ rows (this dataset) | **SQLite** (current) | One file, no server, 1 s for a full analytical scan is fine for a chat answer |
| Up to ~10⁸–10⁹ rows, or interactive scans | **DuckDB + Parquet** | Embedded like SQLite, but column-oriented and vectorized: a scan reads only the columns it needs, in parallel. Parquet files are compressed and readable from pandas. The same SQL (CTEs, window functions) works almost unchanged. |
| 10⁹+ rows, many users, constant ingestion | **ClickHouse** | Column-oriented server built for billions of rows and real-time inserts. Worth its operating cost only at that scale. |

App records (reports, feedback, aliases) need transactions, not scans, so they don't belong in an analytical database. For many users they move to PostgreSQL, see [Production and high load](#production-and-high-load-plan-not-built).

## Production and high load (plan, not built)

Everything above runs as one process on one machine. This section is the plan for many users and much more data: what breaks first, and what replaces it.

### Where the current design breaks, in order

1. **LLM calls.** One answer takes 3–10 model calls (tool steps) and 5–80 s. Provider rate limits (like the 50/day limit on free OpenRouter models) and GPU time on a local model run out long before any database does.
2. **One process.** NiceGUI keeps each browser session's state in memory and talks over a WebSocket, so the app can't run on more than one server as it is.
3. **SQLite writes.** `app.db` and `state.db` allow one writer at a time. Every chat step writes a checkpoint, so concurrent chats queue behind each other.
4. **Analytical scans.** `related_indicators` takes ~1 s of CPU per call. That's fine for a few users, but at scale it's the query to cache or pre-aggregate.

Lookups (0.4–10 ms) and Pinecone (serverless, scales on its own) are not the bottleneck.

### Target architecture

| Part | Now | Production |
|---|---|---|
| Web app | 1 NiceGUI process | N identical instances behind a load balancer with sticky sessions (WebSockets); session data in Redis |
| Chat state (LangGraph checkpoints) | SQLite `state.db` | PostgreSQL (`langgraph-checkpoint-postgres`): concurrent writers, survives instance restarts |
| App records (reports, feedback, aliases) | SQLite `app.db` | Same PostgreSQL, so one transactional database for everything small |
| Indicator data (9M → 10⁹+ values) | SQLite `wdi.db` | **ClickHouse** (schema below). DuckDB + Parquet is the middle step up to ~10⁸–10⁹ rows if the data stays read-only. |
| Cache | JSON files in `data/cache/` | Redis: API responses and query results, keyed by query + data release, so a new release invalidates them |
| LLM calls | Called directly from the request | A worker pool with per-provider concurrency limits, retries, a fallback chain (local → cheap cloud → strong cloud), and token budgets per user |
| Data refresh | `make wdi` by hand | A scheduled job (e.g. monthly, Airflow or cron): download → validate (row counts, value ranges, schema) → load into a new table → swap |
| Vectors | Pinecone, one index | Same; namespaces already versioned per catalog/corpus |
| Monitoring | LangSmith traces | Plus metrics: p95 latency per tool, tokens per answer, cache hit rate, ingestion lag |

### ClickHouse schema for the indicator data

```sql
CREATE TABLE observations (
    indicator LowCardinality(String),  -- ~1,500 distinct values: stored as a dictionary, like the
    iso3      LowCardinality(String),  -- integer keys in SQLite, without the join
    year      UInt16,
    value     Float64,
    release   Date                     -- which World Bank release the value came from
) ENGINE = ReplacingMergeTree(release)  -- reloading a release replaces rows instead of duplicating them
ORDER BY (indicator, iso3, year);       -- same access path as the SQLite primary key
```

- **Sort key:** `ORDER BY (indicator, iso3, year)` keeps the series and ranking queries as range reads over a sparse index. Data is stored by column, so the correlation scan reads only `indicator`, `iso3`, `year` and `value`.
- **Built-in functions:** ClickHouse has `corr()` and `rankCorr()` (Spearman), so `related_indicators` loses the hand-written rank-and-sum SQL.
- **Pre-aggregation:** a materialized view keeps per-country averages by indicator and decade, so the correlation query reads ~300k pre-computed rows instead of scanning 2M raw ones.
- **Loading:** inserts in large batches (≥100k rows), never row by row, the same rule the SQLite loader follows.
- **Partitioning:** only if releases are kept side by side, `PARTITION BY release`, so an old release is dropped as one partition. At ~10⁷ rows, no partitioning.

### Before building any of this

Load-test first: Locust or k6 against `/api/scores` and the chat, measuring p95 latency and errors as concurrent users grow. The order of the list above is a prediction. The test should confirm that LLM calls saturate first, so the first production spend goes to the worker pool and caching, not the database.
