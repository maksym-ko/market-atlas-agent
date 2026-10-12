import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

WB_BASE = "https://api.worldbank.org/v2"  # fixed: the LLM never supplies URLs (SSRF)


def data_dir() -> Path:
    return Path(os.getenv("MARKET_DATA_DIR", ROOT / "data"))


def allowed_origins() -> set[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080")
    return {origin.strip() for origin in raw.split(",") if origin.strip()}
