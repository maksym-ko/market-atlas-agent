"""Security helpers: XSS-safe Markdown, text cleaning, and a CSRF Origin check."""
import re

import nh3

from app import config

ALLOWED_TAGS = {"p", "br", "strong", "em", "b", "i", "ul", "ol", "li", "code", "pre", "blockquote",
                "h3", "h4", "table", "thead", "tbody", "tr", "th", "td", "a", "hr"}  # no <img>: no data leaks


def sanitize_html(html: str) -> str:
    """Used as NiceGUI's `sanitize` callback for Markdown rendered from model output."""
    return nh3.clean(html, tags=ALLOWED_TAGS, attributes={"a": {"href", "title"}},
                     url_schemes={"https"}, link_rel="noopener noreferrer nofollow")


URL = re.compile(r"https?://[^\s)\]>\"']+")
MD_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^\s)]+)\)")


def strip_unsourced_links(text: str, sources: str) -> str:
    """Drop links the model wrote itself: a URL is shown only if it appears in a tool result (`sources`).
    A Markdown link keeps its text; a bare URL becomes "(link removed)"."""
    def sourced(url: str) -> bool:
        return url.rstrip(".,;") in sources

    def bare(match: re.Match) -> str:
        url = match.group(0)
        core = url.rstrip(".,;")
        return url if core in sources else "(link removed)" + url[len(core):]

    text = MD_LINK.sub(lambda m: m.group(0) if sourced(m.group(2)) else m.group(1), text)
    return URL.sub(bare, text)


def clean_text(text: str, max_len: int) -> str:
    """Plain text for titles and stored summaries: strip control chars and HTML tags, cap length."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(text))
    return nh3.clean(text, tags=set())[:max_len].strip()


UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


class OriginCheckMiddleware:
    """CSRF / cross-site WebSocket hijacking defense: state-changing requests and WebSocket
    handshakes must come from an allowed Origin (browsers always send it on those)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers") or [])
            origin = headers.get(b"origin", b"").decode()
            unsafe = scope["type"] == "websocket" or scope.get("method") in UNSAFE
            if unsafe and origin and origin not in config.allowed_origins():
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 4403})
                    return
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"Forbidden origin"})
                return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    """Headers that are safe with NiceGUI (it needs inline scripts, so no strict script-src)."""

    HEADERS = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
               (b"x-frame-options", b"DENY"),
               (b"content-security-policy", b"frame-ancestors 'none'; object-src 'none'; base-uri 'self'")]

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + self.HEADERS
            await send(message)

        await self.app(scope, receive, send_with_headers)
