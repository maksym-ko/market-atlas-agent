"""Main page: clickable world map + country panel + chat with charts and approval cards."""
import json
import uuid

from langgraph.types import Command
from nicegui import ui

from app import db, feedback, methodology, runtime, scoring, tracing
from app.llm import DEFAULT_MODEL, enabled_models, explain_error
from app.security import sanitize_html, strip_unsourced_links
from app.ui import maps
from app.ui.approval import approval_card
from app.ui.dialogs import feedback_dialog, reports_dialog

STARTERS = [
    "Which markets are the most attractive to launch in right now?",
    "Compare inflation in Poland and Ukraine over the last 20 years",
    "Where is access to electricity growing fastest?",
    "Compare EU countries by forest area as % of land",
    "⭐ Make an ARIMA forecast of Ukraine's GDP per capita for the next 10 years",
    "⭐ What should the NBU policy rate have been over the last 10 years according to the Taylor rule?",
]


def text_of(msg) -> str:
    content = msg.content
    return (
        content
        if isinstance(content, str)
        else "".join(block.get("text", "") for block in content if isinstance(block, dict))
    )


@ui.page("/")
async def index():
    state = {"thread_id": uuid.uuid4().hex, "highlight": [], "model": DEFAULT_MODEL,
             "run_id": None, "question": "", "passages": [], "sources": []}
    try:
        scores = scoring.all_scores()
    except FileNotFoundError as e:
        ui.label(str(e)).classes("text-red-600 m-8")
        return

    ui.page_title("Market Atlas")
    with ui.header().classes("items-center bg-slate-800"):
        ui.label("🌍 Market Atlas").classes("text-lg font-bold")
        ui.label("Where should you launch? World Bank data, explained.").classes("text-sm opacity-80")
        ui.space()
        models = enabled_models()
        ui.select(models, value=state["model"], label="Model",
                  on_change=lambda event: state.update(model=event.value)).props("dense dark outlined").classes("w-48")
        ui.button("Reports", on_click=reports_dialog).props("flat color=white")
        ui.button("New chat", on_click=lambda: new_chat()).props("flat color=white")

    with ui.row().classes("w-full no-wrap gap-4 p-2"):
        with ui.column().classes("w-3/5"):
            world = ui.plotly(maps.score_figure()).classes("w-full")
            ui.label("Click a country to see why it scores the way it does. Gray = not enough data.") \
                .classes("text-xs text-gray-500")
            panel = ui.card().classes("w-full")
            with panel:
                ui.label("No country selected").classes("text-gray-500")
        with ui.column().classes("w-2/5 h-[calc(100vh-90px)]"):
            messages = ui.scroll_area().classes("grow w-full border rounded")
            with messages:
                with ui.column().classes("gap-1") as starters:
                    ui.label("Try:").classes("text-sm text-gray-500")
                    for starter in STARTERS:
                        ui.button(starter, on_click=lambda starter=starter: send(starter)).props(
                            "flat no-caps align=left dense"
                        ).classes("text-left")
            with ui.row().classes("w-full no-wrap items-center"):
                input_box = ui.input(placeholder="Ask about any market or World Bank indicator…") \
                    .props("outlined dense maxlength=1000").classes("grow").on("keydown.enter", lambda: submit())
                send_btn = ui.button(icon="send", on_click=lambda: submit()).props("round")

    # ---------- map + panel ----------
    def redraw_map():
        world.update_figure(maps.score_figure(state["highlight"]))

    def show_country(iso3: str):
        info = scoring.explain(iso3, scores)
        panel.clear()
        with panel:
            with ui.row().classes("items-baseline gap-3"):
                ui.label(info["name"]).classes("text-xl font-bold")
                if info["score"] is None:
                    ui.label("not enough data").classes("text-gray-500")
                else:
                    ui.label(f"{info['score']} / 100").classes("text-xl")
                    ui.label(f"rank {info['rank']} of {info['of']}").classes("text-gray-500")
            for signal in info["signals"]:
                ui.markdown(f"**{signal['name']}:** {signal['sentence']}", sanitize=sanitize_html)
            with ui.row():
                ui.button("Chat about this country", on_click=lambda: send(
                    f"Tell me about {info['name']} ({iso3}) as a market to launch a business.")).props("size=sm")

    def on_map_click(event):
        try:
            iso3 = event.args["points"][0]["location"]
        except (KeyError, IndexError, TypeError):
            return
        if isinstance(iso3, str) and len(iso3) == 3:
            show_country(iso3)

    world.on("plotly_click", on_map_click)

    # ---------- chat ----------
    def scroll():
        messages.scroll_to(percent=1.0)

    def add_bot_message(text: str):
        with messages:
            with ui.chat_message(name="Analyst").classes("w-full"):
                ui.markdown(text, sanitize=sanitize_html)
                with ui.row().classes("gap-0"):
                    run_id, question = state["run_id"], state["question"]
                    ui.button(icon="thumb_up", on_click=lambda: thumbs_up(run_id, question, text)) \
                        .props("flat dense round size=xs color=grey")
                    ui.button(icon="thumb_down", on_click=lambda: feedback_dialog(
                        state["thread_id"], run_id, question, text)).props("flat dense round size=xs color=grey")
        scroll()

    def thumbs_up(run_id, question, answer):
        feedback.submit(state["thread_id"], 1, question, answer)
        tracing.send_feedback(run_id, 1)
        ui.notify("Thanks for the feedback")

    def add_step(name: str, args: dict):
        with messages:
            with ui.expansion(f"🔧 {name}", icon=None).classes("text-xs text-gray-500 w-full"):
                ui.label(json.dumps(args, ensure_ascii=False)[:500]).classes("text-xs")

    def handle_tool_result(msg):
        state["sources"].append(text_of(msg))  # links in answers must come from here
        try:
            data = json.loads(text_of(msg))
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(data, dict):
            return
        if data.get("chart_id"):
            fig = db.get_ref(data["chart_id"])["figure"]
            with messages:
                ui.plotly(fig).classes("w-full")
            scroll()
        if data.get("ui_action") == "highlight":
            state["highlight"] = data["countries"]
            redraw_map()
        if data.get("passages"):  # sources come from the tool result, whether or not the model cites them
            state["passages"] = data["passages"]
            lines = [f"- {passage['cite']} {passage['title']} · {passage['section']}" for passage in data["passages"]]
            with messages:
                with ui.expansion(f"📚 Sources ({len(lines)})").classes("text-xs w-full"):
                    ui.markdown("\n".join(lines), sanitize=sanitize_html).classes("text-xs")

    async def run(graph, payload, graph_config):
        async for chunk in graph.astream(payload, graph_config, stream_mode="updates"):
            for node, update in chunk.items():
                if node == "__interrupt__":
                    return update[0].value
                if not update or "messages" not in update:
                    continue
                for msg in update["messages"]:
                    if node == "agent":
                        for call in getattr(msg, "tool_calls", []):
                            add_step(call["name"], call["args"])
                        if text_of(msg).strip():
                            text = methodology.link_citations(text_of(msg), state["passages"])
                            add_bot_message(strip_unsourced_links(text, " ".join(state["sources"])))
                    elif node == "tools":
                        handle_tool_result(msg)
        return None

    async def send(text: str):
        text = text.strip()[:1000]
        if not text:
            return
        starters.set_visibility(False)
        with messages:
            ui.chat_message(text, name="You", sent=True).classes("w-full")
        scroll()
        send_btn.disable()
        spinner = None
        with messages:
            spinner = ui.spinner("dots")
        try:
            graph = await runtime.get_graph()
            state["question"], state["passages"] = text, []
            graph_config, state["run_id"] = tracing.run_config(state["thread_id"], state["model"])
            payload = {"messages": [("user", text)]}
            pending = await run(graph, payload, graph_config)
            while pending:  # the approval gate paused the graph
                decision = await approval_card(messages, pending, on_shown=scroll)
                graph_config, state["run_id"] = tracing.run_config(state["thread_id"], state["model"])
                pending = await run(graph, Command(resume=decision), graph_config)
        except Exception as e:  # API errors, missing keys, rate limits: keep the page alive
            add_bot_message(f"⚠️ {explain_error(e, state['model'])}")
        finally:
            spinner.delete()
            send_btn.enable()

    async def submit():
        text = input_box.value
        input_box.value = ""
        await send(text)

    def new_chat():
        state.update(thread_id=uuid.uuid4().hex, highlight=[])
        messages.clear()
        redraw_map()
        ui.notify("New conversation")
