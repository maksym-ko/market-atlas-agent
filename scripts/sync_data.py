"""Freeze the scoring indicators and the indicator catalog into data/.

    uv run python -m scripts.sync_data
"""
import json
from datetime import date

from app import config, wb
from app.scoring import SIGNALS


def main():
    out = config.data_dir()
    out.mkdir(parents=True, exist_ok=True)
    countries = wb.countries()
    observations = {}
    for signal in SIGNALS:
        fetched = wb.series(signal["indicator"], None, 2000, date.today().year)
        observations[signal["indicator"]] = [
            [observation.iso3, observation.year, observation.value]
            for observation in fetched
            if observation.value is not None
        ]
        print(f"{signal['indicator']}: {len(observations[signal['indicator']])} values")
    snap = {"created": date.today().isoformat(),
            "countries": [country.model_dump() for country in countries],
            "observations": observations}
    (out / "snapshot.json").write_text(json.dumps(snap))
    catalog = wb.indicator_catalog()
    (out / "indicators.json").write_text(json.dumps(catalog))
    print(f"{len(countries)} countries, {len(catalog)} catalog indicators → {out}")


if __name__ == "__main__":
    main()
