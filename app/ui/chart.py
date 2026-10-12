"""Standalone chart page, linked from answers given through the OpenAI-compatible endpoint."""
import re

from nicegui import ui

from app import db


@ui.page("/chart/{chart_id}")
def chart_page(chart_id: str):
    if not re.fullmatch(r"C-[0-9a-f]{8}", chart_id):
        ui.label("Invalid chart id")
        return
    try:
        fig = db.get_ref(chart_id)["figure"]
    except ValueError:
        ui.label("Chart not found")
        return
    ui.page_title("Market Atlas · chart")
    ui.plotly(fig).classes("w-full max-w-4xl")
