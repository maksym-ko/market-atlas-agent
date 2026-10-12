"""Deterministic metrics over tidy frames (iso3, year, value). The LLM never computes these."""
import pandas as pd


def latest_full_year(observations: pd.DataFrame, min_share: float = 0.5) -> int:
    """Latest year that at least `min_share` of countries have reported (avoids sparse recent years)."""
    counts = observations.groupby("year")["iso3"].nunique()
    good = counts[counts >= counts.max() * min_share]
    return int(good.index.max())


def window(observations: pd.DataFrame, years: int, end: int | None = None) -> pd.DataFrame:
    end = end or latest_full_year(observations)
    return observations[(observations["year"] > end - years) & (observations["year"] <= end)]


def metric(observations: pd.DataFrame, kind: str, years: int = 5, min_points: int | None = None) -> pd.DataFrame:
    """Per-country metric with the years actually used: columns iso3, value, y0, y1."""
    in_window = window(observations, years)
    min_points = min_points or (1 if kind == "latest" else max(2, years // 2 + 1))
    by_country = in_window.sort_values("year").groupby("iso3")
    if kind == "latest":
        result = by_country.tail(1).rename(columns={"year": "y1"}).assign(y0=lambda frame: frame["y1"])
    elif kind == "avg":
        result = by_country.agg(value=("value", "mean"), y0=("year", "min"), y1=("year", "max"), n=("value", "size"))
        result = result[result["n"] >= min_points].reset_index()
    elif kind == "change":  # last value minus first value in the window, in the indicator's units
        result = by_country.agg(first=("value", "first"), value=("value", "last"), y0=("year", "min"),
                    y1=("year", "max"), n=("value", "size"))
        result = result[result["n"] >= min_points].reset_index()
        result["value"] = result["value"] - result["first"]
    else:
        raise ValueError("metric must be one of: latest, avg, change")
    return result[["iso3", "value", "y0", "y1"]].reset_index(drop=True)


def better_than_pct(values: pd.Series, higher_is_better: bool = True) -> pd.Series:
    """Share of other countries this one beats, 0-100."""
    count = len(values)
    if count < 2:
        return pd.Series([100] * count, index=values.index)
    ranks = (values if higher_is_better else -values).rank(method="min") - 1
    return (ranks / (count - 1) * 100).round().astype(int)
