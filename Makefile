.PHONY: data index index-docs wdi bench test ui eval eval-search docker reset ollama

data:  ## freeze World Bank data for scoring + the indicator catalog
	uv run python -m scripts.sync_data

index:  ## upload the indicator catalog to Pinecone for semantic search (needs PINECONE_API_KEY)
	uv run python -m scripts.index_indicators

index-docs:  ## World Bank methodology passages → data/docs.jsonl + Pinecone (needs `make wdi`)
	uv run python -m scripts.index_methodology

wdi:  ## full World Bank dataset (~9M values) into data/wdi.db: 283 MB download, ~15 s load
	uv run python -m scripts.load_wdi

bench:  ## query timings on data/wdi.db
	uv run python -m scripts.bench_wdi

test:
	uv run pytest -q

ui:  ## http://localhost:8080
	uv run python -m app.ui

ollama:  ## pull the local model(s) from models.yaml (needs https://ollama.com running)
	ollama pull qwen3:8b

eval:  ## golden evals on the default model (see evals/results.md)
	uv run python -m evals.run_evals

eval-search:  ## retrieval evals, indicator search + methodology passages: keyword vs. semantic (hit@1, hit@5, MRR)
	uv run python -m evals.retrieval

docker:  ## build and run the image on http://localhost:8080
	docker build -t market-atlas . && docker run --rm -p 8080:8080 --env-file .env market-atlas

reset:  ## forget chats, reports, feedback and the API cache
	rm -rf data/app.db data/state.db* data/cache
