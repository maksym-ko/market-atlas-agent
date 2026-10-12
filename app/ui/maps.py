import plotly.graph_objects as go

from app import scoring, snapshot


def score_figure(highlight: list[str] | None = None) -> dict:
    scores = scoring.all_scores()
    names = snapshot.names()
    iso3s = list(scores.index)
    marked = set(highlight or [])
    fig = go.Figure(go.Choropleth(
        locations=iso3s, locationmode="ISO-3", z=scores["score"].tolist(),
        zmin=0, zmax=100, colorscale="YlGnBu",
        customdata=[[names.get(iso3, iso3), int(scores.loc[iso3, "rank"])] for iso3 in iso3s],
        hovertemplate="<b>%{customdata[0]}</b><br>Score %{z} / 100<br>Rank %{customdata[1]}"
                      f" of {len(iso3s)}<extra></extra>",
        marker_line_color=["#d62728" if iso3 in marked else "#ffffff" for iso3 in iso3s],
        marker_line_width=[2.5 if iso3 in marked else 0.4 for iso3 in iso3s],
        colorbar=dict(title="Score", thickness=12, len=0.6),
    ))
    fig.update_geos(projection_type="natural earth", showframe=False, showcoastlines=False,
                    showland=True, landcolor="#e5e5e5")  # gray = not enough data
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=460, dragmode=False)
    # the map is click-only: drop the selection tools, keep zoom, pan, reset and download
    return {**fig.to_plotly_json(), "config": {"modeBarButtonsToRemove": ["lasso2d", "select2d"]}}
