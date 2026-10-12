"""Upload the indicator catalog to Pinecone for semantic search (needs PINECONE_API_KEY; run `make data` first).

    uv run python -m scripts.index_indicators
"""
from app import indicators, vectorstore


def main():
    catalog = indicators._catalog()
    if not catalog:
        raise SystemExit("data/indicators.json is missing: run `make data` first")
    info = vectorstore.build(catalog)
    print(f"{info['records']} indicators → Pinecone index {info['index']}, namespace {info['namespace']}")


if __name__ == "__main__":
    main()
