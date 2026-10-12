import numpy as np
import pandas as pd
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app import charts, db, forecast
from app.graph import apply_edits, build_graph, make_tools
from tests.test_graph import FakeLLM

YEARS = range(1995, 2025)


@pytest.fixture(autouse=True)
def fake_series(monkeypatch):
    random = np.random.default_rng(0)
    gdp = pd.Series(1000 * np.exp(np.cumsum(0.03 + random.normal(0, 0.02, len(YEARS)))), index=list(YEARS))
    inflation = pd.Series(5 + random.normal(0, 1, len(YEARS)), index=list(YEARS))
    monkeypatch.setattr(forecast, "_annual", lambda indicator, iso3, year_from=1990:
                        inflation if indicator == "FP.CPI.TOTL.ZG" else gdp)


def test_arima_auto_order_and_intervals():
    result = forecast.arima("NY.GDP.PCAP.CD", "AAA", 5)
    assert result["model"].startswith("ARIMA(") and "log" in result["model"] and result["points"] == len(YEARS)
    rows = db.get_ref(result["data_ref"])["forecast"]
    assert [row["year"] for row in rows] == list(range(2025, 2030))
    assert all(row["lo95"] <= row["lo80"] <= row["mean"] <= row["hi80"] <= row["hi95"] for row in rows)
    assert charts.build(result["data_ref"], "line", "f")["data"]  # history, bands and forecast


def test_arima_rejects_bad_input():
    with pytest.raises(ValueError):
        forecast.arima("NY.GDP.PCAP.CD", "AAA", 50)
    with pytest.raises(ValueError):
        forecast.arima("NY.GDP.PCAP.CD", "AAA", 5, p=9, d=1, q=0)


def test_taylor_formula():
    result = forecast.taylor("AAA", years=5, r_star=2, pi_target=5, a_pi=0.5, a_y=0.5)
    row = result["rows"][-1]
    expected = 2 + row["inflation"] + 0.5 * (row["inflation"] - 5) + 0.5 * row["output_gap"]
    assert abs(row["implied_rate"] - expected) < 0.02 and len(result["rows"]) == 5
    assert "not loaded" in result["actual_rates"]


def test_taylor_overlays_user_supplied_actual_rates(data_dir):
    (data_dir / "policy_rates").mkdir()
    (data_dir / "policy_rates" / "AAA.csv").write_text("year,rate\n2024,13.0\n")
    assert forecast.taylor("AAA", years=3)["rows"][-1]["actual_rate"] == 13.0


def test_apply_edits_allowlists_and_coerces():
    msg = AIMessage("", tool_calls=[{"name": "taylor_rule", "id": "c1", "args": {"country": "UKR", "r_star": 2.0}}])
    out = apply_edits(msg, {"c1": {"r_star": "3", "country": "RUS", "years": None}})
    args = out.tool_calls[0]["args"]
    assert args == {"country": "UKR", "r_star": 3.0} and out.id == msg.id  # country not editable, None skipped


@pytest.mark.asyncio
async def test_forecast_is_gated_and_runs_with_edited_horizon():
    call = AIMessage("", tool_calls=[{"name": "forecast_series", "id": "c1",
                                      "args": {"indicator": "NY.GDP.PCAP.CD", "country": "AAA", "horizon": 10}}])
    llm = FakeLLM([call, AIMessage("Done.")])
    graph = build_graph(make_tools(), InMemorySaver(), llm_factory=lambda _: llm)
    graph_config = {"configurable": {"thread_id": "f1"}}
    out = await graph.ainvoke({"messages": [("user", "forecast")]}, graph_config)
    pending = out["__interrupt__"][0].value["pending"][0]
    assert pending["tool"] == "forecast_series" and "horizon" in pending["editable"]
    out = await graph.ainvoke(Command(resume={"approved": True, "edits": {"c1": {"horizon": 3}}}), graph_config)
    tool_msg = next(message for message in out["messages"] if message.type == "tool")
    assert '"forecast"' in tool_msg.content and "2027" in tool_msg.content and "2034" not in tool_msg.content
