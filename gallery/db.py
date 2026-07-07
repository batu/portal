"""SQLite storage layer for Gallery. Plain sqlite3, no ORM.

A single module-level connection guarded by a lock is enough for a
single-user, low-volume review tool (per the project brief).
"""

import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config

KINDS = ("pick-one", "pick-many", "rank", "approve", "comment")

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    project TEXT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    context_md TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS variants (
    request_id TEXT NOT NULL REFERENCES requests(id),
    idx INTEGER NOT NULL,
    media_path TEXT NOT NULL,
    media_type TEXT NOT NULL,
    caption TEXT,
    meta_json TEXT,
    PRIMARY KEY (request_id, idx)
);

CREATE TABLE IF NOT EXISTS verdicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL REFERENCES requests(id),
    selected_indices TEXT NOT NULL,
    ratings_json TEXT,
    comment TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status);
CREATE INDEX IF NOT EXISTS idx_requests_project ON requests(project);
CREATE INDEX IF NOT EXISTS idx_verdicts_request ON verdicts(request_id);
"""

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_request_id() -> str:
    return "req_" + secrets.token_hex(3)


def connect() -> sqlite3.Connection:
    """Return the process-wide connection, opening it on first use."""
    global _conn
    if _conn is not None:
        return _conn
    path = config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.commit()
    _conn = conn
    return _conn


def reset_connection() -> None:
    """Close and drop the cached connection (used by tests switching data dirs)."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def create_request(
    req_id: str,
    title: str,
    project: str | None,
    kind: str,
    context_md: str | None,
    variants: list[dict],
) -> str:
    """variants: list of {media_path, media_type, caption, meta} in display order (1-based idx)."""
    conn = connect()
    with _lock:
        conn.execute(
            "INSERT INTO requests (id, title, project, kind, status, context_md, created_at) "
            "VALUES (?, ?, ?, ?, 'open', ?, ?)",
            (req_id, title, project, kind, context_md, now_iso()),
        )
        for i, v in enumerate(variants, start=1):
            conn.execute(
                "INSERT INTO variants (request_id, idx, media_path, media_type, caption, meta_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    req_id,
                    i,
                    v["media_path"],
                    v["media_type"],
                    v.get("caption"),
                    json.dumps(v["meta"]) if v.get("meta") is not None else None,
                ),
            )
        conn.commit()
    return req_id


def list_requests(status: str | None = None, project: str | None = None, q: str | None = None) -> list[dict]:
    conn = connect()
    clauses = []
    params: list = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if project:
        clauses.append("project = ?")
        params.append(project)
    if q:
        clauses.append("(project LIKE ? OR title LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    sql = "SELECT * FROM requests"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["variant_count"] = conn.execute(
            "SELECT COUNT(*) FROM variants WHERE request_id = ?", (d["id"],)
        ).fetchone()[0]
        out.append(d)
    return out


def get_request(req_id: str) -> dict | None:
    conn = connect()
    row = conn.execute("SELECT * FROM requests WHERE id = ?", (req_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    variants = conn.execute(
        "SELECT idx, media_path, media_type, caption, meta_json FROM variants "
        "WHERE request_id = ? ORDER BY idx", (req_id,)
    ).fetchall()
    d["variants"] = []
    for v in variants:
        vd = dict(v)
        vd["meta"] = json.loads(vd.pop("meta_json")) if vd.get("meta_json") else None
        d["variants"].append(vd)
    d["verdict"] = get_latest_verdict(req_id)
    return d


def get_latest_verdict(req_id: str) -> dict | None:
    conn = connect()
    row = conn.execute(
        "SELECT * FROM verdicts WHERE request_id = ? ORDER BY id DESC LIMIT 1", (req_id,)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["selected"] = json.loads(d.pop("selected_indices"))
    d["ratings"] = json.loads(d.pop("ratings_json")) if d.get("ratings_json") else None
    return d


def variant_indices(req_id: str) -> set[int]:
    conn = connect()
    rows = conn.execute("SELECT idx FROM variants WHERE request_id = ?", (req_id,)).fetchall()
    return {r["idx"] for r in rows}


def record_verdict(req_id: str, selected: list[int], ratings: dict | None, comment: str | None) -> dict:
    """Insert a new verdict revision and mark the request decided. Latest verdict wins."""
    conn = connect()
    with _lock:
        conn.execute(
            "INSERT INTO verdicts (request_id, selected_indices, ratings_json, comment, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (req_id, json.dumps(selected), json.dumps(ratings) if ratings is not None else None, comment, now_iso()),
        )
        conn.execute(
            "UPDATE requests SET status = 'decided', decided_at = ? WHERE id = ?",
            (now_iso(), req_id),
        )
        conn.commit()
    return get_latest_verdict(req_id)


def open_count() -> int:
    conn = connect()
    return conn.execute("SELECT COUNT(*) FROM requests WHERE status = 'open'").fetchone()[0]
