"""Full-dataset store (app/warehouse.py) on a tiny zip with the same layout as the World Bank bulk file."""
import csv
import io
import zipfile

import pandas as pd
import pytest

from app import tools, warehouse

YEARS = [str(year) for year in range(2015, 2025)]
COUNTRIES = ["AAA", "BBB", "CCC", "DDD", "ZZZ"]  # conftest's snapshot countries
# per-country levels: IND.B rises with IND.A, IND.C falls with it, IND.D is unrelated
BASE_LEVELS = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4, "ZZZ": 5}
SERIES = {
    "IND.A": BASE_LEVELS,
    "IND.B": {country_code: base_level * 10 + 1 for country_code, base_level in BASE_LEVELS.items()},
    "IND.C": {country_code: -base_level for country_code, base_level in BASE_LEVELS.items()},
    "IND.D": {"AAA": 3, "BBB": 1, "CCC": 5, "DDD": 2, "ZZZ": 4},
}


def _csv(header, rows) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


@pytest.fixture
def wdi(data_dir):
    zip_path = data_dir / "WDI_CSV.zip"
    data = []
    for code, levels in SERIES.items():
        for iso3 in COUNTRIES + ["WLD"]:  # WLD is an aggregate and must never count as a country
            level = levels.get(iso3, 999)
            data.append([iso3, iso3, f"Indicator {code}", code] + [level] * len(YEARS))
    data.append(["AAA", "AAA", "Indicator IND.A", "IND.EMPTY"] + [""] * len(YEARS))
    countries = [[country, country[:2], country, "Europe & Central Asia", "High income"] for country in COUNTRIES] + \
                [["WLD", "1W", "World", "", ""]]
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "WDICSV.csv", _csv(["Country Name", "Country Code", "Indicator Name", "Indicator Code", *YEARS], data)
        )
        archive.writestr(
            "WDICountry.csv", _csv(["Country Code", "2-alpha code", "Table Name", "Region", "Income Group"], countries)
        )
        archive.writestr(
            "WDISeries.csv",
            _csv(
                ["Series Code", "Indicator Name", "Topic", "Unit of measure"],
                [[series_code, f"Indicator {series_code}", "Test", ""] for series_code in SERIES],
            ),
        )
    stats = warehouse.load(zip_path, log=lambda _: None)
    return stats


def test_load_skips_empty_values_and_marks_aggregates(wdi):
    assert wdi["rows"] == len(SERIES) * 6 * len(YEARS)  # IND.EMPTY has no values
    assert warehouse.available() and not (warehouse.path().with_suffix(".tmp")).exists()
    everyone = {observation.iso3 for observation in warehouse.series("IND.A", None, 2015, 2024)}
    assert everyone == set(COUNTRIES)  # WLD excluded
    assert [observation.iso3 for observation in warehouse.series("IND.A", ["WLD"], 2020, 2020)] == [
        "WLD"
    ]  # but can be asked for


def test_related_matches_pandas_spearman(wdi):
    by_indicator = {row["indicator"]: row for row in warehouse.related("IND.A", 2015, 2024, min_countries=5)}
    assert by_indicator["IND.B"]["rho"] == 1.0 and by_indicator["IND.C"]["rho"] == -1.0
    expected = pd.DataFrame({code: pd.Series(levels) for code, levels in SERIES.items()})
    assert by_indicator["IND.D"]["rho"] == round(expected["IND.A"].corr(expected["IND.D"], method="spearman"), 3)
    assert all(row["countries"] == 5 for row in by_indicator.values())
    assert warehouse.related("IND.A", 2015, 2024, min_countries=6) == []  # not enough countries


def test_tools_read_the_local_copy_and_say_so(wdi, monkeypatch):
    monkeypatch.setattr(tools.wb, "series", lambda *args, **kwargs: pytest.fail("should not call the API"))
    out = tools.get_series("IND.B", ["AAA", "BBB"], 2015, 2024)
    assert out["data_from"].startswith("local WDI copy") and out["summary"]["BBB"]["latest"] == [2024, 21.0]
    assert "Fewer than 20 countries" in tools.related_indicators("IND.A", min_countries=20)["error"]
    assert "error" in tools.related_indicators("IND.A", min_countries=5)  # validation: 20-200
    assert warehouse.latest_year("IND.A", 5) == 2024


def test_related_tool_needs_the_dataset(data_dir):
    assert "make wdi" in tools.related_indicators("IND.A")["error"]
