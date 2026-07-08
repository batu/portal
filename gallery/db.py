"""SQLite storage layer for Gallery. Plain sqlite3, no ORM.

A single module-level connection guarded by a lock is enough for a
single-user, low-volume review tool (per the project brief).
"""

import hashlib
import json
import re
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

_lock = threading.RLock()
_init_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_request_id() -> str:
    return "req_" + secrets.token_hex(3)


def new_stream_id() -> str:
    return "s_" + secrets.token_hex(3)


def new_post_id() -> str:
    return "p_" + secrets.token_hex(3)


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _column_names(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _migrate_v1(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS streams (
            id TEXT PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            closed_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            stream_id TEXT NOT NULL REFERENCES streams(id),
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            body_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_stream_created ON posts(stream_id, created_at)")
    _add_column_if_missing(conn, "requests", "stream_id", "stream_id TEXT REFERENCES streams(id)")
    _add_column_if_missing(conn, "requests", "before_media_path", "before_media_path TEXT")
    _add_column_if_missing(conn, "requests", "before_media_type", "before_media_type TEXT")


MIGRATIONS = [(1, _migrate_v1)]


def _user_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _run_migrations(conn: sqlite3.Connection) -> None:
    current = _user_version(conn)
    for version, migration in MIGRATIONS:
        if current >= version:
            continue
        try:
            conn.execute("BEGIN")
            migration(conn)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        current = version


def connect() -> sqlite3.Connection:
    """Return the process-wide connection, opening it on first use."""
    global _conn
    if _conn is not None:
        return _conn
    with _init_lock:
        if _conn is not None:
            return _conn
        path = config.db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(SCHEMA)
            conn.commit()
            _run_migrations(conn)
        except Exception:
            conn.close()
            raise
        _conn = conn
        return _conn


def reset_connection() -> None:
    """Close and drop the cached connection (used by tests switching data dirs)."""
    global _conn
    with _init_lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _stream_from_row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _post_from_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    post = dict(row)
    post["body"] = json.loads(post.pop("body_json"))
    return post


def _get_stream_by_slug(conn: sqlite3.Connection, slug: str) -> dict | None:
    return _stream_from_row(conn.execute("SELECT * FROM streams WHERE slug = ?", (slug,)).fetchone())


def _get_stream_by_id(conn: sqlite3.Connection, stream_id: str) -> dict | None:
    return _stream_from_row(conn.execute("SELECT * FROM streams WHERE id = ?", (stream_id,)).fetchone())


def _create_stream(
    conn: sqlite3.Connection,
    slug: str,
    kind: str,
    title: str,
    created_at: str | None = None,
) -> dict:
    stream_id = new_stream_id()
    conn.execute(
        "INSERT INTO streams (id, slug, kind, title, created_at) VALUES (?, ?, ?, ?, ?)",
        (stream_id, slug, kind, title, created_at or now_iso()),
    )
    stream = _get_stream_by_slug(conn, slug)
    assert stream is not None
    return stream


def _ensure_stream(conn: sqlite3.Connection, slug: str) -> dict:
    stream = _get_stream_by_slug(conn, slug)
    if stream is not None:
        return stream
    return _create_stream(conn, slug, "session", slug)


def create_stream(slug: str, kind: str, title: str) -> dict:
    conn = connect()
    with _lock:
        try:
            stream = _create_stream(conn, slug, kind, title)
            conn.commit()
            return stream
        except Exception:
            conn.rollback()
            raise


def get_stream(slug: str) -> dict | None:
    conn = connect()
    with _lock:
        return _get_stream_by_slug(conn, slug)


def ensure_stream(slug: str) -> dict:
    conn = connect()
    with _lock:
        try:
            stream = _ensure_stream(conn, slug)
            conn.commit()
            return stream
        except Exception:
            conn.rollback()
            raise


def close_stream(slug: str) -> dict:
    conn = connect()
    closed_at = now_iso()
    with _lock:
        try:
            cur = conn.execute("UPDATE streams SET closed_at = ? WHERE slug = ?", (closed_at, slug))
            if cur.rowcount == 0:
                raise ValueError(f"stream not found: {slug}")
            conn.commit()
            stream = _get_stream_by_slug(conn, slug)
            assert stream is not None
            return stream
        except Exception:
            conn.rollback()
            raise


def _require_open_stream(conn: sqlite3.Connection, stream_id: str) -> dict:
    stream = _get_stream_by_id(conn, stream_id)
    if stream is None:
        raise ValueError(f"stream not found: {stream_id}")
    if stream["closed_at"] is not None:
        raise ValueError(f"stream is closed: {stream_id}")
    return stream


def _create_post(
    conn: sqlite3.Connection,
    stream_id: str,
    type: str,
    title: str,
    author: str,
    body: dict,
    created_at: str | None = None,
) -> dict:
    _require_open_stream(conn, stream_id)
    post_id = new_post_id()
    conn.execute(
        "INSERT INTO posts (id, stream_id, type, title, author, body_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (post_id, stream_id, type, title, author, json.dumps(body), created_at or now_iso()),
    )
    post = _get_post_by_id(conn, post_id)
    assert post is not None
    return post


def create_post(
    stream_id: str,
    type: str,
    title: str,
    author: str,
    body: dict,
    created_at: str | None = None,
) -> dict:
    conn = connect()
    with _lock:
        try:
            post = _create_post(conn, stream_id, type, title, author, body, created_at=created_at)
            conn.commit()
            return post
        except Exception:
            conn.rollback()
            raise


def list_posts(stream_id: str) -> list[dict]:
    conn = connect()
    with _lock:
        rows = conn.execute(
            "SELECT * FROM posts WHERE stream_id = ? ORDER BY created_at, rowid",
            (stream_id,),
        ).fetchall()
    return [_post_from_row(row) for row in rows]


def _get_post_by_id(conn: sqlite3.Connection, post_id: str) -> dict | None:
    return _post_from_row(conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone())


def get_post(post_id: str) -> dict | None:
    conn = connect()
    with _lock:
        return _get_post_by_id(conn, post_id)


def _stream_slug_for_project(project: str | None) -> str:
    if not project:
        return "inbox"
    slug = re.sub(r"[^a-z0-9]+", "-", project.strip().lower()).strip("-")
    digest = hashlib.sha1(project.encode("utf-8")).hexdigest()[:8]
    return f"proj-{slug or 'project'}-{digest}"


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
    created_at = now_iso()
    with _lock:
        try:
            stream = _ensure_stream(conn, _stream_slug_for_project(project))
            conn.execute(
                "INSERT INTO requests (id, title, project, kind, status, context_md, created_at, stream_id) "
                "VALUES (?, ?, ?, ?, 'open', ?, ?, ?)",
                (req_id, title, project, kind, context_md, created_at, stream["id"]),
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
            _create_post(
                conn,
                stream["id"],
                "decision",
                title,
                "gallery",
                {"request_id": req_id},
                created_at=created_at,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return req_id


def list_requests(status: str | None = None, project: str | None = None, q: str | None = None) -> list[dict]:
    conn = connect()
    with _lock:
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
    with _lock:
        return _get_request(conn, req_id)


def _get_request(conn: sqlite3.Connection, req_id: str) -> dict | None:
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
    d["verdict"] = _get_latest_verdict(conn, req_id)
    return d


def get_latest_verdict(req_id: str) -> dict | None:
    conn = connect()
    with _lock:
        return _get_latest_verdict(conn, req_id)


def _get_latest_verdict(conn: sqlite3.Connection, req_id: str) -> dict | None:
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
    with _lock:
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
    with _lock:
        return conn.execute("SELECT COUNT(*) FROM requests WHERE status = 'open'").fetchone()[0]
