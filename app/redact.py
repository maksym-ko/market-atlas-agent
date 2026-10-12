"""Remove private data from questions before they leave the system (web search)."""
import re


PATTERNS = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("url", re.compile(r"https?://\S+")),
    ("phone", re.compile(r"\+?\d[\d ()-]{8,}\d")),
    ("id", re.compile(r"\b(?:[A-Z]{2,}-\d{2,}|R-[0-9a-f]{8}|C-[0-9a-f]{8}|REP-[0-9a-f]{6})\b")),
    (
        "amount",
        re.compile(r"(?:[$€£₴]\s?\d[\d,.]*(?:\s?(?:k|m|bn)\b)?|\b\d[\d,.]*\s?(?:USD|EUR|GBP|UAH|k|m|bn)\b)", re.I),
    ),
]


def redact(text: str, private_terms: list[str] | None = None) -> tuple[str, list[str]]:
    """Returns (safe text, what was removed). private_terms: e.g. internal dataset or client names."""
    removed = []
    for term in private_terms or []:
        if term and re.search(re.escape(term), text, re.I):
            text = re.sub(re.escape(term), "[private]", text, flags=re.I)
            removed.append("private term")
    for label, pattern in PATTERNS:
        text, matches = pattern.subn(f"[{label}]", text)
        if matches:
            removed.append(label)
    return text.strip()[:400], sorted(set(removed))


