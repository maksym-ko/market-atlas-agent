"""Methodology RAG: corpus from a tiny WDI-shaped zip, chunking, filters, keyword fallback, tool output."""
import csv
import io
import zipfile

import pytest

from app import methodology, tools, vectorstore


def _csv(rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


@pytest.fixture
def corpus(data_dir, monkeypatch):
    monkeypatch.setattr(vectorstore, "query", lambda *args, **kwargs: None)  # keyword path unless a test says otherwise
    series = [
        {"Series Code": "NY.GDP.PCAP.CD", "Indicator Name": "GDP per capita (current US$)",
         "Long definition": "GDP per capita is gross domestic product divided by midyear population.",
         "Statistical concept and methodology": ("Data are converted at official exchange rates. " * 60).strip(),
         "Limitations and exceptions": "Informal activity is often missed.", "Source": "World Bank national accounts.",
         "Development relevance": ""},
        {"Series Code": "SP.POP.TOTL", "Indicator Name": "Population, total",
         "Long definition": "Total population counts all residents regardless of legal status.",
         "Statistical concept and methodology": "Based on censuses.", "Limitations and exceptions": "",
         "Source": "UN World Population Prospects.", "Development relevance": ""},
    ]
    countries = [
        {"Country Code": "UKR", "2-alpha code": "UA", "Table Name": "Ukraine", "Region": "Europe & Central Asia",
         "Special Notes": "", "Latest population census": "2001"},
        {"Country Code": "WLD", "2-alpha code": "1W", "Table Name": "World", "Region": "", "Special Notes": "",
         "Latest population census": ""},
    ]
    note = "Data exclude temporarily occupied territories."
    country_series = [{"CountryCode": "UKR", "SeriesCode": code, "DESCRIPTION": note}
                      for code in ("NY.GDP.PCAP.CD", "SP.POP.TOTL")]
    zip_path = data_dir / "WDI_CSV.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("WDISeries.csv", _csv(series))
        archive.writestr("WDICountry.csv", _csv(countries))
        archive.writestr("WDIcountry-series.csv", _csv(country_series))
    docs = methodology.build_corpus(zip_path)
    methodology.save(docs)
    return docs


def test_split_keeps_sentences_whole():
    chunks = methodology.split("One. " * 400, size=100)
    assert all(len(chunk) <= 100 for chunk in chunks) and all(chunk.endswith(".") for chunk in chunks)
    assert methodology.split("") == [] and methodology.split("Short.") == ["Short."]


def test_corpus_titles_chunks_and_groups(corpus):
    doc_ids = {doc["_id"] for doc in corpus}
    assert len(doc_ids) == len(corpus)
    method = [doc for doc in corpus if doc["_id"].startswith("ind:NY.GDP.PCAP.CD:met")]
    assert len(method) > 1  # the long methodology was split
    assert all(doc["text"].startswith("GDP per capita (current US$) (NY.GDP.PCAP.CD). Methodology:") for doc in method)
    assert not any(doc["_id"].startswith("ind:NY.GDP.PCAP.CD:dev") for doc in corpus)  # empty section skipped
    assert not any(doc["country"] == "WLD" for doc in corpus)  # aggregates get no profile
    notes = [doc for doc in corpus if doc["_id"].startswith("note:")]
    assert len(notes) == 1 and set(notes[0]["indicators"]) == {"NY.GDP.PCAP.CD", "SP.POP.TOTL"}  # grouped
    assert notes[0]["url"] == "https://data.worldbank.org/country/UA"


def test_keyword_fallback_respects_filters(corpus):
    hits, match_type = methodology.search("occupied territories", 5, indicator="SP.POP.TOTL", country="UKR")
    assert match_type == "keyword" and hits[0]["_id"].startswith("note:UKR")
    hits, _ = methodology.search("occupied territories", 5, country="POL")
    assert hits == []


def test_semantic_search_sends_metadata_filters(corpus, monkeypatch):
    seen = {}

    def fake_query(kind, text, limit, fields, metadata_filter):
        seen.update(kind=kind, metadata_filter=metadata_filter, fields=fields)
        return [{"id": "x", "score": 0.5, "title": "T", "section": "S", "url": "https://u", "text": "body"}]
    monkeypatch.setattr(vectorstore, "query", fake_query)
    hits, match_type = methodology.search("how is it measured", 3, indicator="SP.POP.TOTL", country="UKR")
    assert match_type == "semantic" and seen["kind"] == "docs" and "text" in seen["fields"]
    assert seen["metadata_filter"] == {"indicators": {"$in": ["SP.POP.TOTL"]}, "country": {"$eq": "UKR"}}
    methodology.search("how is it measured", 3, indicator="SP.POP.TOTL")
    assert seen["metadata_filter"] == {"indicators": {"$in": ["SP.POP.TOTL"]}, "country": {"$eq": ""}}


def test_tool_returns_numbered_citations_and_retries_without_filters(corpus):
    out = tools.search_methodology("How is GDP per capita calculated?", indicator="NY.GDP.PCAP.CD")
    assert out["passages"][0]["cite"].startswith("[1](https://data.worldbank.org/") and out["untrusted"] is True
    assert not any(
        passage["title"].startswith("Ukraine") for passage in out["passages"]
    )  # no country asked: no country notes
    # the filter finds nothing for AAA (a test country), so the tool retries unfiltered
    out = tools.search_methodology("occupied territories", country="AAA")
    assert out["passages"] and out["passages"][0]["title"].startswith("Ukraine")


def test_tool_validates_and_needs_the_corpus(data_dir):
    assert "make index-docs" in tools.search_methodology("anything")["error"]
    assert "Invalid indicator" in tools.search_methodology("x", indicator="../etc")["error"]


def test_link_citations_replaces_markers_with_passage_links():
    passages = [{"cite": "[1](https://data.worldbank.org/a)"}, {"cite": "[2](https://data.worldbank.org/b)"}]
    text = "Defined as X【1】. Limited by Y【2†L1-L4】 and Z [2]. Kept: [1](https://x) [3] 【9】."
    assert methodology.link_citations(text, passages) == (
        "Defined as X[1](https://data.worldbank.org/a). Limited by Y[2](https://data.worldbank.org/b) and "
        "Z [2](https://data.worldbank.org/b). Kept: [1](https://x) [3] 【9】."
    )
    assert methodology.link_citations("No sources【1】", []) == "No sources【1】"
