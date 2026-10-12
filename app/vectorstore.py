"""Semantic indicator search with Pinecone (integrated embedding: Pinecone embeds both records and queries).

Two namespaces in one index: "indicators" (`make index`, used by indicators.search) and "docs" (World Bank
methodology passages, `make index-docs`, used by app/methodology.py). Pinecone is a cloud service, so the
query text leaves the machine: it is used only when PINECONE_API_KEY is set, an upload has completed, and
privacy_mode is "demo". Any error or timeout falls
back to keyword search, so Pinecone is never a single point of failure.
"""
import hashlib
import json
import logging
import os
import time
from functools import cache

from app import config
from app.llm import REGISTRY

MODEL = "llama-text-embed-v2"
BATCH = 96  # Pinecone's per-request limit for records embedded server-side
TIMEOUT = 3  # seconds; search must stay interactive
log = logging.getLogger(__name__)


def index_name() -> str:
    return os.getenv("PINECONE_INDEX", "market-atlas-indicators")


def _marker():
    return config.data_dir() / "vector_index.json"


def record_text(indicator: dict) -> str:
    """What gets embedded: name, topics and definition."""
    topics = ", ".join(indicator.get("topics") or [])
    return f"{indicator['name']}. Topics: {topics}. {indicator.get('description', '')}".strip()


def namespace_for(kind: str, records: list[dict]) -> str:
    """Versioned by content: changed records go to a new namespace, so a half-finished upload never
    mixes with the one in use."""
    digest = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
    return f"{kind}-{digest[:10]}"


def _markers() -> dict:
    """Live namespace per kind ("indicators", "docs"), written after each finished upload."""
    try:
        markers = json.loads(_marker().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return (
        {"indicators": markers} if "namespace" in markers else markers
    )  # single-namespace format of the first version


def enabled(kind: str = "indicators") -> bool:
    return (bool(os.getenv("PINECONE_API_KEY")) and REGISTRY["privacy_mode"] == "demo"
            and kind in _markers())


@cache
def _index():
    from pinecone import Pinecone

    return Pinecone(api_key=os.environ["PINECONE_API_KEY"]).index(name=index_name())


def query(kind: str, text: str, limit: int, fields: list[str], filter: dict | None = None) -> list[dict] | None:
    """Hits as dicts (id, score and the requested fields), best first; None when disabled or failing,
    so the caller falls back."""
    if not enabled(kind):
        return None
    try:
        resp = _index().search(namespace=_markers()[kind]["namespace"], top_k=limit, inputs={"text": text[:500]},
                               filter=filter or None, fields=fields, timeout=TIMEOUT)
        return [{"id": hit.id, "score": float(hit.score), **(hit.fields or {})} for hit in resp.result.hits]
    except Exception as e:  # network, auth, quota: degrade to keyword search
        log.warning("Pinecone search failed (%s), falling back: %s", kind, e)
        return None


def search(text: str, limit: int = 10) -> list[tuple[str, float]] | None:
    """Indicator search: [(indicator code, score)], best first; None when disabled or failing."""
    hits = query("indicators", text, limit, ["name"])
    return None if hits is None else [(hit["id"], hit["score"]) for hit in hits]


def _with_retry(operation, log_fn, attempts: int = 6, sleep=time.sleep):
    """Embedding rate limits (429) and transient errors: back off 2, 4, 8… s (max 60), then give up."""
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as e:
            if attempt == attempts - 1:
                raise
            wait = min(2 ** (attempt + 1), 60)
            log_fn(f"  retry in {wait}s: {str(e)[:120]}")
            sleep(wait)


def upload(kind: str, records: list[dict], client=None, log_fn=print) -> dict:
    """Create the index if needed, upsert the records (idempotent: stable _ids) into a namespace named after
    their content, then record it as live for `kind`. Each record embeds its "text" field; the other
    fields are stored as metadata, filterable in search."""
    from pinecone import Pinecone

    pinecone_client = client or Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    name = index_name()
    if not pinecone_client.has_index(name):
        log_fn(f"Creating index {name} ({MODEL}, aws/us-east-1)…")
        pinecone_client.indexes.create_for_model(name=name, cloud="aws", region="us-east-1",
                                    embed={"model": MODEL, "field_map": {"text": "text"}})
    index = pinecone_client.index(name=name)
    namespace = namespace_for(kind, records)
    for start in range(0, len(records), BATCH):
        _with_retry(lambda: index.upsert_records(namespace=namespace, records=records[start:start + BATCH]),
                    log_fn)
        done = min(start + BATCH, len(records))
        if done == len(records) or (start // BATCH) % 10 == 0:
            log_fn(f"  {done}/{len(records)}")
    info = {"index": name, "namespace": namespace, "model": MODEL, "records": len(records)}
    _marker().write_text(json.dumps({**_markers(), kind: info}))
    return info


def build(catalog: list[dict], client=None, log_fn=print) -> dict:
    """Upload the indicator catalog (_id = indicator code)."""
    records = [
        {"_id": indicator["id"], "text": record_text(indicator), "name": indicator["name"]} for indicator in catalog
    ]
    return upload("indicators", records, client, log_fn)
