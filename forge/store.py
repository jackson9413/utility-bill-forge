"""SQLite session log for past analyses."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

DB_PATH = os.environ.get(
    "ENERGY_BILL_FORGE_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sessions.db"),
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT    NOT NULL,
    utility       TEXT,
    customer_class TEXT,
    total         REAL,
    usage         REAL,
    unit          TEXT,
    score         REAL,
    verdict       TEXT,
    rating        INTEGER,
    notes         TEXT,
    payload       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at DESC);
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def save_session(result: Dict[str, Any], raw_text: str) -> int:
    init_db()
    primary = result.get("primary") or {}
    m = primary.get("metrics") or {}
    s = primary.get("score") or {}
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO sessions (created_at, utility, customer_class, total, usage, unit, "
            "score, verdict, rating, notes, payload) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                m.get("utility"),
                m.get("customer_class"),
                m.get("total"),
                m.get("usage"),
                m.get("unit"),
                s.get("overall"),
                s.get("verdict"),
                None,
                None,
                json.dumps({"result": result, "raw_text": raw_text}),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_sessions(limit: int = 40) -> List[Dict[str, Any]]:
    init_db()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, created_at, utility, customer_class, total, usage, unit, score, verdict, "
            "rating, notes FROM sessions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_session(session_id: int) -> Optional[Dict[str, Any]]:
    init_db()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        payload = json.loads(data.pop("payload"))
        data["result"] = payload.get("result")
        data["raw_text"] = payload.get("raw_text")
        return data
    finally:
        conn.close()


def update_session(session_id: int, rating: Optional[int] = None,
                   notes: Optional[str] = None) -> Optional[Dict[str, Any]]:
    init_db()
    conn = _connect()
    try:
        if rating is not None:
            rating = max(1, min(5, int(rating)))
        conn.execute(
            "UPDATE sessions SET rating = COALESCE(?, rating), notes = COALESCE(?, notes) WHERE id = ?",
            (rating, notes, session_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, created_at, utility, customer_class, total, usage, unit, score, verdict, "
            "rating, notes FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_session(session_id: int) -> bool:
    init_db()
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
