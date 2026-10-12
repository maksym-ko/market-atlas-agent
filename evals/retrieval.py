"""Indicator-search eval: does the right World Bank code come back for everyday phrasing?

    uv run python -m evals.retrieval     # keyword vs. semantic (semantic needs `make index` and demo mode)

hit@1 / hit@5: share of queries with an expected code at rank 1 / in the top 5.
MRR: mean of 1/rank of the first expected code (0 when it's not in the top 5)."""
import json
from pathlib import Path
from unittest import mock

from app import indicators, methodology, vectorstore

HERE = Path(__file__).parent
CASES = [json.loads(line) for line in (HERE / "retrieval.jsonl").read_text().splitlines() if line]
DOC_CASES = [json.loads(line) for line in (HERE / "docs_retrieval.jsonl").read_text().splitlines() if line]


def score(limit: int = 5) -> dict:
    hits_at_1 = hits_at_5 = reciprocal_rank_sum = 0.0
    misses = []
    for case in CASES:
        codes = [result.get("id") for result in indicators.search(case["query"], limit)]
        rank = next((position for position, code in enumerate(codes, 1) if code in case["expected"]), None)
        hits_at_1 += rank == 1
        hits_at_5 += rank is not None
        reciprocal_rank_sum += 1 / rank if rank else 0
        if not rank:
            misses.append(case["query"])
    count = len(CASES)
    return {
        "hit@1": hits_at_1 / count,
        "hit@5": hits_at_5 / count,
        "mrr": reciprocal_rank_sum / count,
        "misses": misses,
    }


def score_docs(limit: int = 5) -> dict:
    """Methodology passages: is a passage with the expected id prefix in the top k (no filters)?"""
    hits_at_1 = hits_at_5 = reciprocal_rank_sum = 0.0
    misses = []
    for case in DOC_CASES:
        hits, _ = methodology.search(case["query"], limit)
        passage_ids = [hit.get("id") or hit.get("_id") for hit in hits]
        rank = next(
            (
                position
                for position, passage_id in enumerate(passage_ids, 1)
                if passage_id.startswith(case["expected_prefix"])
            ),
            None,
        )
        hits_at_1 += rank == 1
        hits_at_5 += rank is not None
        reciprocal_rank_sum += 1 / rank if rank else 0
        if not rank:
            misses.append(case["query"])
    count = len(DOC_CASES)
    return {
        "hit@1": hits_at_1 / count,
        "hit@5": hits_at_5 / count,
        "mrr": reciprocal_rank_sum / count,
        "misses": misses,
    }


def main():
    rows = {}
    with mock.patch.object(vectorstore, "search", lambda *args, **kwargs: None):
        rows["keyword"] = score()
    if vectorstore.enabled():
        rows["semantic (Pinecone)"] = score()
    else:
        print("Semantic skipped: needs PINECONE_API_KEY, `make index` and privacy_mode: demo\n")
    print(f"{len(CASES)} queries\n\n| Search | hit@1 | hit@5 | MRR |\n|---|---|---|---|")
    for name, result in rows.items():
        print(f"| {name} | {result['hit@1']:.0%} | {result['hit@5']:.0%} | {result['mrr']:.2f} |")
    for name, result in rows.items():
        print(f"\n{name} misses ({len(result['misses'])}): " + "; ".join(result["misses"]))

    if not methodology.docs():
        print("\nMethodology passages skipped: run `make index-docs`")
        return
    docs = {}
    with mock.patch.object(vectorstore, "query", lambda *args, **kwargs: None):
        docs["keyword"] = score_docs()
    if vectorstore.enabled("docs"):
        docs["semantic (Pinecone)"] = score_docs()
    print(f"\nMethodology passages: {len(DOC_CASES)} questions\n\n| Search | hit@1 | hit@5 | MRR |\n|---|---|---|---|")
    for name, result in docs.items():
        print(f"| {name} | {result['hit@1']:.0%} | {result['hit@5']:.0%} | {result['mrr']:.2f} |")
    for name, result in docs.items():
        print(f"\n{name} misses ({len(result['misses'])}): " + "; ".join(result["misses"]))


if __name__ == "__main__":
    main()
