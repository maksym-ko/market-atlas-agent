"""Indicator search with Pinecone and its keyword fallback, with a fake client (no network)."""
import json
from types import SimpleNamespace

import pytest

from app import indicators, vectorstore

CATALOG = [
    {"id": f"IND.{number}", "name": f"Indicator {number}", "description": "", "topics": ["Test"]}
    for number in range(200)
]


def test_semantic_hits_are_used_and_labeled(monkeypatch):
    monkeypatch.setattr(vectorstore, "search", lambda query, limit: [("AG.LND.FRST.ZS", 0.9), ("NOT.IN.CATALOG", 0.8)])
    out = indicators.search("woods", 5)  # no keyword match in the catalog
    assert out[0]["id"] == "AG.LND.FRST.ZS" and out[0]["match"] == "semantic"
    assert all(result["id"] != "NOT.IN.CATALOG" for result in out)  # only real catalog codes


def test_without_pinecone_it_is_keyword_search(monkeypatch):
    monkeypatch.setattr(vectorstore, "search", lambda query, limit: None)
    out = indicators.search("rural electricity")
    assert out[0]["id"] == "EG.ELC.ACCS.RU.ZS" and out[0]["match"] == "keyword"


@pytest.fixture
def marker(data_dir, monkeypatch):
    monkeypatch.setenv("PINECONE_API_KEY", "test")
    monkeypatch.setitem(vectorstore.REGISTRY, "privacy_mode", "demo")
    (data_dir / "vector_index.json").write_text(json.dumps({"namespace": "indicators-x"}))


def test_search_is_off_without_key_upload_or_in_strict_mode(marker, monkeypatch, data_dir):
    assert vectorstore.enabled()
    monkeypatch.setitem(vectorstore.REGISTRY, "privacy_mode", "strict")  # query text would leave the machine
    assert not vectorstore.enabled() and vectorstore.search("x") is None
    monkeypatch.setitem(vectorstore.REGISTRY, "privacy_mode", "demo")
    (data_dir / "vector_index.json").unlink()  # no completed upload
    assert not vectorstore.enabled()


def test_search_falls_back_on_errors(marker, monkeypatch):
    class Broken:
        def search(self, **kwargs):
            raise TimeoutError("pinecone down")
    monkeypatch.setattr(vectorstore, "_index", lambda: Broken())
    assert vectorstore.search("jobless rate") is None


def test_search_reads_hits(marker, monkeypatch):
    calls = {}

    class Index:
        def search(self, **kwargs):
            calls.update(kwargs)
            hits = [SimpleNamespace(id="SL.UEM.TOTL.ZS", score=0.71, fields={"name": "Unemployment"})]
            return SimpleNamespace(result=SimpleNamespace(hits=hits))
    monkeypatch.setattr(vectorstore, "_index", lambda: Index())
    assert vectorstore.search("jobless rate", 7) == [("SL.UEM.TOTL.ZS", 0.71)]
    assert calls["namespace"] == "indicators-x" and calls["top_k"] == 7 and calls["inputs"] == {"text": "jobless rate"}


class FakePinecone:
    def __init__(self, exists=False):
        self.exists, self.created, self.batches = exists, [], []
        self.indexes = SimpleNamespace(create_for_model=lambda **kwargs: self.created.append(kwargs))

    def has_index(self, name):
        return self.exists

    def index(self, name):
        return SimpleNamespace(upsert_records=lambda namespace, records: self.batches.append((namespace, records)))


def test_build_creates_index_upserts_in_batches_and_writes_marker(data_dir):
    fake_client = FakePinecone()
    info = vectorstore.build(CATALOG, client=fake_client, log_fn=lambda _: None)
    assert fake_client.created[0]["embed"]["model"] == vectorstore.MODEL
    assert [len(records) for _, records in fake_client.batches] == [96, 96, 8]
    assert {record["_id"] for _, records in fake_client.batches for record in records} == {
        item["id"] for item in CATALOG
    }  # idempotent ids
    assert json.loads((data_dir / "vector_index.json").read_text())["indicators"]["namespace"] == info["namespace"]
    vectorstore.build(CATALOG, client=FakePinecone(exists=True), log_fn=lambda _: None)  # no second create


def test_namespace_changes_only_when_the_catalog_does():
    changed = [dict(CATALOG[0], name="Renamed"), *CATALOG[1:]]
    assert vectorstore.namespace_for("x", CATALOG) == vectorstore.namespace_for("x", list(CATALOG))
    assert vectorstore.namespace_for("x", changed) != vectorstore.namespace_for("x", CATALOG)


def test_upload_retries_rate_limits_then_gives_up():
    calls, waits = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("429 Too Many Requests")
        return "ok"
    assert vectorstore._with_retry(flaky, lambda _: None, sleep=waits.append) == "ok"
    assert waits == [2, 4]

    def always_fails():
        raise RuntimeError("quota exceeded")
    with pytest.raises(RuntimeError):
        vectorstore._with_retry(always_fails, lambda _: None, attempts=3, sleep=lambda _: None)
