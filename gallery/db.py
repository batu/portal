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

KINDS = ("pick-one", "pick-many", "rank", "approve", "comment", "before-after", "view")
MESSAGE_DIRECTIONS = ("to_agent", "to_human")
STREAM_SLUG_MAX_LENGTH = 128
PROJECT_STREAM_PREFIX = "proj-"

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


class StreamNotFoundError(ValueError):
    pass


class StreamClosedError(ValueError):
    pass


class MessageNotFoundError(ValueError):
    pass


class RequestNotFoundError(ValueError):
    pass


class RequestTerminalError(ValueError):
    pass


class SuccessorNotFoundError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_request_id() -> str:
    return "req_" + secrets.token_hex(3)


def new_stream_id() -> str:
    return "s_" + secrets.token_hex(3)


def new_post_id() -> str:
    return "p_" + secrets.token_hex(3)


def new_message_id() -> str:
    return "m_" + secrets.token_hex(3)


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _column_names(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _validate_v1_schema(conn: sqlite3.Connection) -> None:
    required = {
        "requests": {"stream_id", "before_media_path", "before_media_type"},
        "streams": {"id", "slug", "kind", "title", "created_at", "closed_at"},
        "posts": {"id", "stream_id", "type", "title", "author", "body_json", "created_at"},
    }
    for table, columns in required.items():
        missing = columns - _column_names(conn, table)
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise RuntimeError(f"schema v1 missing {table} columns: {missing_list}")


def _validate_message_direction_constraint(conn: sqlite3.Connection) -> None:
    suffix = secrets.token_hex(4)
    stream_id = f"__schema_validation_stream_{suffix}__"
    conn.execute("SAVEPOINT validate_message_direction")
    try:
        conn.execute(
            "INSERT INTO streams (id, slug, kind, title, created_at) VALUES (?, ?, ?, ?, ?)",
            (stream_id, f"schema-validation-{suffix}", "session", "Schema validation", now_iso()),
        )
        for direction in MESSAGE_DIRECTIONS:
            try:
                conn.execute(
                    "INSERT INTO messages (id, stream_id, direction, text, created_at) VALUES (?, ?, ?, ?, ?)",
                    (f"__schema_validation_message_{direction}_{suffix}__", stream_id, direction, "probe", now_iso()),
                )
            except sqlite3.IntegrityError as exc:
                raise RuntimeError("schema v2 messages missing direction constraint") from exc
        try:
            conn.execute(
                "INSERT INTO messages (id, stream_id, direction, text, created_at) VALUES (?, ?, ?, ?, ?)",
                (f"__schema_validation_message_invalid_{suffix}__", stream_id, "other", "probe", now_iso()),
            )
        except sqlite3.IntegrityError:
            return
        raise RuntimeError("schema v2 messages missing direction constraint")
    finally:
        conn.execute("ROLLBACK TO validate_message_direction")
        conn.execute("RELEASE validate_message_direction")


def _validate_v2_schema(conn: sqlite3.Connection) -> None:
    missing = {"id", "stream_id", "direction", "text", "created_at", "consumed_at"} - _column_names(
        conn, "messages"
    )
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise RuntimeError(f"schema v2 missing messages columns: {missing_list}")
    message_fks = conn.execute("PRAGMA foreign_key_list(messages)").fetchall()
    if not any(row["from"] == "stream_id" and row["table"] == "streams" and row["to"] == "id" for row in message_fks):
        raise RuntimeError("schema v2 messages missing stream_id foreign key")
    table_row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'messages'").fetchone()
    table_sql = re.sub(r"\s+", " ", (table_row["sql"] or "").lower()) if table_row is not None else ""
    if not re.search(r"check\s*\(\s*direction\s+in\s*\(\s*'to_agent'\s*,\s*'to_human'\s*\)\s*\)", table_sql):
        raise RuntimeError("schema v2 messages missing direction constraint")
    _validate_message_direction_constraint(conn)


def _validate_schema_version(conn: sqlite3.Connection, version: int) -> None:
    if version >= 1:
        _validate_v1_schema(conn)
    if version >= 2:
        _validate_v2_schema(conn)
    if version >= 3:
        _validate_v3_schema(conn)
    if version >= 4:
        _validate_v4_schema(conn)
    if version >= 5:
        _validate_v5_schema(conn)
    if version >= 6:
        _validate_v6_schema(conn)


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


def _migrate_v2(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            stream_id TEXT NOT NULL REFERENCES streams(id),
            direction TEXT NOT NULL CHECK (direction IN ('to_agent', 'to_human')),
            text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            consumed_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_stream_created ON messages(stream_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_stream_unconsumed ON messages(stream_id, consumed_at, created_at)")


def _migrate_v3(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "verdicts", "payload_json", "payload_json TEXT")


def _validate_v3_schema(conn: sqlite3.Connection) -> None:
    missing = {"payload_json"} - _column_names(conn, "verdicts")
    if missing:
        raise RuntimeError("schema v3 missing verdicts columns: payload_json")


def _migrate_v4(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "requests", "superseded_by", "superseded_by TEXT REFERENCES requests(id)")
    _add_column_if_missing(conn, "requests", "close_reason", "close_reason TEXT")


def _validate_v4_schema(conn: sqlite3.Connection) -> None:
    missing = {"superseded_by", "close_reason"} - _column_names(conn, "requests")
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise RuntimeError(f"schema v4 missing requests columns: {missing_list}")


def _migrate_v5(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "requests", "step", "step TEXT")
    _add_column_if_missing(conn, "requests", "purpose", "purpose TEXT")
    _add_column_if_missing(conn, "requests", "ask", "ask TEXT")


def _validate_v5_schema(conn: sqlite3.Connection) -> None:
    missing = {"step", "purpose", "ask"} - _column_names(conn, "requests")
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise RuntimeError(f"schema v5 missing requests columns: {missing_list}")


def _migrate_v6(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS journeys (
            slug TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            doc_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _validate_v6_schema(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'journeys'").fetchone() is None:
        raise RuntimeError("schema v6 missing journeys table")
    missing = {"slug", "title", "doc_json", "created_at", "updated_at"} - _column_names(conn, "journeys")
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise RuntimeError(f"schema v6 missing journeys columns: {missing_list}")


MIGRATIONS = [
    (1, _migrate_v1),
    (2, _migrate_v2),
    (3, _migrate_v3),
    (4, _migrate_v4),
    (5, _migrate_v5),
    (6, _migrate_v6),
]


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
            _validate_schema_version(conn, version)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        current = version
    if MIGRATIONS:
        _validate_schema_version(conn, MIGRATIONS[-1][0])


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


def _message_from_row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


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


def get_stream_by_id(stream_id: str) -> dict | None:
    conn = connect()
    with _lock:
        return _get_stream_by_id(conn, stream_id)


def get_stream_with_posts(slug: str) -> dict | None:
    conn = connect()
    with _lock:
        stream = _get_stream_by_slug(conn, slug)
        if stream is None:
            return None
        stream["posts"] = [
            _post_from_row(row)
            for row in conn.execute(
                "SELECT * FROM posts WHERE stream_id = ? ORDER BY created_at, rowid",
                (stream["id"],),
            ).fetchall()
        ]
        return stream


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
        raise StreamNotFoundError(f"stream not found: {stream_id}")
    if stream["closed_at"] is not None:
        raise StreamClosedError(f"stream is closed: {stream_id}")
    return stream


def _create_post(
    conn: sqlite3.Connection,
    stream_id: str,
    type: str,
    title: str,
    author: str,
    body: dict,
    created_at: str | None = None,
    post_id: str | None = None,
) -> dict:
    _require_open_stream(conn, stream_id)
    post_id = post_id or new_post_id()
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
    post_id: str | None = None,
) -> dict:
    conn = connect()
    with _lock:
        try:
            post = _create_post(conn, stream_id, type, title, author, body, created_at=created_at, post_id=post_id)
            conn.commit()
            return post
        except Exception:
            conn.rollback()
            raise


def create_post_for_stream(
    slug: str,
    type: str,
    title: str,
    author: str,
    body: dict,
    *,
    created_at: str | None = None,
    post_id: str | None = None,
) -> dict:
    conn = connect()
    with _lock:
        try:
            stream = _ensure_stream(conn, slug)
            post = _create_post(
                conn,
                stream["id"],
                type,
                title,
                author,
                body,
                created_at=created_at,
                post_id=post_id,
            )
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


def get_stream_post(slug: str, post_id: str) -> dict | None:
    conn = connect()
    with _lock:
        row = conn.execute(
            "SELECT posts.* FROM posts JOIN streams ON posts.stream_id = streams.id "
            "WHERE streams.slug = ? AND posts.id = ?",
            (slug, post_id),
        ).fetchone()
        return _post_from_row(row)


def _validate_message_direction(direction: str) -> None:
    if direction not in MESSAGE_DIRECTIONS:
        raise ValueError(f"invalid message direction: {direction}")


def _normalize_message_since(since: str) -> str:
    try:
        parsed = datetime.fromisoformat(since)
    except ValueError as exc:
        raise ValueError("since must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("since must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _get_message_by_id(conn: sqlite3.Connection, message_id: str) -> dict | None:
    return _message_from_row(conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone())


def _create_message(
    conn: sqlite3.Connection,
    stream_id: str,
    direction: str,
    text: str,
    *,
    created_at: str | None = None,
    message_id: str | None = None,
) -> dict:
    _validate_message_direction(direction)
    _require_open_stream(conn, stream_id)
    message_id = message_id or new_message_id()
    conn.execute(
        "INSERT INTO messages (id, stream_id, direction, text, created_at) VALUES (?, ?, ?, ?, ?)",
        (message_id, stream_id, direction, text, created_at or now_iso()),
    )
    message = _get_message_by_id(conn, message_id)
    assert message is not None
    return message


def create_message(
    stream_id: str,
    direction: str,
    text: str,
    *,
    created_at: str | None = None,
    message_id: str | None = None,
) -> dict:
    conn = connect()
    with _lock:
        try:
            message = _create_message(
                conn,
                stream_id,
                direction,
                text,
                created_at=created_at,
                message_id=message_id,
            )
            conn.commit()
            return message
        except Exception:
            conn.rollback()
            raise


def create_message_for_stream(
    slug: str,
    direction: str,
    text: str,
    *,
    created_at: str | None = None,
    message_id: str | None = None,
) -> dict:
    conn = connect()
    with _lock:
        try:
            stream = _ensure_stream(conn, slug)
            message = _create_message(
                conn,
                stream["id"],
                direction,
                text,
                created_at=created_at,
                message_id=message_id,
            )
            conn.commit()
            return message
        except Exception:
            conn.rollback()
            raise


def list_messages(
    stream_id: str,
    *,
    since: str | None = None,
    direction: str | None = None,
    unconsumed: bool = False,
) -> list[dict]:
    if direction is not None:
        _validate_message_direction(direction)
    if since is not None:
        since = _normalize_message_since(since)
    conn = connect()
    with _lock:
        clauses = ["stream_id = ?"]
        params: list = [stream_id]
        if since is not None:
            clauses.append("created_at > ?")
            params.append(since)
        if direction is not None:
            clauses.append("direction = ?")
            params.append(direction)
        if unconsumed:
            clauses.append("consumed_at IS NULL")
        rows = conn.execute(
            "SELECT * FROM messages WHERE " + " AND ".join(clauses) + " ORDER BY created_at, rowid",
            params,
        ).fetchall()
        return [_message_from_row(row) for row in rows]


def consume_message(message_id: str) -> dict:
    """Mark a message consumed once; repeated consumes are no-ops that return the original timestamp."""
    conn = connect()
    with _lock:
        try:
            message = _get_message_by_id(conn, message_id)
            if message is None:
                raise MessageNotFoundError(f"message not found: {message_id}")
            _require_open_stream(conn, message["stream_id"])
            if message["consumed_at"] is None:
                conn.execute(
                    "UPDATE messages SET consumed_at = ? WHERE id = ? AND consumed_at IS NULL",
                    (now_iso(), message_id),
                )
            conn.commit()
            message = _get_message_by_id(conn, message_id)
            assert message is not None
            return message
        except Exception:
            conn.rollback()
            raise


def _stream_slug_for_project(project: str | None) -> str:
    if not project or not project.strip():
        return "inbox"
    slug = re.sub(r"[^a-z0-9]+", "-", project.strip().lower()).strip("-")
    max_project_slug_length = STREAM_SLUG_MAX_LENGTH - len(PROJECT_STREAM_PREFIX)
    slug = slug or "project"
    if len(slug) > max_project_slug_length:
        digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:8]
        suffix = f"-{digest}"
        stem = slug[: max_project_slug_length - len(suffix)].strip("-") or "project"
        slug = f"{stem}{suffix}"
    return f"{PROJECT_STREAM_PREFIX}{slug}"


def create_request(
    req_id: str,
    title: str,
    project: str | None,
    kind: str,
    context_md: str | None,
    variants: list[dict],
    before_media_path: str | None = None,
    before_media_type: str | None = None,
    step: str | None = None,
    purpose: str | None = None,
    ask: str | None = None,
    stream: str | None = None,
) -> str:
    """variants: list of {media_path, media_type, caption, meta} in display order (1-based idx).

    When ``stream`` is given, that slug is the request's authoritative stream
    (created if missing); otherwise the stream is derived from ``project``.
    """
    conn = connect()
    created_at = now_iso()
    with _lock:
        try:
            slug = stream if (stream and stream.strip()) else _stream_slug_for_project(project)
            stream = _ensure_stream(conn, slug)
            conn.execute(
                "INSERT INTO requests "
                "(id, title, project, kind, status, context_md, created_at, stream_id, before_media_path, before_media_type, step, purpose, ask) "
                "VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    req_id,
                    title,
                    project,
                    kind,
                    context_md,
                    created_at,
                    stream["id"],
                    before_media_path,
                    before_media_type,
                    step,
                    purpose,
                    ask,
                ),
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
        variant_counts = {}
        request_ids = [r["id"] for r in rows]
        if request_ids:
            placeholders = ", ".join("?" for _ in request_ids)
            count_rows = conn.execute(
                "SELECT request_id, COUNT(*) AS variant_count FROM variants "
                f"WHERE request_id IN ({placeholders}) GROUP BY request_id",
                request_ids,
            ).fetchall()
            variant_counts = {r["request_id"]: r["variant_count"] for r in count_rows}
        out = []
        for r in rows:
            d = dict(r)
            d["variant_count"] = variant_counts.get(d["id"], 0)
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
    d["payload"] = json.loads(d.pop("payload_json")) if d.get("payload_json") else None
    return d


def variant_indices(req_id: str) -> set[int]:
    conn = connect()
    with _lock:
        rows = conn.execute("SELECT idx FROM variants WHERE request_id = ?", (req_id,)).fetchall()
    return {r["idx"] for r in rows}


def record_verdict(
    req_id: str,
    selected: list[int],
    ratings: dict | None,
    comment: str | None,
    payload: object | None = None,
) -> dict:
    """Insert a new verdict revision and mark the request decided. Latest verdict wins."""
    conn = connect()
    with _lock:
        request = conn.execute("SELECT stream_id, status FROM requests WHERE id = ?", (req_id,)).fetchone()
        if request is not None and request["status"] in TERMINAL_STATUSES:
            raise RequestTerminalError(f"request already {request['status']}: {req_id}")
        if request is not None and request["stream_id"] is not None:
            _require_open_stream(conn, request["stream_id"])
        conn.execute(
            "INSERT INTO verdicts (request_id, selected_indices, ratings_json, comment, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                req_id,
                json.dumps(selected),
                json.dumps(ratings) if ratings is not None else None,
                comment,
                json.dumps(payload) if payload is not None else None,
                now_iso(),
            ),
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


TERMINAL_STATUSES = ("closed", "superseded")


def count_verdicts(req_id: str) -> int:
    conn = connect()
    with _lock:
        return conn.execute("SELECT COUNT(*) FROM verdicts WHERE request_id = ?", (req_id,)).fetchone()[0]


def close_request(req_id: str, reason: str) -> dict:
    """Retire a request with a reason and no fabricated verdict. Terminal states are immutable."""
    conn = connect()
    with _lock:
        try:
            row = conn.execute("SELECT status FROM requests WHERE id = ?", (req_id,)).fetchone()
            if row is None:
                raise RequestNotFoundError(f"request not found: {req_id}")
            if row["status"] in TERMINAL_STATUSES:
                raise RequestTerminalError(f"request already {row['status']}: {req_id}")
            conn.execute(
                "UPDATE requests SET status = 'closed', close_reason = ? WHERE id = ?",
                (reason, req_id),
            )
            conn.commit()
            request = _get_request(conn, req_id)
            assert request is not None
            return request
        except Exception:
            conn.rollback()
            raise


def supersede_request(req_id: str, successor_id: str) -> dict:
    """Mark a request superseded by a live successor. Terminal states are immutable."""
    conn = connect()
    with _lock:
        try:
            row = conn.execute("SELECT status FROM requests WHERE id = ?", (req_id,)).fetchone()
            if row is None:
                raise RequestNotFoundError(f"request not found: {req_id}")
            if req_id == successor_id:
                raise ValueError(f"request cannot supersede itself: {req_id}")
            if row["status"] in TERMINAL_STATUSES:
                raise RequestTerminalError(f"request already {row['status']}: {req_id}")
            successor = conn.execute("SELECT id, status FROM requests WHERE id = ?", (successor_id,)).fetchone()
            if successor is None:
                raise SuccessorNotFoundError(f"successor not found: {successor_id}")
            if successor["status"] in TERMINAL_STATUSES:
                raise ValueError(f"successor is not live: {successor_id} (status {successor['status']})")
            conn.execute(
                "UPDATE requests SET status = 'superseded', superseded_by = ? WHERE id = ?",
                (successor_id, req_id),
            )
            conn.commit()
            request = _get_request(conn, req_id)
            assert request is not None
            return request
        except Exception:
            conn.rollback()
            raise


def _journey_from_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    journey = dict(row)
    journey["doc"] = json.loads(journey.pop("doc_json"))
    return journey


def _get_journey(conn: sqlite3.Connection, slug: str) -> dict | None:
    return _journey_from_row(conn.execute("SELECT * FROM journeys WHERE slug = ?", (slug,)).fetchone())


def upsert_journey(slug: str, title: str, doc: dict, *, created_at: str | None = None, updated_at: str | None = None) -> dict:
    """Update-in-place: one row per slug. Re-posting a slug replaces title+doc and
    bumps updated_at while preserving the original created_at."""
    conn = connect()
    now = updated_at or now_iso()
    created = created_at or now
    with _lock:
        try:
            conn.execute(
                "INSERT INTO journeys (slug, title, doc_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(slug) DO UPDATE SET "
                "title = excluded.title, doc_json = excluded.doc_json, updated_at = excluded.updated_at",
                (slug, title, json.dumps(doc), created, now),
            )
            conn.commit()
            journey = _get_journey(conn, slug)
            assert journey is not None
            return journey
        except Exception:
            conn.rollback()
            raise


def get_journey(slug: str) -> dict | None:
    conn = connect()
    with _lock:
        return _get_journey(conn, slug)


def list_journeys() -> list[dict]:
    conn = connect()
    with _lock:
        rows = conn.execute(
            "SELECT slug, title, doc_json, updated_at FROM journeys ORDER BY updated_at DESC, slug"
        ).fetchall()
    out = []
    for row in rows:
        doc = json.loads(row["doc_json"])
        steps = doc.get("steps") if isinstance(doc, dict) else None
        out.append(
            {
                "slug": row["slug"],
                "title": row["title"],
                "step_count": len(steps) if isinstance(steps, list) else 0,
                "updated_at": row["updated_at"],
            }
        )
    return out
