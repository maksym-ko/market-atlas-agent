"""World Bank API client: fixed base URL, validated codes, pagination, disk cache."""
import hashlib
import json
import time

import httpx

from app import config
from app.models import Country, Observation, check_countries, check_indicator, check_years

MAX_BYTES = 30_000_000
CACHE_TTL = 7 * 24 * 3600

_transport: httpx.BaseTransport | None = None  # tests inject httpx.MockTransport


def _get(path: str, params: dict) -> list:
    """GET all pages of a World Bank endpoint. `path` is built only from validated codes."""
    params = {"format": "json", "per_page": 20000, **params}
    url = f"{config.WB_BASE}/{path}"
    key = hashlib.sha256(f"{url}?{sorted(params.items())}".encode()).hexdigest()
    cache = config.data_dir() / "cache" / f"{key}.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_TTL:
        return json.loads(cache.read_text())

    rows, page = [], 1
    with httpx.Client(timeout=httpx.Timeout(60, connect=10), follow_redirects=False,
                      transport=_transport) as client:
        while True:
            for attempt in range(3):  # the World Bank API is sometimes slow; retry timeouts and 5xx
                try:
                    resp = client.get(url, params={**params, "page": page})
                    if resp.status_code < 500:
                        break
                except httpx.TimeoutException:
                    if attempt == 2:
                        raise
                time.sleep(1 + attempt)
            resp.raise_for_status()
            if len(resp.content) > MAX_BYTES:
                raise ValueError("World Bank response too large")
            body = resp.json()
            if not isinstance(body, list) or len(body) < 2:
                msg = body[0].get("message") if isinstance(body, list) and body else body
                raise ValueError(f"World Bank API error: {msg}")
            rows += body[1] or []
            if page >= int(body[0].get("pages", 1)):
                break
            page += 1

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows))
    return rows


def source_url(indicator: str, countries: list[str] | None = None) -> str:
    return f"https://data.worldbank.org/indicator/{indicator}" + (
        f"?locations={'-'.join(countries)}" if countries and len(countries) <= 10 else "")


def countries() -> list[Country]:
    """Real countries only; aggregates (World, EU, income groups...) are dropped."""
    return [
        Country(iso3=row["id"], iso2=row.get("iso2Code", ""), name=row["name"], region=row["region"]["value"].strip(),
                income_level=row["incomeLevel"]["value"].strip())
        for row in _get("country", {})
        if row["region"]["value"].strip() != "Aggregates"
    ]


def series(indicator: str, codes: list[str] | None, year_from=None, year_to=None) -> list[Observation]:
    """Yearly observations. codes=None means all countries (aggregates included; filter later)."""
    indicator = check_indicator(indicator)
    location = "all" if codes is None else ";".join(check_countries(codes))
    first_year, last_year = check_years(year_from, year_to)
    rows = _get(f"country/{location}/indicator/{indicator}", {"date": f"{first_year}:{min(last_year, 2100)}"})
    return [
        Observation(indicator=indicator, iso3=row["countryiso3code"], year=int(row["date"]), value=row["value"])
        for row in rows if row.get("countryiso3code")
    ]


def indicator_catalog() -> list[dict]:
    """World Development Indicators (source 2): id, name, description, topics."""
    return [
        {"id": row["id"], "name": row["name"], "description": (row.get("sourceNote") or "")[:400],
         "topics": [topic.get("value", "").strip() for topic in row.get("topics") or [] if topic.get("value")]}
        for row in _get("source/2/indicator", {})
    ]
