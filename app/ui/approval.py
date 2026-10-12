"""Approval card for gated tools (save_report, forecast_series, taylor_rule), with editable assumptions."""
import asyncio
import json

from nicegui import ui

from app.security import sanitize_html

TITLES = {"forecast_series": "ARIMA forecast", "taylor_rule": "Taylor rule"}
LABELS = {"horizon": "years ahead", "p": "p (blank=auto)", "d": "d (blank=auto)", "q": "q (blank=auto)",
          "years": "years", "r_star": "neutral rate r*", "pi_target": "inflation target π*",
          "a_pi": "weight on inflation", "a_y": "weight on output gap"}
APPROVAL_TIMEOUT = 600


async def approval_card(container, pending: dict, on_shown=lambda: None) -> dict:
    """Shows the card in `container` and waits for the user. Returns the decision for Command(resume=...)."""
    decision_future = asyncio.get_running_loop().create_future()
    inputs: dict[str, dict] = {}  # call id -> {field: ui.number}
    with container:
        with ui.card().classes("w-full border-amber-400 border-2") as card:
            ui.label("Approval needed").classes("font-bold text-amber-700")
            for call in pending["pending"]:
                if call["tool"] == "save_report":
                    ui.label(f"Save report: “{call['title']}”").classes("font-medium")
                    ui.markdown(call["summary"][:1500], sanitize=sanitize_html).classes("text-sm")
                    continue
                fixed = {name: value for name, value in call["args"].items() if name not in call["editable"]}
                ui.label(f"{TITLES.get(call['tool'], call['tool'])}: {json.dumps(fixed)[:200]}").classes("font-medium")
                ui.label("Check or change the assumptions:").classes("text-xs text-gray-500")
                with ui.row().classes("gap-2"):
                    inputs[call["id"]] = {
                        field: ui.number(LABELS.get(field, field), value=call["args"].get(field), format="%g")
                        .props("dense outlined")
                        .classes("w-28")
                        for field in call["editable"]
                    }

            def approve():
                edits = {
                    call_id: {field: widget.value for field, widget in fields.items()}
                    for call_id, fields in inputs.items()
                }
                decision_future.done() or decision_future.set_result({"approved": True, "edits": edits})

            with ui.row():
                ui.button("✅ Approve", on_click=approve)
                ui.button("❌ Reject", on_click=lambda: decision_future.done() or decision_future.set_result(
                    {"approved": False, "reason": "user rejected"})).props("outline")
    on_shown()
    try:
        decision = await asyncio.wait_for(decision_future, APPROVAL_TIMEOUT)
    except asyncio.TimeoutError:
        decision = {"approved": False, "reason": "timeout"}
    card.clear()
    with card:
        ui.label("✅ Approved" if decision["approved"] else "❌ Rejected").classes("text-sm")
    return decision
