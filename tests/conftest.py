import json

import pytest

from app import wb

# 5 fake countries, 4 signals, 2019-2023. ZZZ has only 2 signals -> "not enough data".
COUNTRIES = [
    {
        "iso3": country_code,
        "iso2": country_code[:2],
        "name": country_name,
        "region": "Europe & Central Asia",
        "income_level": "High income",
    }
    for country_code, country_name in [
        ("AAA", "Alpha"),
        ("BBB", "Beta"),
        ("CCC", "Gamma"),
        ("DDD", "Delta, Rep."),
        ("ZZZ", "Zeta"),
    ]
]
LEVELS = {  # growth, population growth, internet %, inflation
    "AAA": (5.0, 1.0, 90.0, 2.0),
    "BBB": (3.0, 0.5, 80.0, 4.0),
    "CCC": (1.0, 0.0, 70.0, 8.0),
    "DDD": (-1.0, -0.5, 60.0, 20.0),
    "ZZZ": (2.0, 0.2, None, None),
}
INDICATORS = ["NY.GDP.MKTP.KD.ZG", "SP.POP.GROW", "IT.NET.USER.ZS", "FP.CPI.TOTL.ZG"]


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    observations = {
        indicator: [
            [iso3, year, levels[position]]
            for iso3, levels in LEVELS.items()
            for year in range(2019, 2024)
            if levels[position] is not None
        ]
        for position, indicator in enumerate(INDICATORS)
    }
    (tmp_path / "snapshot.json").write_text(json.dumps(
        {"created": "2026-10-01", "countries": COUNTRIES, "observations": observations}))
    (tmp_path / "indicators.json").write_text(json.dumps([
        {"id": "AG.LND.FRST.ZS", "name": "Forest area (% of land area)", "description": "Forest land", "topics": []},
        {"id": "EG.ELC.ACCS.RU.ZS", "name": "Access to electricity, rural (% of rural population)",
         "description": "", "topics": []},
    ]))
    monkeypatch.setenv("MARKET_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(wb, "_transport", None)
    return tmp_path
