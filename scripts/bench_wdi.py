"""Query timings on the local WDI copy (data/wdi.db), as a Markdown table for the README.

    uv run python -m scripts.bench_wdi
"""
import statistics
import time

from app import warehouse


def timed(query, runs: int = 3) -> tuple[float, object]:
    times, result = [], None
    for _ in range(runs):
        started = time.perf_counter()
        result = query()
        times.append(time.perf_counter() - started)
    return statistics.median(times) * 1000, result


def main():
    meta = warehouse.meta()
    with warehouse.connect() as conn:
        window = conn.execute("SELECT COUNT(*) FROM observations WHERE year BETWEEN 2015 AND 2024").fetchone()[0]
    print(f"{int(meta['rows']):,} values · {meta['indicators']} indicators · {meta['economies']} economies · "
          f"{meta['years']} · {warehouse.path().stat().st_size / 1e6:.0f} MB · loaded in {meta['load_seconds']} s\n")
    cases = [
        ("Series: 2 countries, 1 indicator, 20 years", "primary-key range",
         lambda: warehouse.series("FP.CPI.TOTL.ZG", ["POL", "UKR"], 2005, 2024)),
        ("All countries, 1 indicator, all years (rankings)", "primary-key range",
         lambda: warehouse.series("IT.NET.USER.ZS", None, 1960, 2100)),
        ("Related indicators: 1 vs all ~1,500, 10 years", f"scan + group by over {window:,} rows",
         lambda: warehouse.related("IT.NET.USER.ZS", 2015, 2024)),
    ]
    print("| Query | Access | Result rows | Median time |\n|---|---|---|---|")
    for label, access, query in cases:
        median_ms, result = timed(query)
        print(f"| {label} | {access} | {len(result):,} | {median_ms:,.1f} ms |")


if __name__ == "__main__":
    main()
