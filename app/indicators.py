"""Find World Bank indicator codes from plain language: aliases first, then semantic search with
Pinecone (app/vectorstore.py), or keyword search when Pinecone is off (strict privacy mode, no key, errors).

Keyword + semantic fusion was measured and dropped: on evals/retrieval.jsonl semantic search alone found
the right code in the top 5 for 45/45 queries, and every keyword weight made fusion worse (see README)."""
import json
import re
from functools import lru_cache
from pathlib import Path

from app import config, db, vectorstore

ALIASES = {
    "inflation": "FP.CPI.TOTL.ZG",
    "gdp growth": "NY.GDP.MKTP.KD.ZG",
    "gdp per capita": "NY.GDP.PCAP.CD",
    "gdp": "NY.GDP.MKTP.CD",
    "population": "SP.POP.TOTL",
    "population growth": "SP.POP.GROW",
    "internet users": "IT.NET.USER.ZS",
    "access to electricity": "EG.ELC.ACCS.ZS",
    "forest area": "AG.LND.FRST.ZS",
    "unemployment": "SL.UEM.TOTL.ZS",
}
STOP = {"the", "and", "for", "of", "in", "to", "a", "an", "by", "with", "on", "rate", "share", "percent", "%"}


def _catalog() -> list[dict]:
    path = config.data_dir() / "indicators.json"
    return _load(str(path), path.stat().st_mtime_ns) if path.exists() else []


@lru_cache(maxsize=4)
def _load(path: str, mtime_ns: int) -> list[dict]:
    return json.loads(Path(path).read_text())


def keyword_ranking(query: str, limit: int) -> list[str]:
    terms = [term for term in re.findall(r"[a-z0-9]+", query.lower()) if term not in STOP and len(term) > 1]
    scored = []
    for indicator in _catalog():
        name = indicator["name"].lower()
        score = sum(3 for term in terms if term in name) + sum(
            1 for term in terms if term in indicator["description"].lower()
        )
        if score:
            scored.append((score, -len(name), indicator["id"]))
    scored.sort(key=lambda entry: (-entry[0], -entry[1]))
    return [code for _, _, code in scored[:limit]]


def search(query: str, limit: int = 5) -> list[dict]:
    normalized = query.lower().strip()
    by_id = {indicator["id"]: indicator for indicator in _catalog()}
    results, seen = [], set()
    learned = db.aliases()  # approved from user feedback; checked first
    for alias, code in [*sorted(learned.items(), key=lambda alias_and_code: -len(alias_and_code[0])), *ALIASES.items()]:
        if alias in normalized and code not in seen:
            seen.add(code)
            item = by_id.get(code, {"id": code, "name": alias})
            results.append({"id": code, "name": item["name"],
                            "match": "learned alias" if alias in learned else "alias"})
    semantic = vectorstore.search(query, limit * 2)
    if semantic is not None:
        ranking, match_type = [code for code, _ in semantic if code in by_id], "semantic"
    else:  # strict privacy mode, no Pinecone, or an error
        ranking, match_type = keyword_ranking(normalized, limit * 2), "keyword"
    for code in ranking:
        if len(results) >= limit:
            break
        if code not in seen:
            indicator_info = by_id[code]
            results.append(
                {
                    "id": code,
                    "name": indicator_info["name"],
                    "description": indicator_info["description"][:200],
                    "match": match_type,
                }
            )
    return results[:limit] or [{"note": "No match. Try other words, or give the indicator code."}]
