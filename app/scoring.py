"""Market attractiveness score: four signals, each "better than X% of countries", plain average."""
import pandas as pd

from app import analytics, snapshot

SIGNALS = [
    {"key": "growth", "name": "Economy is growing", "indicator": "NY.GDP.MKTP.KD.ZG", "metric": "avg",
     "higher": True, "fmt": "{v:.1f}% a year ({y0}–{y1}), higher than {p}% of countries"},
    {"key": "people", "name": "More people every year", "indicator": "SP.POP.GROW", "metric": "avg",
     "higher": True, "fmt": "{v:.1f}% a year ({y0}–{y1}), higher than {p}% of countries"},
    {"key": "online", "name": "People are online", "indicator": "IT.NET.USER.ZS", "metric": "latest",
     "higher": True, "fmt": "{v:.0f}% of people ({y1}), more than {p}% of countries"},
    {"key": "prices", "name": "Prices are stable", "indicator": "FP.CPI.TOTL.ZG", "metric": "avg",
     "higher": False, "fmt": "inflation averaged {v:.1f}% ({y0}–{y1}), more stable than {p}% of countries"},
]
MIN_SIGNALS = 3


def _signal_table(signal: dict) -> pd.DataFrame:
    metric_table = analytics.metric(snapshot.frame(signal["indicator"]), signal["metric"], years=5)
    metric_table["p"] = analytics.better_than_pct(metric_table["value"], signal["higher"])
    return metric_table.set_index("iso3")


def all_scores() -> pd.DataFrame:
    """One row per scored country: score, rank, and per-signal value/years/percentile."""
    tables = {signal["key"]: _signal_table(signal) for signal in SIGNALS}
    percentiles = pd.DataFrame({key: table["p"] for key, table in tables.items()})
    enough = percentiles.notna().sum(axis=1) >= MIN_SIGNALS
    scores = percentiles[enough].mean(axis=1).round().astype(int).rename("score").to_frame()
    scores["rank"] = scores["score"].rank(ascending=False, method="min").astype(int)
    scores.attrs["tables"] = tables
    return scores.sort_values("rank")


def explain(iso3: str, scores: pd.DataFrame) -> dict:
    names = snapshot.names()
    tables = scores.attrs["tables"]
    signals = []
    for signal in SIGNALS:
        table = tables[signal["key"]]
        if iso3 not in table.index:
            signals.append({"name": signal["name"], "indicator": signal["indicator"], "sentence": "no recent data"})
            continue
        row = table.loc[iso3]
        sentence = signal["fmt"].format(v=row["value"], y0=int(row["y0"]), y1=int(row["y1"]), p=int(row["p"]))
        signals.append(
            {
                "name": signal["name"],
                "indicator": signal["indicator"],
                "value": round(float(row["value"]), 2),
                "years": [int(row["y0"]), int(row["y1"])],
                "better_than_pct": int(row["p"]),
                "sentence": sentence.replace("-", "−") if row["value"] < 0 else sentence,
            }
        )
    base = {"iso3": iso3, "name": names.get(iso3, iso3), "signals": signals}
    if iso3 not in scores.index:
        return base | {"score": None, "rank": None, "of": len(scores), "note": "not enough data"}
    return base | {"score": int(scores.loc[iso3, "score"]), "rank": int(scores.loc[iso3, "rank"]),
                   "of": len(scores)}
