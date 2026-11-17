"""Audit trail: one row per tool call (docs/SECURITY.md#audit-log).

Records who called which tool with which arguments, and which evidence IDs came
back (or the error). app/tools.py withholds a tool's facts if this write fails:
no audit, no data. The log lives in briefing.db, so `make unify` starts it fresh.
"""

import datetime as dt
import json
import sqlite3

from app import db

AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    ts          TEXT,   -- UTC timestamp
    user_id     TEXT,
    tool        TEXT,
    args        TEXT,   -- JSON
    result_ids  TEXT,   -- JSON list of evidence IDs returned
    error       TEXT    -- NULL when the call succeeded
)
"""


def log_tool_call(user_id: str, tool: str, args: dict, result_ids: list[str], error: str | None) -> None:
    conn = db.connect(readonly=False)  # the only write the tools make
    try:
        conn.execute(AUDIT_SCHEMA)
        conn.execute("INSERT INTO audit_log VALUES (?, ?, ?, ?, ?, ?)",
                     (dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), user_id, tool,
                      json.dumps(args, default=str, sort_keys=True), json.dumps(result_ids), error))
        conn.commit()
    finally:
        conn.close()


def recent(limit: int = 50, user_id: str | None = None) -> list[dict]:
    """Newest audit rows first; only one user's rows when user_id is given.
    (The API passes the caller's ID: another user's result IDs could name restricted records.)"""
    conn = db.connect()
    try:
        if user_id is None:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM audit_log WHERE user_id = ? ORDER BY rowid DESC LIMIT ?",
                                (user_id, limit)).fetchall()
    except sqlite3.OperationalError:
        return []  # nothing logged yet
    finally:
        conn.close()
    return [dict(row, args=json.loads(row["args"]), result_ids=json.loads(row["result_ids"])) for row in rows]
