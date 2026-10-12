"""Frozen data for scoring and the map: data/snapshot.json, built by `make data`."""
import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app import config
from app.models import Country


@lru_cache(maxsize=4)
def _load(path: str, mtime_ns: int) -> dict:
    return json.loads(Path(path).read_text())


def load() -> dict:
    path = config.data_dir() / "snapshot.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `make data` first")
    return _load(str(path), path.stat().st_mtime_ns)


def snapshot_id() -> str:
    return load()["created"]


def countries() -> list[Country]:
    return [Country.model_validate(country) for country in load()["countries"]]


def names() -> dict[str, str]:
    return {country.iso3: country.name for country in countries()}


def frame(indicator: str) -> pd.DataFrame:
    """Tidy frame (iso3, year, value) for one snapshot indicator, real countries only."""
    rows = load()["observations"].get(indicator)
    if rows is None:
        raise KeyError(f"{indicator} is not in the snapshot")
    observations = pd.DataFrame(rows, columns=["iso3", "year", "value"]).dropna()
    return observations[observations["iso3"].isin(names())]
