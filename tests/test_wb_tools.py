import httpx
import pytest

from app import db, tools, wb


def fake_api(request: httpx.Request) -> httpx.Response:
    assert request.url.host == "api.worldbank.org"
    page = int(request.url.params["page"])
    if "/indicator/" in request.url.path:
        rows = [{"countryiso3code": "AAA", "date": str(2020 + page), "value": float(page)},
                {"countryiso3code": "BBB", "date": str(2020 + page), "value": None}]
        return httpx.Response(200, json=[{"page": page, "pages": 2}, rows])
    return httpx.Response(200, json=[{"message": [{"value": "Invalid value"}]}])


@pytest.fixture
def mock_wb(monkeypatch):
    monkeypatch.setattr(wb, "_transport", httpx.MockTransport(fake_api))


def test_series_paginates_and_caches(mock_wb, data_dir):
    observations = wb.series("FP.CPI.TOTL.ZG", ["AAA", "BBB"], 2020, 2023)
    assert [(observation.year, observation.value) for observation in observations if observation.iso3 == "AAA"] == [
        (2021, 1.0),
        (2022, 2.0),
    ]
    assert list((data_dir / "cache").glob("*.json"))


def test_get_series_chart_and_report(mock_wb):
    result = tools.get_series("FP.CPI.TOTL.ZG", ["AAA", "BBB"], 2020, 2023)
    assert result["summary"]["AAA"]["latest"] == [2022, 2.0] and result["missing_countries"] == ["BBB"]
    chart = tools.make_chart(result["data_ref"], "line", "Inflation")
    assert db.get_ref(chart["chart_id"])["figure"]["data"][0]["y"] == [1.0, 2.0]
    saved = tools.save_report("My report", [result["data_ref"]], "Summary")
    assert db.get_report(saved["report_id"])["title"] == "My report"


def test_tool_errors_are_returned_not_raised(mock_wb):
    assert "error" in tools.make_chart("R-missing", "line", "x")
    assert "error" in tools.get_series("FP.CPI.TOTL.ZG", ["Poland"])
    assert tools.score_markets(["AAA"])["results"][0]["score"] == 100
