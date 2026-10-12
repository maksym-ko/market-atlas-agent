"""Dialogs opened from the main page: 👎 feedback and the report library."""
from nicegui import ui

from app import db, feedback, reports, tracing


def feedback_dialog(thread_id: str, run_id: str | None, question: str, answer: str):
    with ui.dialog() as dialog, ui.card().classes("w-[28rem]"):
        ui.label("What was wrong?").classes("font-bold")
        comment = ui.textarea("Comment").props("outlined maxlength=2000").classes("w-full")
        ui.label("Wrong indicator? Tell us the right one (optional):").classes("text-xs text-gray-500")
        phrase = ui.input("When I say…", placeholder="e.g. rural electricity").props("outlined dense maxlength=80")
        code = ui.input("…I mean indicator code", placeholder="e.g. EG.ELC.ACCS.RU.ZS").props("outlined dense")

        def send_it():
            try:
                feedback.submit(thread_id, -1, question, answer, comment.value or "",
                                phrase.value or "", code.value or "")
            except ValueError as e:
                ui.notify(str(e), type="warning")
                return
            tracing.send_feedback(run_id, 0, comment.value or "")
            dialog.close()
            ui.notify("Thanks! A curator will review it.")

        with ui.row():
            ui.button("Send", on_click=send_it)
            ui.button("Cancel", on_click=dialog.close).props("flat")
    dialog.open()


def reports_dialog():
    with ui.dialog() as dialog, ui.card().classes("w-[32rem]"):
        ui.label("Saved reports").classes("font-bold")
        rows = db.list_reports(50)
        if not rows:
            ui.label("No reports yet. Ask the analyst to save one.").classes("text-gray-500")
        for report in rows:
            with ui.row().classes("w-full items-center"):
                ui.label(report["title"]).classes("grow")
                ui.label(report["created"][:10]).classes("text-xs text-gray-500")
                ui.button(icon="download", on_click=lambda report_id=report["id"]: ui.download.content(
                    reports.to_markdown(report_id), f"{report_id}.md", "text/markdown")).props("flat dense round")
        ui.button("Close", on_click=dialog.close).props("flat")
    dialog.open()
