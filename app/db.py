"""SQLite for data refs, charts, reports and feedback. Parameterized queries only (no SQL injection)."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS refs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, title TEXT NOT NULL, summary TEXT NOT NULL,
                                    refs TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL,
                                     rating INTEGER NOT NULL, comment TEXT NOT NULL, answer TEXT NOT NULL,
                                     created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS proposals (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                                      payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                                      created TEXT NOT NULL, decided TEXT);
CREATE TABLE IF NOT EXISTS aliases (phrase TEXT PRIMARY KEY, code TEXT NOT NULL, created TEXT NOT NULL);
"""


def connect() -> sqlite3.Connection:
    path = config.data_dir() / "app.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def put_ref(kind: str, payload: dict, prefix: str = "R") -> str:
    ref = f"{prefix}-{uuid.uuid4().hex[:8]}"
    with connect() as conn:
        conn.execute("INSERT INTO refs (id, kind, payload, created) VALUES (?, ?, ?, ?)",
                  (ref, kind, json.dumps(payload), _now()))
    return ref


def get_ref(ref: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT kind, payload FROM refs WHERE id = ?", (ref,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown data_ref {ref!r}")
    return {"kind": row["kind"], **json.loads(row["payload"])}


def save_report(title: str, summary: str, refs: list[str]) -> dict:
    report_id = f"REP-{uuid.uuid4().hex[:6]}"
    with connect() as conn:
        conn.execute("INSERT INTO reports (id, title, summary, refs, created) VALUES (?, ?, ?, ?, ?)",
                  (report_id, title, summary, json.dumps(refs), _now()))
    return {"report_id": report_id, "title": title}


def list_reports(limit: int = 20) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT id, title, created FROM reports ORDER BY created DESC LIMIT ?", (limit,))
        return [dict(row) for row in rows]


def get_report(report_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown report {report_id!r}")
    return dict(row) | {"refs": json.loads(row["refs"])}


def add_feedback(thread_id: str, rating: int, comment: str, answer: str) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO feedback (thread_id, rating, comment, answer, created) VALUES (?, ?, ?, ?, ?)",
                  (thread_id, rating, comment[:2000], answer[:4000], _now()))


def add_proposal(kind: str, payload: dict) -> int:
    with connect() as conn:
        cursor = conn.execute("INSERT INTO proposals (kind, payload, created) VALUES (?, ?, ?)",
                        (kind, json.dumps(payload), _now()))
        return cursor.lastrowid


def list_proposals(status: str = "pending") -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM proposals WHERE status = ? ORDER BY id", (status,)).fetchall()
    return [dict(row) | {"payload": json.loads(row["payload"])} for row in rows]


def decide_proposal(proposal_id: int, status: str) -> dict:
    if status not in ("approved", "rejected"):
        raise ValueError("status must be approved or rejected")
    with connect() as conn:
        row = conn.execute("SELECT * FROM proposals WHERE id = ? AND status = 'pending'", (proposal_id,)).fetchone()
        if row is None:
            raise ValueError(f"No pending proposal {proposal_id}")
        conn.execute("UPDATE proposals SET status = ?, decided = ? WHERE id = ?", (status, _now(), proposal_id))
    return dict(row) | {"payload": json.loads(row["payload"]), "status": status}


def upsert_alias(phrase: str, code: str) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO aliases (phrase, code, created) VALUES (?, ?, ?) "
                  "ON CONFLICT(phrase) DO UPDATE SET code = excluded.code", (phrase, code, _now()))


def aliases() -> dict[str, str]:
    with connect() as conn:
        return {row["phrase"]: row["code"] for row in conn.execute("SELECT phrase, code FROM aliases")}
