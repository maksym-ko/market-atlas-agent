"""Markdown export of saved reports, rebuilt from the stored data refs (not from model text alone)."""
from app import db, snapshot


def _table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def _section(ref: str) -> str:
    try:
        data = db.get_ref(ref)
    except ValueError:
        return f"_Data {ref} is no longer available._"
    names = snapshot.names()
    kind = data["kind"]
    if kind == "series":
        rows = []
        for iso3, points in data["values"].items():
            years = sorted(points, key=int)
            rows.append(
                [names.get(iso3, iso3), f"{points[years[0]]} ({years[0]})", f"{points[years[-1]]} ({years[-1]})"]
            )
        return (
            f"### {data['indicator_name']} (`{data['indicator']}`)\n\n"
            + _table(["Country", "First", "Latest"], rows)
            + f"\n\nSource: https://data.worldbank.org/indicator/{data['indicator']}"
        )
    if kind in ("scores", "ranking"):
        title = (
            "Market attractiveness score" if kind == "scores" else f"Ranking: `{data['indicator']}` ({data['metric']})"
        )
        return f"### {title}\n\n" + _table(
            ["Country", "Value"], [[names.get(row["iso3"], row["iso3"]), row["value"]] for row in data["rows"]]
        )
    if kind == "forecast":
        return f"### ARIMA forecast: `{data['indicator']}`, {data['name']}\n\n" + _table(
            ["Year", "Forecast", "95% range"],
            [
                [row["year"], round(row["mean"], 2), f"{row['lo95']:.2f} – {row['hi95']:.2f}"]
                for row in data["forecast"]
            ],
        )
    if kind == "taylor":
        assumptions = data["assumptions"]
        return (
            f"### Taylor rule: {data['name']}\n\n"
            f"Assumptions: r* = {assumptions['r_star']}, π* = {assumptions['pi_target']}, "
            f"a_π = {assumptions['a_pi']}, a_y = {assumptions['a_y']}\n\n"
            + _table(
                ["Year", "Inflation", "Output gap", "Implied rate", "Actual"],
                [
                    [row["year"], row["inflation"], row["output_gap"], row["implied_rate"], row["actual_rate"] or "—"]
                    for row in data["rows"]
                ],
            )
        )
    return f"_({kind} data)_"


def to_markdown(report_id: str) -> str:
    report = db.get_report(report_id)
    parts = [f"# {report['title']}", f"_Saved {report['created']} · World Bank Open Data (CC BY 4.0) · "
                                 f"snapshot {snapshot.snapshot_id()}_", "## Summary", report["summary"], "## Data"]
    parts += [_section(ref) for ref in report["refs"]]
    return "\n\n".join(parts) + "\n"
