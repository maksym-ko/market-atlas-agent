"""Plotly figures built from stored data refs. The LLM never supplies data points."""
import plotly.graph_objects as go

from app import db, snapshot

LAYOUT = dict(template="plotly_white", margin=dict(l=40, r=20, t=50, b=40), height=360,
              legend=dict(orientation="h", y=-0.2))


def build(data_ref: str, kind: str, title: str) -> dict:
    data = db.get_ref(data_ref)
    names = snapshot.names()
    fig = go.Figure()
    if kind == "line" and data["kind"] == "forecast":
        _forecast(fig, data)
    elif kind == "line" and data["kind"] == "taylor":
        _taylor(fig, data)
    elif kind == "line":
        if data["kind"] != "series":
            raise ValueError("A line chart needs a data_ref from get_series, forecast_series or taylor_rule")
        for iso3, points in data["values"].items():
            years = sorted(points, key=int)
            fig.add_scatter(x=[int(year) for year in years], y=[points[year] for year in years], mode="lines+markers",
                            name=names.get(iso3, iso3))
        fig.update_layout(yaxis_title=data.get("unit") or data["indicator_name"])
    elif kind == "bar":
        rows = _bar_rows(data)
        rows.sort(key=lambda row: row[1], reverse=True)
        fig.add_bar(x=[names.get(row[0], row[0]) for row in rows], y=[row[1] for row in rows],
                    text=[f"{row[1]:.1f}" for row in rows], textposition="outside")
    else:
        raise ValueError("kind must be 'line' or 'bar'")
    fig.update_layout(title=title[:120], **LAYOUT)
    return fig.to_plotly_json()


def _bar_rows(data: dict) -> list[tuple[str, float]]:
    if data["kind"] == "series":  # latest value per country
        out = []
        for iso3, points in data["values"].items():
            if points:
                last = max(points, key=int)
                out.append((iso3, points[last]))
        return out
    if data["kind"] in ("ranking", "scores"):
        return [(row["iso3"], row["value"]) for row in data["rows"]]
    raise ValueError(f"Can't draw a bar chart from {data['kind']}")


def _forecast(fig: go.Figure, data: dict) -> None:
    hist = sorted(data["history"].items(), key=lambda item: int(item[0]))
    rows = data["forecast"]
    forecast_years = [row["year"] for row in rows]
    fig.add_scatter(
        x=forecast_years + forecast_years[::-1],
        y=[row["hi95"] for row in rows] + [row["lo95"] for row in rows][::-1],
        fill="toself",
        fillcolor="rgba(31,119,180,0.12)",
        line=dict(width=0),
        name="95% range",
    )
    fig.add_scatter(
        x=forecast_years + forecast_years[::-1],
        y=[row["hi80"] for row in rows] + [row["lo80"] for row in rows][::-1],
        fill="toself",
        fillcolor="rgba(31,119,180,0.25)",
        line=dict(width=0),
        name="80% range",
    )
    fig.add_scatter(
        x=[int(year) for year, _ in hist],
        y=[value for _, value in hist],
        mode="lines",
        name=f"{data['name']} actual",
        line=dict(color="#1f77b4"),
    )
    last_year, last_value = int(hist[-1][0]), hist[-1][1]
    fig.add_scatter(x=[last_year] + forecast_years, y=[last_value] + [row["mean"] for row in rows], mode="lines",
                    name="forecast", line=dict(color="#1f77b4", dash="dash"))


def _taylor(fig: go.Figure, data: dict) -> None:
    rows = data["rows"]
    years = [row["year"] for row in rows]
    fig.add_scatter(x=years, y=[row["implied_rate"] for row in rows], mode="lines+markers", name="Taylor-rule rate")
    fig.add_scatter(x=years, y=[row["inflation"] for row in rows], mode="lines", name="inflation",
                    line=dict(dash="dot"))
    if any(row["actual_rate"] is not None for row in rows):
        fig.add_scatter(x=years, y=[row["actual_rate"] for row in rows], mode="lines+markers",
                        name="actual policy rate")
    fig.update_layout(yaxis_title="%")
