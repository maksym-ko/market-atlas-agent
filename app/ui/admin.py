"""Curator page: approve or reject proposals from user feedback. Requires ADMIN_PASSWORD."""
import hmac
import os

from nicegui import app as nicegui_app
from nicegui import ui

from app import db, feedback


@ui.page("/admin")
def admin():
    ui.page_title("Market Atlas · curator")
    password = os.getenv("ADMIN_PASSWORD", "")
    if not password:
        ui.label("Curator page is disabled: set ADMIN_PASSWORD in .env").classes("m-8 text-gray-600")
        return
    container = ui.column().classes("m-6 w-[48rem]")

    def render():
        container.clear()
        with container:
            if not nicegui_app.storage.user.get("admin"):
                password_input = ui.input("Password", password=True).props("outlined")

                def login():
                    if hmac.compare_digest(password_input.value or "", password):
                        nicegui_app.storage.user["admin"] = True
                        render()
                    else:
                        ui.notify("Wrong password", type="negative")

                ui.button("Log in", on_click=login)
                return
            ui.label("Pending proposals from user feedback").classes("text-xl font-bold")
            pending = db.list_proposals()
            if not pending:
                ui.label("Nothing to review.").classes("text-gray-500")
            for proposal in pending:
                with ui.card().classes("w-full"):
                    payload = proposal["payload"]
                    if proposal["kind"] == "alias":
                        ui.label(f"Alias: “{payload['phrase']}” → {payload['code']}").classes("font-medium")
                    else:
                        ui.label("Eval case candidate").classes("font-medium")
                    ui.label(f"Question: {payload.get('question', '')}").classes("text-sm")
                    if payload.get("comment"):
                        ui.label(f"Comment: {payload['comment']}").classes("text-sm text-gray-600")
                    with ui.row():
                        ui.button(
                            "Approve",
                            on_click=lambda proposal_id=proposal["id"]: (feedback.approve(proposal_id), render()),
                        )
                        ui.button(
                            "Reject",
                            on_click=lambda proposal_id=proposal["id"]: (feedback.reject(proposal_id), render()),
                        ).props("outline")

    render()
