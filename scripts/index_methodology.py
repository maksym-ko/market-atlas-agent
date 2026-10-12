"""Build the methodology corpus from the WDI bulk zip and upload it to Pinecone (namespace "docs").

    uv run python -m scripts.index_methodology    # needs `make wdi` first; PINECONE_API_KEY for the upload

Without a key it still writes data/docs.jsonl, which the keyword fallback searches.
"""
import os

from app import config, methodology, vectorstore


def main():
    zip_path = config.data_dir() / "raw" / "WDI_CSV.zip"
    if not zip_path.exists():
        raise SystemExit(f"{zip_path} is missing: run `make wdi` first")
    docs = methodology.build_corpus(zip_path)
    methodology.save(docs)
    tokens = sum(len(doc["text"]) for doc in docs) // 4
    print(f"{len(docs):,} passages (~{tokens / 1e6:.1f}M tokens to embed) → {methodology.path()}")
    if not os.getenv("PINECONE_API_KEY"):
        print("No PINECONE_API_KEY: skipping the upload; chat will use keyword search over the passages")
        return
    info = vectorstore.upload("docs", docs)
    print(f"Uploaded to Pinecone index {info['index']}, namespace {info['namespace']}")


if __name__ == "__main__":
    main()
