"""Eval checkers: number grounding and citations (evals/run_evals.py)."""
from evals.run_evals import citations_ok, grounding, rendered


def test_grounding_checks_numbers_against_tool_output():
    tools = ['{"latest": [2024, 6.502], "max": 48.7}']
    assert grounding("Inflation peaked at 48.7% and was 6.5% in 2024.", tools) == 1.0
    assert grounding("Inflation peaked at 52.3%.", tools) == 0.0
    assert grounding("Over 10 years since 2014, nothing to check.", tools) == 1.0  # years and small counts skipped
    assert grounding("ARIMA(1,1,0) with a 95 % confidence interval", tools) == 1.0  # labels, not data claims
    assert grounding("GDP was 12,345.6 dollars", ['{"v": 12345.6}']) == 1.0


def test_citation_check_rejects_invented_urls():
    tools = ['{"passages": [{"url": "https://data.worldbank.org/indicator/NY.GDP.PCAP.CD"}]}']
    good = "Defined as GDP over population [1](https://data.worldbank.org/indicator/NY.GDP.PCAP.CD)."
    assert citations_ok(good, tools, required=True)
    assert not citations_ok(good + " See https://example.com/made-up.", tools, required=True)
    assert not citations_ok("No sources given.", tools, required=True)
    assert citations_ok("No sources given.", tools, required=False)


def test_answer_is_scored_as_the_user_sees_it():
    url = "https://data.worldbank.org/indicator/NY.GDP.PCAP.CD"
    tools = ['{"passages": [{"cite": "[1](%s)", "title": "GDP per capita"}]}' % url]
    answer = rendered("GDP divided by midyear population 【1†L1-L4】. More at https://example.com/x", tools)
    assert f"[1]({url})" in answer and "example.com" not in answer
    assert citations_ok(answer, tools, required=True)
