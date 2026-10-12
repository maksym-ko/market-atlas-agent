"""Methodology RAG: answers "how is X measured?", "what are its limits?", "why does country Y's data look
odd?" from the World Bank's own documentation, with citations.

Corpus (built by `make index-docs` from the WDI bulk zip that `make wdi` downloads, ~11k passages):
- indicator docs: definition, methodology, limitations, source, development relevance, per indicator
- country profiles: census year, accounting standards, special notes, per country
- country notes: what the World Bank says about one country's series (repeated notes grouped)

Passages are split on sentence boundaries and prefixed with their document title (so a chunk about
"its limitations" still says which indicator it belongs to). They are kept locally in data/docs.jsonl
and uploaded to Pinecone (namespace "docs"); search filters by indicator (a list per passage) and
country metadata. Without Pinecone (strict privacy mode, no key, errors) the same passages are
searched by keywords.
"""
import csv
import io
import json
import re
import zipfile
from functools import lru_cache
from pathlib import Path

from app import config, vectorstore

SECTIONS = {  # WDISeries.csv field -> section label
    "Long definition": "Definition",
    "Statistical concept and methodology": "Methodology",
    "Limitations and exceptions": "Limitations",
    "Source": "Source",
    "Development relevance": "Development relevance",
}
COUNTRY_FIELDS = ["Special Notes", "Currency Unit", "System of National Accounts", "National accounts base year",
                  "National accounts reference year", "SNA price valuation", "PPP survey year",
                  "Balance of Payments Manual in use", "External debt Reporting status", "System of trade",
                  "Government Accounting concept", "IMF data dissemination standard", "Latest population census",
                  "Latest household survey", "Source of most recent Income and expenditure data",
                  "Vital registration complete", "Latest agricultural census", "Latest industrial data",
                  "Latest trade data"]
CHUNK = 1200  # characters; definitions fit in one chunk, long methodology sections split in 2-4
FIELDS = ["text", "title", "section", "url", "indicators", "country"]
# citation markers models write instead of the ready-made link: 【1】, 【2†L1-L4】, or a bare [3]
MARKER = re.compile(r"【(\d+)(?:†[^】]*)?】|\[(\d+)\](?![(\[:])")


def path() -> Path:
    return config.data_dir() / "docs.jsonl"


def split(text: str, size: int = CHUNK) -> list[str]:
    """Sentence-boundary chunks of at most ~size characters."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= size:
        return [text] if text else []
    chunks, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if current and len(current) + len(sentence) > size:
            chunks.append(current)
            current = ""
        current += (" " if current else "") + sentence
    return chunks + ([current] if current else [])


def _rows(archive: zipfile.ZipFile, name: str):
    with archive.open(name) as csv_file:
        yield from csv.DictReader(io.TextIOWrapper(csv_file, encoding="utf-8-sig", newline=""))


def build_corpus(zip_path: Path) -> list[dict]:
    archive = zipfile.ZipFile(zip_path)
    docs = []

    def add(doc_id, title, section, body, url, indicators=(), country=""):
        docs.append({"_id": doc_id, "title": title, "section": section, "url": url, "indicators": list(indicators),
                     "country": country, "text": f"{title}. {section}: {body}"})

    names = {}
    for row in _rows(archive, "WDISeries.csv"):
        code, name = row["Series Code"], row["Indicator Name"]
        names[code] = name
        url = f"https://data.worldbank.org/indicator/{code}"
        for field, section in SECTIONS.items():
            for chunk_no, chunk in enumerate(split(row.get(field, ""))):
                add(
                    f"ind:{code}:{section[:3].lower()}:{chunk_no}",
                    f"{name} ({code})",
                    section,
                    chunk,
                    url,
                    indicators=[code],
                )

    countries = {}
    for row in _rows(archive, "WDICountry.csv"):
        if not row["Region"].strip():  # aggregates (World, EU...) have no country profile worth citing
            continue
        iso3, iso2 = row["Country Code"], row["2-alpha code"]
        countries[iso3] = (row["Table Name"], iso2)
        facts = "; ".join(
            f"{field_name}: {row[field_name].strip()}"
            for field_name in COUNTRY_FIELDS
            if row.get(field_name, "").strip()
        )
        for chunk_no, chunk in enumerate(split(facts)):
            add(f"cty:{iso3}:{chunk_no}", f"{row['Table Name']} ({iso3}) country profile", "Country data notes", chunk,
                f"https://data.worldbank.org/country/{iso2}", country=iso3)

    groups: dict[tuple[str, str], list[str]] = {}
    for row in _rows(archive, "WDIcountry-series.csv"):
        if row["CountryCode"] in countries and row["DESCRIPTION"].strip():
            groups.setdefault((row["CountryCode"], row["DESCRIPTION"].strip()), []).append(row["SeriesCode"])
    for note_no, ((iso3, note), codes) in enumerate(sorted(groups.items())):
        country, iso2 = countries[iso3]
        shown = ", ".join(f"{names.get(series_code, series_code)} ({series_code})" for series_code in codes[:6]) + (
            f" and {len(codes) - 6} more" if len(codes) > 6 else ""
        )
        for chunk_no, chunk in enumerate(split(f"{note} Applies to: {shown}.")):
            add(
                f"note:{iso3}:{note_no}:{chunk_no}",
                f"{country} ({iso3}): note on {len(codes)} indicator(s)",
                "Country note",
                chunk,
                f"https://data.worldbank.org/country/{iso2}",
                indicators=codes,
                country=iso3,
            )
    return docs


def save(docs: list[dict]) -> None:
    path().write_text("".join(json.dumps(doc, ensure_ascii=False) + "\n" for doc in docs))


@lru_cache(maxsize=2)
def _load(file_path: str, mtime_ns: int) -> list[dict]:
    return [json.loads(line) for line in Path(file_path).read_text().splitlines() if line]


def docs() -> list[dict]:
    file_path = path()
    return _load(str(file_path), file_path.stat().st_mtime_ns) if file_path.exists() else []


STOP = {"the", "and", "for", "of", "in", "to", "a", "an", "by", "with", "on", "is", "are", "how", "what", "why",
        "does", "do", "its", "it", "this", "that", "data"}


def _keyword(question: str, limit: int, indicator: str | None, country: str | None) -> list[dict]:
    terms = [term for term in re.findall(r"[a-z0-9.]+", question.lower()) if term not in STOP and len(term) > 2]
    scored = []
    for doc in docs():
        if (indicator and indicator not in doc["indicators"]) or (country and doc["country"] != country) \
                or (indicator and not country and doc["country"]):
            continue
        text = doc["text"].lower()
        score = sum(text.count(term) for term in terms)
        if score:
            scored.append((score, doc))
    scored.sort(key=lambda item: -item[0])
    return [doc for _, doc in scored[:limit]]


def search(question: str, limit: int = 5, indicator: str | None = None, country: str | None = None) -> tuple[list, str]:
    """Top passages and how they were found ("semantic" or "keyword")."""
    metadata_filter = {}
    if indicator:
        metadata_filter["indicators"] = {"$in": [indicator]}
    if country:
        metadata_filter["country"] = {"$eq": country}
    elif indicator:  # a general question about an indicator: leave out notes about particular countries
        metadata_filter["country"] = {"$eq": ""}
    hits = vectorstore.query("docs", question, limit, FIELDS, metadata_filter)
    if hits is not None:
        return hits, "semantic"
    return _keyword(question, limit, indicator, country), "keyword"


def link_citations(text: str, passages: list[dict]) -> str:
    """Replace citation markers with the matching passage's `cite` link. Numbers with no passage stay as written."""
    def link(match: re.Match) -> str:
        number = int(match.group(1) or match.group(2))
        return passages[number - 1]["cite"] if 1 <= number <= len(passages) else match.group(0)

    return MARKER.sub(link, text) if passages else text
