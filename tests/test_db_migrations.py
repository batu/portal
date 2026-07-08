import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from gallery import config, db


OLD_SCHEMA = """
CREATE TABLE requests (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    project TEXT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    context_md TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE TABLE variants (
    request_id TEXT NOT NULL REFERENCES requests(id),
    idx INTEGER NOT NULL,
    media_path TEXT NOT NULL,
    media_type TEXT NOT NULL,
    caption TEXT,
    meta_json TEXT,
    PRIMARY KEY (request_id, idx)
);

CREATE TABLE verdicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL REFERENCES requests(id),
    selected_indices TEXT NOT NULL,
    ratings_json TEXT,
    comment TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_requests_status ON requests(status);
CREATE INDEX idx_requests_project ON requests(project);
CREATE INDEX idx_verdicts_request ON verdicts(request_id);
"""


def _raw_conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def _column_names(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _user_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _rows(conn, sql):
    return [dict(row) for row in conn.execute(sql).fetchall()]


def _legacy_snapshot(path):
    conn = _raw_conn(path)
    try:
        return {
            "requests": _rows(
                conn,
                "SELECT id, title, project, kind, status, context_md, created_at, decided_at "
                "FROM requests ORDER BY id",
            ),
            "variants": _rows(
                conn,
                "SELECT request_id, idx, media_path, media_type, caption, meta_json "
                "FROM variants ORDER BY request_id, idx",
            ),
            "verdicts": _rows(
                conn,
                "SELECT id, request_id, selected_indices, ratings_json, comment, created_at "
                "FROM verdicts ORDER BY id",
            ),
        }
    finally:
        conn.close()


def _create_legacy_db(path):
    conn = _raw_conn(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO requests (id, title, project, kind, status, context_md, created_at, decided_at) "
        "VALUES ('req_old', 'Old request', 'legacy/project', 'pick-one', 'decided', 'old **ctx**', "
        "'2026-07-08T10:00:00+00:00', '2026-07-08T10:05:00+00:00')"
    )
    conn.execute(
        "INSERT INTO variants (request_id, idx, media_path, media_type, caption, meta_json) "
        "VALUES ('req_old', 1, '01_a.png', 'image', 'A', '{\"score\": 1}')"
    )
    conn.execute(
        "INSERT INTO variants (request_id, idx, media_path, media_type, caption, meta_json) "
        "VALUES ('req_old', 2, '02_b.png', 'image', 'B', NULL)"
    )
    conn.execute(
        "INSERT INTO verdicts (request_id, selected_indices, ratings_json, comment, created_at) "
        "VALUES ('req_old', '[1]', NULL, 'first', '2026-07-08T10:03:00+00:00')"
    )
    conn.execute(
        "INSERT INTO verdicts (request_id, selected_indices, ratings_json, comment, created_at) "
        "VALUES ('req_old', '[2]', '{\"2\": 5}', 'latest', '2026-07-08T10:05:00+00:00')"
    )
    conn.commit()
    conn.close()


def _variant():
    return {"media_path": "01_a.png", "media_type": "image", "caption": "A", "meta": {"score": 1}}


def test_fresh_db_has_portal_schema_v1(data_dir):
    conn = db.connect()

    assert _user_version(conn) == 1
    assert {"requests", "variants", "verdicts", "streams", "posts"} <= _table_names(conn)
    assert "messages" not in _table_names(conn)
    assert {"stream_id", "before_media_path", "before_media_type"} <= _column_names(conn, "requests")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    request_fks = conn.execute("PRAGMA foreign_key_list(requests)").fetchall()
    post_fks = conn.execute("PRAGMA foreign_key_list(posts)").fetchall()
    assert any(
        row["from"] == "stream_id" and row["table"] == "streams" and row["on_delete"] == "NO ACTION"
        for row in request_fks
    )
    assert any(
        row["from"] == "stream_id" and row["table"] == "streams" and row["on_delete"] == "NO ACTION"
        for row in post_fks
    )


def test_legacy_db_upgrade_preserves_existing_rows(data_dir):
    path = config.db_path()
    _create_legacy_db(path)
    legacy_rows = _legacy_snapshot(path)

    conn = db.connect()

    assert _user_version(conn) == 1
    assert {"streams", "posts"} <= _table_names(conn)
    assert {"stream_id", "before_media_path", "before_media_type"} <= _column_names(conn, "requests")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert _rows(
        conn,
        "SELECT id, title, project, kind, status, context_md, created_at, decided_at "
        "FROM requests ORDER BY id",
    ) == legacy_rows["requests"]
    assert _rows(
        conn,
        "SELECT request_id, idx, media_path, media_type, caption, meta_json "
        "FROM variants ORDER BY request_id, idx",
    ) == legacy_rows["variants"]
    assert _rows(
        conn,
        "SELECT id, request_id, selected_indices, ratings_json, comment, created_at "
        "FROM verdicts ORDER BY id",
    ) == legacy_rows["verdicts"]

    request = db.get_request("req_old")
    assert request["title"] == "Old request"
    assert request["project"] == "legacy/project"
    assert request["stream_id"] is None
    assert request["before_media_path"] is None
    assert request["variants"][0]["meta"] == {"score": 1}
    assert request["variants"][1]["meta"] is None
    assert request["verdict"]["selected"] == [2]
    assert request["verdict"]["ratings"] == {"2": 5}
    assert request["verdict"]["comment"] == "latest"
    assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0


def test_reconnecting_migrated_db_is_noop(data_dir):
    conn = db.connect()
    db.create_stream("stable", "session", "Stable")
    before = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("requests", "variants", "verdicts", "streams", "posts")
    }

    db.reset_connection()
    conn = db.connect()

    after = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("requests", "variants", "verdicts", "streams", "posts")
    }
    assert _user_version(conn) == 1
    assert after == before


def test_partial_v1_db_completes_migration(data_dir):
    path = config.db_path()
    _create_legacy_db(path)
    conn = _raw_conn(path)
    conn.execute(
        "CREATE TABLE streams ("
        "id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, "
        "title TEXT NOT NULL, created_at TEXT NOT NULL, closed_at TEXT)"
    )
    conn.execute("ALTER TABLE requests ADD COLUMN stream_id TEXT REFERENCES streams(id)")
    conn.commit()
    conn.close()

    conn = db.connect()

    assert _user_version(conn) == 1
    assert {"stream_id", "before_media_path", "before_media_type"} <= _column_names(conn, "requests")
    assert "posts" in _table_names(conn)
    assert db.get_request("req_old")["verdict"]["comment"] == "latest"


def test_migration_rejects_malformed_existing_portal_tables(data_dir):
    path = config.db_path()
    _create_legacy_db(path)
    conn = _raw_conn(path)
    conn.execute(
        "CREATE TABLE posts ("
        "id TEXT PRIMARY KEY, stream_id TEXT NOT NULL REFERENCES streams(id), "
        "type TEXT NOT NULL, title TEXT NOT NULL, author TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="schema v1 missing posts columns: body_json"):
        db.connect()

    assert db._conn is None
    raw = _raw_conn(path)
    assert _user_version(raw) == 0
    raw.close()


def test_user_version_one_requires_v1_schema_shape(data_dir):
    path = config.db_path()
    _create_legacy_db(path)
    conn = _raw_conn(path)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="schema v1 missing"):
        db.connect()

    assert db._conn is None


def test_failed_migration_rolls_back_and_connect_can_retry(data_dir, monkeypatch):
    original_migrations = db.MIGRATIONS

    def failing_migration(conn):
        db._migrate_v1(conn)
        raise RuntimeError("boom")

    monkeypatch.setattr(db, "MIGRATIONS", [(1, failing_migration)])
    with pytest.raises(RuntimeError, match="boom"):
        db.connect()

    assert db._conn is None
    raw = _raw_conn(config.db_path())
    assert _user_version(raw) == 0
    assert "streams" not in _table_names(raw)
    raw.close()

    monkeypatch.setattr(db, "MIGRATIONS", original_migrations)
    conn = db.connect()
    assert _user_version(conn) == 1
    assert {"streams", "posts"} <= _table_names(conn)


def test_concurrent_first_connect_is_serialized(data_dir, monkeypatch):
    calls = 0
    original_migration = db.MIGRATIONS[0][1]

    def slow_migration(conn):
        nonlocal calls
        calls += 1
        time.sleep(0.02)
        original_migration(conn)

    monkeypatch.setattr(db, "MIGRATIONS", [(1, slow_migration)])

    with ThreadPoolExecutor(max_workers=8) as pool:
        conns = list(pool.map(lambda _: db.connect(), range(8)))

    assert len({id(conn) for conn in conns}) == 1
    assert calls == 1
    assert _user_version(conns[0]) == 1


def test_stream_helpers_create_ensure_and_close(data_dir):
    stream = db.create_stream("alpha", "session", "Alpha")
    assert stream["id"].startswith("s_")
    assert stream["slug"] == "alpha"
    assert stream["kind"] == "session"
    assert stream["title"] == "Alpha"
    assert stream["closed_at"] is None

    assert db.get_stream("alpha")["id"] == stream["id"]
    with pytest.raises(sqlite3.IntegrityError):
        db.create_stream("alpha", "session", "Duplicate")

    ensured = db.ensure_stream("alpha")
    assert ensured["id"] == stream["id"]
    assert ensured["title"] == "Alpha"
    assert ensured["kind"] == "session"

    created = db.ensure_stream("new-session")
    assert created["slug"] == "new-session"
    assert created["kind"] == "session"
    assert created["title"] == "new-session"

    closed = db.close_stream("alpha")
    assert closed["closed_at"] is not None
    assert db.get_stream("alpha")["closed_at"] == closed["closed_at"]

    with pytest.raises(ValueError, match="stream not found"):
        db.close_stream("missing")


def test_post_helpers_round_trip_and_reject_closed_or_missing_stream(data_dir):
    stream = db.create_stream("posts", "session", "Posts")
    first = db.create_post(
        stream["id"],
        "report",
        "Report",
        "codex",
        {"path": "grid.html", "scores": [1, 2]},
        created_at="2026-07-08T10:00:00+00:00",
    )
    second = db.create_post(
        stream["id"],
        "decision",
        "Decision",
        "gallery",
        {"request_id": "req_abc123"},
        created_at="2026-07-08T10:01:00+00:00",
    )

    assert first["id"].startswith("p_")
    assert first["stream_id"] == stream["id"]
    assert first["type"] == "report"
    assert first["title"] == "Report"
    assert first["author"] == "codex"
    assert first["created_at"] == "2026-07-08T10:00:00+00:00"
    assert first["body"] == {"path": "grid.html", "scores": [1, 2]}
    assert db.get_post(first["id"]) == first
    assert [post["id"] for post in db.list_posts(stream["id"])] == [first["id"], second["id"]]

    with pytest.raises(ValueError, match="stream not found"):
        db.create_post("s_missing", "report", "Missing", "codex", {})

    db.close_stream("posts")
    with pytest.raises(ValueError, match="stream is closed"):
        db.create_post(stream["id"], "report", "Closed", "codex", {})


def test_create_request_dual_writes_to_project_and_inbox_streams(data_dir):
    req_id = "req_project"
    db.create_request(
        req_id,
        "Pick a crop",
        "fabrika/find_the_dog",
        "pick-one",
        "**ctx**",
        [_variant()],
    )

    stream_slug = db._stream_slug_for_project("fabrika/find_the_dog")
    assert stream_slug.startswith("proj-fabrika-find-the-dog-")
    stream = db.get_stream(stream_slug)
    request = db.get_request(req_id)
    posts = db.list_posts(stream["id"])
    assert request["stream_id"] == stream["id"]
    assert request["before_media_path"] is None
    assert request["before_media_type"] is None
    assert db.variant_indices(req_id) == {1}
    assert len(posts) == 1
    assert posts[0]["type"] == "decision"
    assert posts[0]["title"] == "Pick a crop"
    assert posts[0]["body"] == {"request_id": req_id}

    inbox_id = "req_inbox"
    db.create_request(inbox_id, "Inbox", None, "approve", None, [_variant()])
    inbox = db.get_stream("inbox")
    assert db.get_request(inbox_id)["stream_id"] == inbox["id"]
    assert db.list_posts(inbox["id"])[0]["body"] == {"request_id": inbox_id}

    verdict = db.record_verdict(req_id, [1], None, "yes")
    assert verdict["selected"] == [1]
    assert db.get_request(req_id)["verdict"]["comment"] == "yes"


def test_project_stream_slugs_are_collision_resistant(data_dir):
    db.create_request("req_slash", "Slash", "a/b", "pick-one", None, [_variant()])
    db.create_request("req_space", "Space", "a b", "pick-one", None, [_variant()])

    slash = db.get_stream(db._stream_slug_for_project("a/b"))
    space = db.get_stream(db._stream_slug_for_project("a b"))
    assert slash["slug"].startswith("proj-a-b-")
    assert space["slug"].startswith("proj-a-b-")
    assert len(slash["slug"].rsplit("-", 1)[1]) == 16
    assert len(space["slug"].rsplit("-", 1)[1]) == 16
    assert slash["id"] != space["id"]
    assert db.get_request("req_slash")["stream_id"] == slash["id"]
    assert db.get_request("req_space")["stream_id"] == space["id"]


def test_create_request_rejects_closed_legacy_stream(data_dir):
    db.create_request("req_first", "First", "closed/project", "pick-one", None, [_variant()])
    stream = db.get_stream(db._stream_slug_for_project("closed/project"))
    db.close_stream(stream["slug"])

    with pytest.raises(ValueError, match="stream is closed"):
        db.create_request("req_second", "Second", "closed/project", "pick-one", None, [_variant()])

    assert db.get_request("req_second") is None
    assert db.list_posts(stream["id"])[0]["body"] == {"request_id": "req_first"}


def test_record_verdict_rejects_closed_request_stream(data_dir):
    db.create_request("req_closed_verdict", "Closed verdict", "closed/verdict", "pick-one", None, [_variant()])
    stream = db.get_stream(db._stream_slug_for_project("closed/verdict"))
    db.close_stream(stream["slug"])

    with pytest.raises(ValueError, match="stream is closed"):
        db.record_verdict("req_closed_verdict", [1], None, "too late")

    request = db.get_request("req_closed_verdict")
    assert request["status"] == "open"
    assert request["verdict"] is None


def test_create_request_rolls_back_dual_write_failure(data_dir, monkeypatch):
    original_create_post = db._create_post

    def fail_create_post(*_args, **_kwargs):
        original_create_post(*_args, **_kwargs)
        raise RuntimeError("post failure")

    monkeypatch.setattr(db, "_create_post", fail_create_post)

    with pytest.raises(RuntimeError, match="post failure"):
        db.create_request("req_fail", "Fail", "project/fail", "pick-one", None, [_variant()])

    conn = db.connect()
    assert db.get_request("req_fail") is None
    assert db.get_stream(db._stream_slug_for_project("project/fail")) is None
    assert conn.execute("SELECT COUNT(*) FROM variants WHERE request_id = 'req_fail'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0


def test_public_reads_do_not_observe_uncommitted_rows_before_rollback(data_dir, monkeypatch):
    entered_post_insert = threading.Event()
    release_post_insert = threading.Event()

    def fail_create_post(*_args, **_kwargs):
        entered_post_insert.set()
        assert release_post_insert.wait(timeout=1)
        raise RuntimeError("post failure")

    monkeypatch.setattr(db, "_create_post", fail_create_post)

    with ThreadPoolExecutor(max_workers=2) as pool:
        write = pool.submit(
            db.create_request,
            "req_uncommitted",
            "Uncommitted",
            "race/project",
            "pick-one",
            None,
            [_variant()],
        )
        assert entered_post_insert.wait(timeout=1)

        read = pool.submit(db.get_request, "req_uncommitted")
        time.sleep(0.05)
        assert not read.done()

        release_post_insert.set()
        with pytest.raises(RuntimeError, match="post failure"):
            write.result(timeout=1)
        assert read.result(timeout=1) is None
