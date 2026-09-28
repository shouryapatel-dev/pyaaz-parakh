"""Tiny SQLite store: one row per graded lot, full result kept as JSON."""
import json
import sqlite3

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lots (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    farmer TEXT,
    centre TEXT,
    verdict TEXT,
    grade_a_pct REAL,
    data TEXT NOT NULL
)"""


def _conn():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(_SCHEMA)
    return con


def save_lot(lot: dict):
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO lots VALUES (?,?,?,?,?,?,?)",
            (lot["id"], lot["created_at"], lot["info"].get("farmer"), lot["info"].get("centre"),
             lot["final"]["verdict"], lot["final"]["grade_a_pct"], json.dumps(lot)),
        )


def get_lot(lot_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT data FROM lots WHERE id=?", (lot_id,)).fetchone()
    return json.loads(row["data"]) if row else None


def list_lots(limit: int = 50) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT id, created_at, farmer, centre, verdict, grade_a_pct FROM lots "
            "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
