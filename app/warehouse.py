"""Local copy of the full World Development Indicators (WDI) dataset in SQLite: ~9M values.

Built by `make wdi` from the World Bank bulk download (scripts/load_wdi.py). When data/wdi.db exists,
get_series and rank_countries read from it instead of calling the API, and related_indicators can scan
every indicator at once. Without it, the app works as before (live API).

Schema: integer surrogate keys keep the 9M-row fact table small, and its primary key
(indicator_id, country_id, year) is the access path for every query, so no secondary indexes are needed.
"""
import csv
import io
import math
import os
import sqlite3
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path

from app import config
from app.models import Observation

SCHEMA = """
CREATE TABLE countries (id INTEGER PRIMARY KEY, iso3 TEXT NOT NULL UNIQUE, iso2 TEXT, name TEXT NOT NULL,
                        region TEXT, income_level TEXT, is_aggregate INTEGER NOT NULL);
CREATE TABLE indicators (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                         topic TEXT, unit TEXT);
CREATE TABLE observations (indicator_id INTEGER NOT NULL, country_id INTEGER NOT NULL, year INTEGER NOT NULL,
                           value REAL NOT NULL, PRIMARY KEY (indicator_id, country_id, year)) WITHOUT ROWID;
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
BATCH = 50_000


def path() -> Path:
    return config.data_dir() / "wdi.db"


def available() -> bool:
    return path().exists()


@contextmanager
def connect():
    conn = sqlite3.connect(f"file:{path()}?mode=ro", uri=True)  # read-only: the app never writes here
    try:
        conn.execute("PRAGMA cache_size = -200000")  # ~200 MB page cache for scans
        yield conn
    finally:
        conn.close()


# ---------- load ----------

def _rows(archive: zipfile.ZipFile, name: str):
    with archive.open(name) as csv_file:
        yield from csv.DictReader(io.TextIOWrapper(csv_file, encoding="utf-8-sig", newline=""))


def load(zip_path: Path, db_path: Path | None = None, log=print) -> dict:
    """Bulk-load the WDI zip into a new database file, then swap it in atomically.
    Fast-load settings (no journal, no fsync) are safe because a failed load only leaves a temp file."""
    db_path = db_path or path()
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    started = time.perf_counter()
    archive = zipfile.ZipFile(zip_path)
    conn = sqlite3.connect(tmp)
    conn.executescript("PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF; PRAGMA cache_size = -500000;"
                       + SCHEMA)

    countries = {}
    for row in _rows(archive, "WDICountry.csv"):
        region = row["Region"].strip()
        countries[row["Country Code"]] = (row["Country Code"], row["2-alpha code"], row["Table Name"], region,
                                        row["Income Group"].strip(), 0 if region else 1)
    indicators = {row["Series Code"]: (row["Series Code"], row["Indicator Name"], row["Topic"], row["Unit of measure"])
                  for row in _rows(archive, "WDISeries.csv")}

    country_id = {code: surrogate_id for surrogate_id, code in enumerate(countries, 1)}
    indicator_id = {code: surrogate_id for surrogate_id, code in enumerate(indicators, 1)}
    rows, batch, years = 0, [], None
    for row in _rows(archive, "WDICSV.csv"):
        if years is None:
            years = [column for column in row if column.isdigit()]
        iso3, code = row["Country Code"], row["Indicator Code"]
        if iso3 not in country_id:  # no metadata: keep it, but never treat it as a real country
            countries[iso3] = (iso3, "", row["Country Name"], "", "", 1)
            country_id[iso3] = len(country_id) + 1
        if code not in indicator_id:
            indicators[code] = (code, row["Indicator Name"], "", "")
            indicator_id[code] = len(indicator_id) + 1
        country_key, indicator_key = country_id[iso3], indicator_id[code]
        for year in years:
            cell = row[year]
            if cell:
                batch.append((indicator_key, country_key, int(year), float(cell)))
        if len(batch) >= BATCH:
            conn.executemany("INSERT INTO observations VALUES (?, ?, ?, ?)", batch)
            rows += len(batch)
            batch.clear()
    conn.executemany("INSERT INTO observations VALUES (?, ?, ?, ?)", batch)
    rows += len(batch)

    conn.executemany("INSERT INTO countries VALUES (?, ?, ?, ?, ?, ?, ?)",
                     [(country_id[iso3_code], *fields) for iso3_code, fields in countries.items()])
    conn.executemany("INSERT INTO indicators VALUES (?, ?, ?, ?, ?)",
                     [(indicator_id[series_code], *fields) for series_code, fields in indicators.items()])
    seconds = time.perf_counter() - started
    stats = {"rows": rows, "indicators": len(indicators), "economies": len(countries),
             "years": f"{years[0]}-{years[-1]}", "load_seconds": round(seconds, 1),
             "source": "World Bank WDI bulk download", "zip_modified": time.strftime(
                 "%Y-%m-%d", time.gmtime(os.path.getmtime(zip_path)))}
    conn.executemany("INSERT INTO meta VALUES (?, ?)", [(key, str(value)) for key, value in stats.items()])
    conn.commit()
    conn.execute("ANALYZE")
    conn.close()
    os.replace(tmp, db_path)  # atomic: readers see the old file or the new one, never half of one
    stats["size_mb"] = round(db_path.stat().st_size / 1e6)
    log(f"{rows:,} values, {len(indicators)} indicators, {len(countries)} economies "
        f"in {seconds:.0f}s ({rows / seconds:,.0f} rows/s) → {db_path} ({stats['size_mb']} MB)")
    return stats


# ---------- queries ----------

def meta() -> dict:
    with connect() as conn:
        return dict(conn.execute("SELECT key, value FROM meta"))


def has_indicator(code: str) -> bool:
    with connect() as conn:
        return conn.execute("SELECT 1 FROM indicators WHERE code = ?", (code,)).fetchone() is not None


def series(code: str, iso3s: list[str] | None, year_from: int, year_to: int) -> list[Observation]:
    """Same shape as wb.series. iso3s=None means every real country (aggregates excluded)."""
    sql = """SELECT c.iso3, o.year, o.value FROM observations o
             JOIN indicators i ON i.id = o.indicator_id JOIN countries c ON c.id = o.country_id
             WHERE i.code = ? AND o.year BETWEEN ? AND ?"""
    params: list = [code, year_from, year_to]
    if iso3s is None:
        sql += " AND c.is_aggregate = 0"
    else:
        sql += f" AND c.iso3 IN ({','.join('?' * len(iso3s))})"
        params += iso3s
    with connect() as conn:
        return [Observation(indicator=code, iso3=iso3, year=year, value=value)
                for iso3, year, value in conn.execute(sql + " ORDER BY c.iso3, o.year", params)]


def latest_year(code: str, min_countries: int) -> int | None:
    """Latest year that at least `min_countries` real countries have reported for this indicator."""
    sql = """SELECT o.year FROM observations o
             JOIN indicators i ON i.id = o.indicator_id JOIN countries c ON c.id = o.country_id
             WHERE i.code = ? AND c.is_aggregate = 0
             GROUP BY o.year HAVING COUNT(*) >= ? ORDER BY o.year DESC LIMIT 1"""
    with connect() as conn:
        row = conn.execute(sql, (code, min_countries)).fetchone()
    return row[0] if row else None


RELATED_SQL = """
WITH target AS (SELECT id FROM indicators WHERE code = :code),
-- 1. one value per (indicator, country): the average over the window. Scans the whole fact table.
country_avg AS (
    SELECT o.indicator_id, o.country_id, AVG(o.value) AS avg_value
    FROM observations o JOIN countries c ON c.id = o.country_id AND c.is_aggregate = 0
    WHERE o.year BETWEEN :year_from AND :year_to
    GROUP BY o.indicator_id, o.country_id),
-- 2. pair every other indicator with the target, country by country
pairs AS (
    SELECT other.indicator_id, other.avg_value AS other_value, target_avg.avg_value AS target_value
    FROM country_avg other
    JOIN country_avg target_avg
      ON target_avg.country_id = other.country_id AND target_avg.indicator_id = (SELECT id FROM target)
    WHERE other.indicator_id <> (SELECT id FROM target)),
-- 3. rank both sides within each pair set (Spearman: robust to skewed data like GDP)
ranked AS (
    SELECT indicator_id,
           RANK() OVER (PARTITION BY indicator_id ORDER BY other_value) AS other_rank,
           RANK() OVER (PARTITION BY indicator_id ORDER BY target_value) AS target_rank
    FROM pairs)
-- 4. the sums Pearson's formula needs, on the ranks
SELECT i.code, i.name, COUNT(*) AS countries,
       SUM(other_rank) AS sum_x, SUM(target_rank) AS sum_y, SUM(other_rank * other_rank) AS sum_xx,
       SUM(target_rank * target_rank) AS sum_yy, SUM(other_rank * target_rank) AS sum_xy
FROM ranked JOIN indicators i ON i.id = ranked.indicator_id
GROUP BY ranked.indicator_id
HAVING COUNT(*) >= :min_countries
"""


def related(code: str, year_from: int, year_to: int, min_countries: int = 50) -> list[dict]:
    """Spearman correlation across countries between `code` and every other indicator.
    Returns all indicators with enough countries; the caller sorts and trims."""
    results = []
    with connect() as conn:
        rows = conn.execute(RELATED_SQL, {"code": code, "year_from": year_from, "year_to": year_to,
                                          "min_countries": min_countries}).fetchall()
    for indicator_code, name, count, sum_x, sum_y, sum_xx, sum_yy, sum_xy in rows:
        denominator = math.sqrt(max(count * sum_xx - sum_x * sum_x, 0) * max(count * sum_yy - sum_y * sum_y, 0))
        if denominator:
            results.append(
                {
                    "indicator": indicator_code,
                    "name": name,
                    "rho": round((count * sum_xy - sum_x * sum_y) / denominator, 3),
                    "countries": count,
                }
            )
    return results
