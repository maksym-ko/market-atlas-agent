"""Run golden conversations against one or more models and score them from the trace (not the reply text).

    uv run python -m evals.run_evals                       # default model
    uv run python -m evals.run_evals --models all          # every enabled model
    uv run python -m evals.run_evals --cases inflation-pl-ua,eu-forest

Runs are traced to LangSmith (tag "eval") when LANGSMITH_TRACING=true.
"""
import argparse
import asyncio
import json
import re
import time
import uuid
from datetime import date

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app import db, groups, methodology, tracing
from app.config import ROOT
from app.graph import build_graph
from app.runtime import inproc_tools
from app.llm import DEFAULT_MODEL, enabled_models
from app.security import strip_unsourced_links

INDICATOR_TOOLS = {"get_series", "rank_countries", "forecast_series"}
# thousands separators only in groups of 3 ("12,345"), so "ARIMA(1,1,0)" isn't read as 110
NUMBER = re.compile(r"(?<![\w.])-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
URL = re.compile(r"https?://[^\s)\]>\"']+")
LABELS = re.compile(r"\b(?:80|90|95|99)\s?%\s?(?:confidence|interval|range|CI|prediction)", re.I)


def numbers(text: str) -> list[float]:
    values = []
    for match in NUMBER.findall(LABELS.sub(" ", text)):
        try:
            values.append(float(match.replace(",", "")))
        except ValueError:
            pass
    return values


def grounding(answer: str, tool_texts: list[str]) -> float:
    """Share of 'real' numbers in the answer that appear in some tool output (within rounding)."""
    source = numbers(" ".join(tool_texts))
    claims = [
        number
        for number in numbers(answer)
        if not (number.is_integer() and (1900 <= number <= 2100 or abs(number) <= 31))
    ]  # skip years, small counts
    if not claims:
        return 1.0

    def found(number: float) -> bool:
        return any(
            abs(number - source_value) <= max(0.051, abs(source_value) * 0.005)
            or abs(abs(number) - abs(source_value)) <= 0.051
            for source_value in source
        )

    return sum(found(number) for number in claims) / len(claims)


def citations_ok(answer: str, tool_texts: list[str], required: bool) -> bool:
    """Every URL in the answer appears in a tool result (none invented); at least one when required."""
    cited = {url.rstrip(".,;") for url in URL.findall(answer)}
    sources = " ".join(tool_texts)
    return (bool(cited) or not required) and all(url in sources for url in cited)


def rendered(answer: str, tool_texts: list[str]) -> str:
    """The answer as the user sees it: citation markers linked to their passages, unsourced links removed
    (the same post-processing as the main UI and the OpenAI-compatible endpoint)."""
    passages = []
    for text in tool_texts:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and data.get("passages"):
            passages = data["passages"]
    return strip_unsourced_links(methodology.link_citations(answer, passages), " ".join(tool_texts))


def ungrounded(answer: str, tool_texts: list[str]) -> list[float]:
    source = numbers(" ".join(tool_texts))
    return [
        number
        for number in numbers(answer)
        if not (number.is_integer() and (1900 <= number <= 2100 or abs(number) <= 31))
        and not any(
            abs(number - source_value) <= max(0.051, abs(source_value) * 0.005)
            or abs(abs(number) - abs(source_value)) <= 0.051
            for source_value in source
        )
    ]


async def run_case(graph, case: dict, model: str) -> dict:
    thread = uuid.uuid4().hex
    calls, tool_texts, answer, last_turn_calls = [], [], "", []
    reports_before = len(db.list_reports(1000))
    started = time.time()
    for turn_no, turn in enumerate(case["turns"]):
        graph_config, _ = tracing.run_config(thread, model, tags=["eval", case["id"]])
        payload = {"messages": [("user", turn)]}
        while True:
            out = await graph.ainvoke(payload, graph_config)
            if "__interrupt__" not in out:
                break
            payload = Command(resume={"approved": bool(case.get("approve")), "reason": "eval policy"})
        msgs = out["messages"]
        turn_calls = [call for message in msgs if message.type == "ai" for call in (message.tool_calls or [])]
        if turn_no == len(case["turns"]) - 1:
            # only the calls made in the last turn
            start = max(index for index, message in enumerate(msgs) if message.type == "human")
            last_turn_calls = [
                call for message in msgs[start:] if message.type == "ai" for call in (message.tool_calls or [])
            ]
            calls = turn_calls
            tool_texts = [str(message.content) for message in msgs if message.type == "tool"]
            raw = next(
                (str(message.content) for message in reversed(msgs) if message.type == "ai" and message.content), ""
            )
            answer = rendered(raw, tool_texts)
    seconds = time.time() - started

    names = {call["name"] for call in calls}
    checks = {"tools": set(case.get("tools", [])) <= names}
    if case.get("indicator"):
        used = {str(call["args"].get("indicator", "")).upper() for call in calls if call["name"] in INDICATOR_TOOLS}
        checks["indicator"] = bool(used & set(case["indicator"]))
    if case.get("countries"):
        pool = last_turn_calls if case.get("last_turn_countries") else calls
        seen = set()
        for call in pool:
            args = call["args"]
            seen |= set(groups.to_iso3(args.get("countries") or []))  # tools accept names and ISO2 too
            if args.get("country"):
                seen |= set(groups.to_iso3([args["country"]]))
        checks["countries"] = set(case["countries"]) <= seen
    if case.get("group"):
        expected = set(groups.resolve(case["group"]))
        ok = any(set(groups.to_iso3(call["args"].get("countries") or [])) == expected for call in calls) or \
            any(str(call["args"].get("group", "")).lower() in ("eu", "european union") for call in calls)
        checks["group"] = ok
    if case.get("no_save"):
        checks["safety"] = len(db.list_reports(1000)) == reports_before
    if case.get("cites") or URL.search(answer):
        checks["citations"] = citations_ok(answer, tool_texts, bool(case.get("cites")))
    grounding_score = grounding(answer, tool_texts)
    checks["grounded"] = grounding_score >= 0.9
    return {"id": case["id"], "pass": all(checks.values()), "checks": checks, "grounding": round(grounding_score, 2),
            "ungrounded": ungrounded(answer, tool_texts)[:8], "answer": answer[:1500],
            "seconds": round(seconds, 1), "tools_called": sorted(names),
            "calls": [{"name": call["name"], "args": call["args"]} for call in calls][:12]}


async def run_model(model: str, cases: list[dict]) -> list[dict]:
    graph = build_graph(inproc_tools(), InMemorySaver())
    results = []
    for case in cases:
        try:
            result = await run_case(graph, case, model)
        except Exception as e:  # rate limits, provider errors: count as a failed case
            result = {"id": case["id"], "pass": False, "checks": {}, "error": f"{type(e).__name__}: {str(e)[:120]}",
                 "seconds": 0, "grounding": 0}
        results.append(result)
        flag = "PASS" if result["pass"] else "FAIL"
        detail = result.get("error") or ", ".join(check for check, passed in result["checks"].items() if not passed)
        if result.get("ungrounded"):
            detail += f"  ungrounded={result['ungrounded']}"
        print(f"  {flag} {case['id']:<20} {result['seconds']:>5}s  {detail}")
    return results


def summary_row(model: str, results: list[dict]) -> str:
    count = len(results)

    def rate(check: str) -> float:
        return sum(1 for result in results if result["checks"].get(check, True) and "error" not in result) / count

    passed = sum(result["pass"] for result in results)
    grounding_avg = sum(result["grounding"] for result in results) / count
    seconds_avg = sum(result["seconds"] for result in results) / count
    errors = sum("error" in result for result in results)
    return (f"| {model} | {passed}/{count} | {rate('tools'):.0%} | {rate('indicator'):.0%} | {rate('countries'):.0%} | "
            f"{rate('safety'):.0%} | {rate('citations'):.0%} | {grounding_avg:.2f} | {seconds_avg:.1f}s | {errors} |")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default=DEFAULT_MODEL, help="comma-separated keys, or 'all'")
    parser.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    args = parser.parse_args()
    cases = [json.loads(line) for line in (ROOT / "evals" / "golden.jsonl").read_text().splitlines() if line.strip()]
    if args.cases:
        cases = [case for case in cases if case["id"] in args.cases.split(",")]
    models = list(enabled_models()) if args.models == "all" else args.models.split(",")

    rows = []
    runs_dir = ROOT / "evals" / "runs"
    runs_dir.mkdir(exist_ok=True)
    for model in models:
        print(f"\n== {model}")
        results = await run_model(model, cases)
        rows.append(summary_row(model, results))
        run_path = runs_dir / f"{date.today()}-{model}.jsonl"
        run_path.write_text("".join(json.dumps(result, ensure_ascii=False) + "\n" for result in results))
        print(f"Per-case output: {run_path}")
    columns = ["Model", "Passed", "Tools", "Indicator", "Countries", "Safety", "Citations", "Grounding", "Avg time",
               "Errors"]
    header = "| " + " | ".join(columns) + " |\n" + "|---" * len(columns) + "|"
    table = "\n".join([header, *rows])
    print("\n" + table)
    results_path = ROOT / "evals" / "results.md"
    with results_path.open("a") as results_file:
        results_file.write(f"\n## {date.today()} · {len(cases)} cases\n\n{table}\n")
    print(f"\nAppended to {results_path}")


if __name__ == "__main__":
    asyncio.run(main())
