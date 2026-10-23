"""Entry point: registers the pages and the JSON API, then starts the server on PORT (default 8080)."""
import os
import secrets

from nicegui import app as nicegui_app
from nicegui import ui

import app.server  # noqa: F401  (registers the JSON API and middleware)
from app import runtime
from app.ui import admin, chart, main  # noqa: F401  (register the pages)

nicegui_app.on_shutdown(runtime.close)

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="Market Atlas", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8080")), reload=False, show=False,
           storage_secret=os.getenv("STORAGE_SECRET") or secrets.token_hex(32))
