import json
import tomllib
import urllib.error
from pathlib import Path

import pytest

from gallery import cli, db


def _record_urlopen_timeouts(monkeypatch):
    observed_timeouts = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(_request, timeout):
        observed_timeouts.append(timeout)
        return Response()

    monkeypatch.setattr(cli.client.urllib.request, "urlopen", fake_urlopen)
    return observed_timeouts


def _stub_open_stream(monkeypatch):
    monkeypatch.setattr(cli.client, "get_stream", lambda *_args, **_kwargs: {"closed_at": None})


def test_pyproject_exposes_portal_and_gallery_scripts():
    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())

    assert pyproject["project"]["scripts"]["portal"] == "gallery.cli:main"
    assert pyproject["project"]["scripts"]["gallery"] == "gallery.cli:main"


def test_legacy_stream_slug_matches_db_bounded_project_slug():
    project = "ab/" * 80

    slug = cli._legacy_stream_slug(project)

    assert slug == db._stream_slug_for_project(project)
    assert len(slug) <= db.STREAM_SLUG_MAX_LENGTH
    assert cli.STREAM_SLUG_RE.fullmatch(slug)


def test_legacy_stream_slug_hashes_overlong_project_tail():
    common_prefix = "ab/" * 80
    first = cli._legacy_stream_slug(f"{common_prefix}first")
    second = cli._legacy_stream_slug(f"{common_prefix}second")

    assert first == db._stream_slug_for_project(f"{common_prefix}first")
    assert second == db._stream_slug_for_project(f"{common_prefix}second")
    assert first != second
    assert len(first) <= db.STREAM_SLUG_MAX_LENGTH
    assert len(second) <= db.STREAM_SLUG_MAX_LENGTH
    assert cli.STREAM_SLUG_RE.fullmatch(first)
    assert cli.STREAM_SLUG_RE.fullmatch(second)


def test_client_network_error_becomes_gallery_client_error(monkeypatch):
    def fail_urlopen(_request, timeout):
        raise urllib.error.URLError("server down")

    monkeypatch.setattr(cli.client.urllib.request, "urlopen", fail_urlopen)

    with pytest.raises(cli.client.GalleryClientError) as exc:
        cli.client.get_json("http://gallery", "tok", "/api/health")

    assert exc.value.status == 0
    assert "server down" in exc.value.message


def test_game_publish_uses_a_timeout_sized_for_large_release_uploads(monkeypatch, tmp_path):
    observed_timeouts = _record_urlopen_timeouts(monkeypatch)
    artifact = tmp_path / "game.zip"
    video = tmp_path / "game.mp4"
    poster = tmp_path / "poster.jpg"
    for path in (artifact, video, poster):
        path.write_bytes(b"release")

    cli.client.publish_game_build(
        "http://gallery",
        "tok",
        "find-the-bird",
        title="Find the Bird",
        version="2026.08.06-2",
        changelog="- Fixed preview boot",
        artifact=artifact,
        video=video,
        poster=poster,
    )

    assert observed_timeouts == [600]


def test_regular_multipart_upload_keeps_the_default_timeout(monkeypatch, tmp_path):
    observed_timeouts = _record_urlopen_timeouts(monkeypatch)
    attachment = tmp_path / "report.html"
    attachment.write_text("<html></html>")

    cli.client.post_multipart(
        "http://gallery",
        "tok",
        "/api/streams/alpha/posts",
        {"text": "Release report"},
        [attachment],
    )

    assert observed_timeouts == [30]


def test_client_malformed_url_becomes_gallery_client_error():
    with pytest.raises(cli.client.GalleryClientError) as exc:
        cli.client.get_json("http://[::1", "tok", "/api/health")

    assert exc.value.status == 0
    assert "invalid URL" in exc.value.message


def test_no_command_prints_help_and_exits(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["gallery"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert "usage" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("binary", ["portal", "gallery"])
def test_help_aliases_list_portal_verbs(monkeypatch, capsys, binary):
    monkeypatch.setattr("sys.argv", [binary, "--help"])
    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "usage: portal" in out
    for verb in ["init", "post", "wait", "status", "list", "serve", "stream", "report", "ask", "pull", "trello-watch", "game"]:
        assert verb in out


def test_post_requires_title_and_kind(monkeypatch):
    monkeypatch.setattr("sys.argv", ["gallery", "post", "file.png"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2  # argparse error: missing required args


def test_post_rejects_invalid_kind(monkeypatch):
    monkeypatch.setattr("sys.argv", ["gallery", "post", "--title", "t", "--kind", "bogus", "file.png"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2  # argparse choices validation


def test_post_missing_file_exits_1(monkeypatch, tmp_path):
    monkeypatch.setenv("GALLERY_URL", "http://example.invalid")
    monkeypatch.setenv("GALLERY_TOKEN", "x")
    missing = tmp_path / "nope.png"
    monkeypatch.setattr("sys.argv", ["gallery", "post", "--title", "t", "--kind", "pick-one", str(missing)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1


def test_old_style_gallery_post_keeps_request_payload_and_no_stream_attach(monkeypatch, tmp_path, capsys):
    upload = tmp_path / "variant.png"
    upload.write_bytes(b"png")
    calls = []

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))

    def fake_post_multipart(base_url, token, path, fields, files):
        calls.append(
            {
                "base_url": base_url,
                "token": token,
                "path": path,
                "fields": fields,
                "files": files,
            }
        )
        return {"id": "req_123", "variant_count": 1}

    monkeypatch.setattr(cli.client, "post_multipart", fake_post_multipart)
    monkeypatch.setattr(
        cli.client,
        "create_stream_post",
        lambda *args, **kwargs: pytest.fail("old post must not create a stream post"),
    )
    monkeypatch.setattr("sys.argv", ["gallery", "post", "--title", "t", "--kind", "pick-one", str(upload)])

    cli.main()

    assert calls == [
        {
            "base_url": "http://gallery",
            "token": "tok",
            "path": "/api/requests",
            "fields": {
                "title": "t",
                "project": None,
                "kind": "pick-one",
                "context": None,
                "manifest": None,
                "step": None,
                "purpose": None,
                "ask": None,
                "stream": None,
                "author": None,
            },
            "files": [upload],
        }
    ]
    assert json.loads(capsys.readouterr().out) == {
        "id": "req_123",
        "variant_count": 1,
        "chain_url": "http://gallery/c/req_123",
    }


def test_post_before_upload_uses_named_before_field(monkeypatch, tmp_path):
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    before.write_bytes(b"before")
    after.write_bytes(b"after")
    captured = {}

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))

    def fake_post_multipart(_base_url, _token, _path, _fields, files):
        captured["files"] = files
        return {"id": "req_before"}

    monkeypatch.setattr(cli.client, "post_multipart", fake_post_multipart)
    monkeypatch.setattr("sys.argv", [
        "portal",
        "post",
        "--before",
        str(before),
        "--title",
        "t",
        "--kind",
        "before-after",
        str(after),
    ])

    cli.main()

    assert captured["files"] == [("before", before), after]


def test_post_missing_before_file_exits_1(monkeypatch, tmp_path):
    monkeypatch.setenv("GALLERY_URL", "http://example.invalid")
    monkeypatch.setenv("GALLERY_TOKEN", "x")
    upload = tmp_path / "variant.png"
    upload.write_bytes(b"png")
    missing = tmp_path / "missing.png"
    monkeypatch.setattr("sys.argv", [
        "portal",
        "post",
        "--before",
        str(missing),
        "--title",
        "t",
        "--kind",
        "before-after",
        str(upload),
    ])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1


def test_post_stream_forwards_stream_field_without_second_post(monkeypatch, tmp_path, capsys):
    upload = tmp_path / "variant.png"
    upload.write_bytes(b"png")
    request_posts = []

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    _stub_open_stream(monkeypatch)

    def fake_post_multipart(base_url, token, path, fields, files):
        request_posts.append(
            {
                "base_url": base_url,
                "token": token,
                "path": path,
                "fields": fields,
                "files": files,
            }
        )
        return {"id": "req_123", "variant_count": 1}

    monkeypatch.setattr(cli.client, "post_multipart", fake_post_multipart)
    monkeypatch.setattr(
        cli.client,
        "create_stream_post",
        lambda *args, **kwargs: pytest.fail("owning stream is set server-side; no second stream post"),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "post", "--stream", "alpha", "--title", "t", "--kind", "pick-one", str(upload)],
    )

    cli.main()

    assert request_posts == [
        {
            "base_url": "http://gallery",
            "token": "tok",
            "path": "/api/requests",
            "fields": {
                "title": "t",
                "project": None,
                "kind": "pick-one",
                "context": None,
                "manifest": None,
                "step": None,
                "purpose": None,
                "ask": None,
                "stream": "alpha",
                "author": None,
            },
            "files": [upload],
        }
    ]
    assert json.loads(capsys.readouterr().out) == {
        "id": "req_123",
        "variant_count": 1,
        "chain_url": "http://gallery/c/req_123",
    }


def test_post_stream_with_before_keeps_before_out_of_candidates(monkeypatch, tmp_path):
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    before.write_bytes(b"before")
    after.write_bytes(b"after")
    captured = {}

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    _stub_open_stream(monkeypatch)

    def fake_post_multipart(_base_url, _token, _path, _fields, files):
        captured["files"] = files
        return {"id": "req_123"}

    monkeypatch.setattr(cli.client, "post_multipart", fake_post_multipart)
    monkeypatch.setattr(
        cli.client,
        "create_stream_post",
        lambda *args, **kwargs: pytest.fail("owning stream is set server-side; no second stream post"),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "portal",
            "post",
            "--stream",
            "alpha",
            "--before",
            str(before),
            "--title",
            "t",
            "--kind",
            "before-after",
            str(after),
        ],
    )

    cli.main()

    assert captured["files"] == [("before", before), after]


@pytest.mark.parametrize("stream", ["", "Alpha", "bad slug", "alpha-"])
def test_post_invalid_stream_slug_rejected_before_request(monkeypatch, tmp_path, stream):
    upload = tmp_path / "variant.png"
    upload.write_bytes(b"png")

    monkeypatch.setattr(
        cli.client,
        "post_multipart",
        lambda *args, **kwargs: pytest.fail("invalid stream slug must be rejected before request creation"),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "post", "--stream", stream, "--title", "t", "--kind", "pick-one", str(upload)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2


def test_post_closed_stream_rejected_before_request(monkeypatch, tmp_path, capsys):
    upload = tmp_path / "variant.png"
    upload.write_bytes(b"png")

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(cli.client, "get_stream", lambda *_args, **_kwargs: {"closed_at": "now"})
    monkeypatch.setattr(
        cli.client,
        "post_multipart",
        lambda *args, **kwargs: pytest.fail("closed stream must be rejected before request creation"),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "post", "--stream", "alpha", "--title", "t", "--kind", "pick-one", str(upload)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert "error: stream is closed: alpha" in capsys.readouterr().err


def test_post_missing_stream_preflight_allows_auto_create(monkeypatch, tmp_path):
    upload = tmp_path / "variant.png"
    upload.write_bytes(b"png")
    events = []
    request_posts = []

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))

    def missing_stream(*_args, **_kwargs):
        events.append("get_stream")
        raise cli.client.GalleryClientError(404, "stream not found")

    monkeypatch.setattr(cli.client, "get_stream", missing_stream)
    monkeypatch.setattr(
        cli.client,
        "post_multipart",
        lambda base_url, token, path, fields, files: events.append("post_multipart")
        or request_posts.append((base_url, token, path, fields, files))
        or {"id": "req_123"},
    )
    monkeypatch.setattr(
        cli.client,
        "create_stream_post",
        lambda *args, **kwargs: pytest.fail("owning stream is set server-side; no second stream post"),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "post", "--stream", "alpha", "--title", "t", "--kind", "pick-one", str(upload)],
    )

    cli.main()

    assert len(request_posts) == 1
    assert request_posts[0][3]["stream"] == "alpha"
    assert events == ["get_stream", "post_multipart"]


def test_post_before_cannot_also_be_candidate_via_glob(monkeypatch, tmp_path, capsys):
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    before.write_bytes(b"before")
    after.write_bytes(b"after")

    monkeypatch.setenv("GALLERY_URL", "http://example.invalid")
    monkeypatch.setenv("GALLERY_TOKEN", "x")
    monkeypatch.setattr(
        cli.client,
        "post_multipart",
        lambda *args, **kwargs: pytest.fail("duplicate before/candidate file must be rejected before posting"),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "portal",
            "post",
            "--before",
            str(before),
            "--title",
            "t",
            "--kind",
            "before-after",
            str(tmp_path / "*.png"),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert "error: before image must not also be a candidate file" in capsys.readouterr().err


def test_client_upsert_journey_explicit_title_wins_over_doc_title(monkeypatch):
    captured = {}

    def fake_request(method, url, headers, data=None):
        captured["data"] = json.loads(data.decode("utf-8"))
        return {}

    monkeypatch.setattr(cli.client, "_request", fake_request)

    cli.client.upsert_journey("http://gallery", "tok", "wool-crush", "Wool Crush", {"title": "sneaky", "steps": []})

    assert captured["data"] == {"title": "Wool Crush", "steps": []}


def test_client_get_and_list_journeys_send_bearer_gets(monkeypatch):
    captured = []

    def fake_request(method, url, headers, data=None):
        captured.append((method, url, headers.get("Authorization"), data))
        return {"slug": "wool-crush"} if "/api/journeys/" in url else [{"slug": "wool-crush"}]

    monkeypatch.setattr(cli.client, "_request", fake_request)

    assert cli.client.get_journey("http://gallery", "tok", "wool-crush") == {"slug": "wool-crush"}
    assert cli.client.list_journeys("http://gallery", "tok") == [{"slug": "wool-crush"}]
    assert captured == [
        ("GET", "http://gallery/api/journeys/wool-crush", "Bearer tok", None),
        ("GET", "http://gallery/api/journeys", "Bearer tok", None),
    ]


def test_client_upsert_journey_puts_merged_title_and_doc(monkeypatch):
    captured = {}

    def fake_request(method, url, headers, data=None):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["data"] = json.loads(data.decode("utf-8"))
        return {}

    monkeypatch.setattr(cli.client, "_request", fake_request)

    cli.client.upsert_journey("http://gallery", "tok", "wool-crush", "Wool Crush", {"steps": [{"title": "x"}]})

    assert captured["method"] == "PUT"
    assert captured["url"] == "http://gallery/api/journeys/wool-crush"
    assert captured["headers"]["Authorization"] == "Bearer tok"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["data"] == {"title": "Wool Crush", "steps": [{"title": "x"}]}


def test_journey_post_loads_doc_and_calls_client(monkeypatch, tmp_path, capsys):
    doc = tmp_path / "journey.json"
    doc.write_text(json.dumps({"steps": [{"title": "Watch"}, {"title": "Pick"}]}))
    calls = []

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))

    def fake_upsert(base_url, token, slug, title, doc_obj):
        calls.append((base_url, token, slug, title, doc_obj))
        return {"slug": slug, "title": title, "doc": doc_obj}

    monkeypatch.setattr(cli.client, "upsert_journey", fake_upsert)
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "journey", "post", "--slug", "wool-crush", "--title", "Wool Crush", "--doc", str(doc)],
    )

    cli.main()

    assert calls == [
        ("http://gallery", "tok", "wool-crush", "Wool Crush", {"steps": [{"title": "Watch"}, {"title": "Pick"}]})
    ]
    assert json.loads(capsys.readouterr().out)["slug"] == "wool-crush"


def test_journey_post_rejects_invalid_slug(monkeypatch, tmp_path):
    doc = tmp_path / "journey.json"
    doc.write_text(json.dumps({"steps": []}))
    monkeypatch.setattr(
        cli.client, "upsert_journey", lambda *a, **k: pytest.fail("invalid slug must be rejected by argparse")
    )
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "journey", "post", "--slug", "Bad Slug", "--title", "T", "--doc", str(doc)],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_journey_post_invalid_doc_json_exits_1(monkeypatch, tmp_path, capsys):
    doc = tmp_path / "journey.json"
    doc.write_text("{not json")
    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(
        cli.client, "upsert_journey", lambda *a, **k: pytest.fail("malformed doc must not be posted")
    )
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "journey", "post", "--slug", "wool-crush", "--title", "T", "--doc", str(doc)],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert "invalid journey doc JSON" in capsys.readouterr().err


def test_journey_post_doc_without_steps_exits_1(monkeypatch, tmp_path, capsys):
    doc = tmp_path / "journey.json"
    doc.write_text(json.dumps({"title": "no steps"}))
    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(
        cli.client, "upsert_journey", lambda *a, **k: pytest.fail("doc without steps must not be posted")
    )
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "journey", "post", "--slug", "wool-crush", "--title", "T", "--doc", str(doc)],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert "must be a JSON object with a 'steps' list" in capsys.readouterr().err


def test_journey_list_and_get_call_client(monkeypatch, capsys):
    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(cli.client, "list_journeys", lambda base_url, token: [{"slug": "wool-crush"}])
    monkeypatch.setattr("sys.argv", ["portal", "journey", "list"])
    cli.main()
    assert json.loads(capsys.readouterr().out) == [{"slug": "wool-crush"}]

    monkeypatch.setattr(
        cli.client, "get_journey", lambda base_url, token, slug: {"slug": slug, "title": "Wool Crush"}
    )
    monkeypatch.setattr("sys.argv", ["portal", "journey", "get", "--slug", "wool-crush"])
    cli.main()
    assert json.loads(capsys.readouterr().out) == {"slug": "wool-crush", "title": "Wool Crush"}


def test_journey_post_client_error_exits_1(monkeypatch, tmp_path, capsys):
    doc = tmp_path / "journey.json"
    doc.write_text(json.dumps({"steps": []}))
    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))

    def boom(*_args, **_kwargs):
        raise cli.client.GalleryClientError(400, "invalid journey doc")

    monkeypatch.setattr(cli.client, "upsert_journey", boom)
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "journey", "post", "--slug", "wool-crush", "--title", "T", "--doc", str(doc)],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert "error: HTTP 400: invalid journey doc" in capsys.readouterr().err


def test_list_parses_flags(monkeypatch):
    parser_args = []
    monkeypatch.setattr(cli, "cmd_list", lambda args: parser_args.append(args))
    monkeypatch.setattr("sys.argv", ["gallery", "list", "--open", "--project", "foo", "--json"])
    cli.main()
    assert len(parser_args) == 1
    assert parser_args[0].open is True
    assert parser_args[0].project == "foo"
    assert parser_args[0].json is True


def test_stream_new_defaults_and_calls_client(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))

    def fake_create_stream(base_url, token, slug, kind, title):
        calls.append((base_url, token, slug, kind, title))
        return {"slug": slug, "kind": kind, "title": title}

    monkeypatch.setattr(cli.client, "create_stream", fake_create_stream)
    monkeypatch.setattr("sys.argv", ["portal", "stream", "new", "alpha"])

    cli.main()

    assert calls == [("http://gallery", "tok", "alpha", "session", "alpha")]
    assert json.loads(capsys.readouterr().out) == {"slug": "alpha", "kind": "session", "title": "alpha"}


def test_stream_new_accepts_kind_and_title(monkeypatch):
    calls = []

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(
        cli.client,
        "create_stream",
        lambda base_url, token, slug, kind, title: calls.append((base_url, token, slug, kind, title)) or {},
    )
    monkeypatch.setattr("sys.argv", ["portal", "stream", "new", "alpha", "--kind", "pinned", "--title", "Alpha"])

    cli.main()

    assert calls == [("http://gallery", "tok", "alpha", "pinned", "Alpha")]


def test_stream_new_rejects_invalid_kind(monkeypatch):
    monkeypatch.setattr("sys.argv", ["portal", "stream", "new", "alpha", "--kind", "bogus"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2


def test_stream_close_calls_client(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(
        cli.client,
        "close_stream",
        lambda base_url, token, slug: calls.append((base_url, token, slug)) or {"slug": slug, "closed_at": "now"},
    )
    monkeypatch.setattr("sys.argv", ["portal", "stream", "close", "alpha"])

    cli.main()

    assert calls == [("http://gallery", "tok", "alpha")]
    assert json.loads(capsys.readouterr().out) == {"slug": "alpha", "closed_at": "now"}


def test_close_calls_client_and_prints_result(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(
        cli.client,
        "close_request",
        lambda base_url, token, req_id, reason: calls.append((base_url, token, req_id, reason))
        or {"id": req_id, "status": "closed", "close_reason": reason},
    )
    monkeypatch.setattr("sys.argv", ["portal", "close", "req_abc", "--reason", "stale"])

    cli.main()

    assert calls == [("http://gallery", "tok", "req_abc", "stale")]
    assert json.loads(capsys.readouterr().out) == {"id": "req_abc", "status": "closed", "close_reason": "stale"}


def test_close_requires_reason(monkeypatch):
    monkeypatch.setattr("sys.argv", ["portal", "close", "req_abc"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_supersede_calls_client_and_prints_result(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(
        cli.client,
        "supersede_request",
        lambda base_url, token, req_id, successor, feedback=None: calls.append(
            (base_url, token, req_id, successor, feedback)
        )
        or {"id": req_id, "status": "superseded", "superseded_by": successor},
    )
    monkeypatch.setattr("sys.argv", ["portal", "supersede", "req_old", "--successor", "req_new"])

    cli.main()

    assert calls == [("http://gallery", "tok", "req_old", "req_new", None)]
    assert json.loads(capsys.readouterr().out) == {
        "id": "req_old",
        "status": "superseded",
        "superseded_by": "req_new",
    }


def test_supersede_client_error_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))

    def boom(*_args, **_kwargs):
        raise cli.client.GalleryClientError(409, "request already closed: req_old")

    monkeypatch.setattr(cli.client, "supersede_request", boom)
    monkeypatch.setattr("sys.argv", ["portal", "supersede", "req_old", "--successor", "req_new"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert "error: HTTP 409: request already closed: req_old" in capsys.readouterr().err


def test_wait_exits_3_when_request_closed(monkeypatch, capsys):
    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(
        cli.client,
        "get_json",
        lambda base_url, token, path: {"status": "closed", "close_reason": "stale"},
    )
    monkeypatch.setattr("sys.argv", ["portal", "wait", "req_abc", "--timeout", "5"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 3
    assert "request closed: stale" in capsys.readouterr().err


def test_wait_exits_3_when_request_superseded(monkeypatch, capsys):
    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(
        cli.client,
        "get_json",
        lambda base_url, token, path: {"status": "superseded", "superseded_by": "req_new"},
    )
    monkeypatch.setattr("sys.argv", ["portal", "wait", "req_abc", "--timeout", "5"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 3
    assert "request superseded; live version: req_new" in capsys.readouterr().err


def test_report_posts_report_with_html_and_assets(monkeypatch, tmp_path, capsys):
    html = tmp_path / "report.html"
    asset = tmp_path / "asset.png"
    html.write_text("<html></html>")
    asset.write_bytes(b"png")
    calls = []

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))

    def fake_create_stream_post(base_url, token, slug, type, title, author, body=None, files=None):
        calls.append((base_url, token, slug, type, title, author, body, files))
        return {"post": {"id": "p_report"}}

    monkeypatch.setattr(cli.client, "create_stream_post", fake_create_stream_post)
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "report", "--stream", "alpha", "--title", "Report", str(html), str(asset)],
    )

    cli.main()

    assert calls == [("http://gallery", "tok", "alpha", "report", "Report", "portal", {}, [html, asset])]
    assert json.loads(capsys.readouterr().out) == {"post": {"id": "p_report"}}


def test_report_missing_file_exits_1(monkeypatch, tmp_path):
    monkeypatch.setenv("GALLERY_URL", "http://example.invalid")
    monkeypatch.setenv("GALLERY_TOKEN", "x")
    missing = tmp_path / "missing.html"
    monkeypatch.setattr("sys.argv", ["portal", "report", "--stream", "alpha", "--title", "Report", str(missing)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1


def test_report_client_error_exits_1(monkeypatch, tmp_path, capsys):
    html = tmp_path / "report.html"
    html.write_text("<html></html>")

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))

    def boom(*_args, **_kwargs):
        raise cli.client.GalleryClientError(409, "stream is closed: alpha")

    monkeypatch.setattr(cli.client, "create_stream_post", boom)
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "report", "--stream", "alpha", "--title", "Report", str(html)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert "error: HTTP 409: stream is closed: alpha" in capsys.readouterr().err


def test_new_command_client_errors_exit_1(monkeypatch, capsys):
    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))

    def boom(*_args, **_kwargs):
        raise cli.client.GalleryClientError(500, "broken")

    monkeypatch.setattr(cli.client, "close_stream", boom)
    monkeypatch.setattr("sys.argv", ["portal", "stream", "close", "alpha"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert "error: HTTP 500: broken" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (
            ["portal", "ask", "--help"],
            [
                "client-side polling",
                '{"reply": "...", "message_id": "...", "elapsed_s": 1.23}',
                '{"timeout": true}',
                "success 0",
                "client/API error 1",
                "timeout 2",
                "argparse usage error 2",
            ],
        ),
        (
            ["portal", "pull", "--help"],
            [
                "client-side polling",
                '{"text": "...", "message_id": "..."}',
                '{"empty": true}',
                "success 0",
                "client/API error 1",
                "empty 3",
                "argparse usage error 2",
            ],
        ),
    ],
)
def test_ask_pull_help_documents_exit_contracts(monkeypatch, capsys, argv, expected):
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    for text in expected:
        assert text in out


@pytest.mark.parametrize(
    "argv",
    [
        ["portal", "ask", "--stream", "Bad", "Question?"],
        ["portal", "ask", "--stream", "alpha", "--timeout", "-1", "Question?"],
        ["portal", "ask", "--stream", "alpha", "--interval", "0", "Question?"],
        ["portal", "pull", "--stream", "Bad"],
        ["portal", "pull", "--stream", "alpha", "--timeout", "-1"],
        ["portal", "pull", "--stream", "alpha", "--interval", "0"],
    ],
)
def test_ask_pull_parser_errors_do_not_call_client(monkeypatch, capsys, argv):
    monkeypatch.setattr(cli.config, "client_config", lambda: pytest.fail("parser errors must not read config"))
    monkeypatch.setattr(cli.client, "create_stream_message", lambda *args, **kwargs: pytest.fail("no client calls"))
    monkeypatch.setattr(cli.client, "list_stream_messages", lambda *args, **kwargs: pytest.fail("no client calls"))
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


def test_ask_posts_question_polls_consumes_reply_and_prints_json(monkeypatch, capsys):
    calls = []
    consumed = []
    times = iter([10.0, 12.5])

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(cli.time, "time", lambda: pytest.fail("ask elapsed must not use wall-clock time"))
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: pytest.fail("immediate reply must not sleep"))

    def fake_create(base_url, token, slug, direction, text):
        calls.append(("create", base_url, token, slug, direction, text))
        return {"id": "m_ask", "created_at": "2026-07-08T10:00:00Z"}

    def fake_list(base_url, token, slug, *, since=None, direction=None, unconsumed=False):
        calls.append(("list", base_url, token, slug, since, direction, unconsumed))
        return [{"id": "m_reply", "text": "Ship it"}]

    monkeypatch.setattr(cli.client, "create_stream_message", fake_create)
    monkeypatch.setattr(cli.client, "list_stream_messages", fake_list)
    monkeypatch.setattr(cli.client, "consume_message", lambda *args: consumed.append(args) or {"id": args[2]})
    monkeypatch.setattr("sys.argv", ["portal", "ask", "--stream", "alpha", "Proceed?"])

    cli.main()

    assert calls == [
        ("create", "http://gallery", "tok", "alpha", "to_human", "Proceed?"),
        ("list", "http://gallery", "tok", "alpha", "2026-07-08T10:00:00Z", "to_agent", True),
    ]
    assert consumed == [("http://gallery", "tok", "m_reply")]
    assert json.loads(capsys.readouterr().out) == {
        "reply": "Ship it",
        "message_id": "m_reply",
        "elapsed_s": 2.5,
    }


def test_ask_consume_error_exits_1_without_success_json(monkeypatch, capsys):
    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: pytest.fail("immediate reply must not sleep"))
    monkeypatch.setattr(
        cli.client,
        "create_stream_message",
        lambda *_args: {"id": "m_ask", "created_at": "2026-07-08T10:00:00Z"},
    )
    monkeypatch.setattr(
        cli.client,
        "list_stream_messages",
        lambda *_args, **_kwargs: [{"id": "m_reply", "text": "Go"}],
    )

    def boom(*_args, **_kwargs):
        raise cli.client.GalleryClientError(409, "stream is closed: alpha")

    monkeypatch.setattr(cli.client, "consume_message", boom)
    monkeypatch.setattr("sys.argv", ["portal", "ask", "--stream", "alpha", "Proceed?"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "error: HTTP 409: stream is closed: alpha" in captured.err


def test_ask_sleeps_between_empty_poll_and_reply(monkeypatch, capsys):
    replies = iter([[], [{"id": "m_reply", "text": "Continue"}]])
    sleeps = []
    times = iter([0.0, 0.0, 2.0])

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(
        cli.client,
        "create_stream_message",
        lambda *_args: {"id": "m_ask", "created_at": "2026-07-08T10:00:00Z"},
    )
    monkeypatch.setattr(cli.client, "list_stream_messages", lambda *_args, **_kwargs: next(replies))
    monkeypatch.setattr(cli.client, "consume_message", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "ask", "--stream", "alpha", "--timeout", "5", "--interval", "2", "Question?"],
    )

    cli.main()

    assert sleeps == [2]
    assert json.loads(capsys.readouterr().out)["message_id"] == "m_reply"


def test_ask_timeout_prints_json_exit_2_and_caps_sleep(monkeypatch, capsys):
    sleeps = []
    consumed = []
    times = iter([0.0, 0.2, 1.0])

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(
        cli.client,
        "create_stream_message",
        lambda *_args: {"id": "m_ask", "created_at": "2026-07-08T10:00:00Z"},
    )
    monkeypatch.setattr(cli.client, "list_stream_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli.client, "consume_message", lambda *args, **kwargs: consumed.append(args))
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "ask", "--stream", "alpha", "--timeout", "1", "--interval", "15", "Question?"],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert json.loads(captured.out) == {"timeout": True}
    assert captured.err == ""
    assert consumed == []
    assert sleeps == [0.8]


def test_pull_empty_default_prints_json_exit_3_without_sleep_or_consume(monkeypatch, capsys):
    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(cli.client, "list_stream_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli.client, "consume_message", lambda *args, **kwargs: pytest.fail("empty pull must not consume"))
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: pytest.fail("default pull must not sleep"))
    monkeypatch.setattr("sys.argv", ["portal", "pull", "--stream", "alpha"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    captured = capsys.readouterr()
    assert exc.value.code == 3
    assert json.loads(captured.out) == {"empty": True}
    assert captured.err == ""


def test_pull_consumes_oldest_message_and_prints_json(monkeypatch, capsys):
    list_calls = []
    consumed = []

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))

    def fake_list(base_url, token, slug, *, since=None, direction=None, unconsumed=False):
        list_calls.append((base_url, token, slug, since, direction, unconsumed))
        return [
            {"id": "m_oldest", "text": "First"},
            {"id": "m_newer", "text": "Second"},
        ]

    monkeypatch.setattr(cli.client, "list_stream_messages", fake_list)
    monkeypatch.setattr(cli.client, "consume_message", lambda *args: consumed.append(args) or {"id": args[2]})
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: pytest.fail("immediate pull must not sleep"))
    monkeypatch.setattr("sys.argv", ["portal", "pull", "--stream", "alpha"])

    cli.main()

    assert list_calls == [("http://gallery", "tok", "alpha", None, "to_agent", True)]
    assert consumed == [("http://gallery", "tok", "m_oldest")]
    assert json.loads(capsys.readouterr().out) == {"text": "First", "message_id": "m_oldest"}


def test_pull_consume_error_exits_1_without_success_json(monkeypatch, capsys):
    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: pytest.fail("immediate pull must not sleep"))
    monkeypatch.setattr(
        cli.client,
        "list_stream_messages",
        lambda *_args, **_kwargs: [{"id": "m_oldest", "text": "First"}],
    )

    def boom(*_args, **_kwargs):
        raise cli.client.GalleryClientError(409, "stream is closed: alpha")

    monkeypatch.setattr(cli.client, "consume_message", boom)
    monkeypatch.setattr("sys.argv", ["portal", "pull", "--stream", "alpha"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "error: HTTP 409: stream is closed: alpha" in captured.err


def test_pull_blocks_with_interval_until_message_arrives(monkeypatch, capsys):
    replies = iter([[], [{"id": "m_note", "text": "Use blue"}]])
    sleeps = []
    times = iter([0.0, 0.0])

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(cli.client, "list_stream_messages", lambda *_args, **_kwargs: next(replies))
    monkeypatch.setattr(cli.client, "consume_message", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "pull", "--stream", "alpha", "--timeout", "10", "--interval", "3"],
    )

    cli.main()

    assert sleeps == [3]
    assert json.loads(capsys.readouterr().out) == {"text": "Use blue", "message_id": "m_note"}


def test_pull_timeout_empty_prints_json_exit_3_and_caps_sleep(monkeypatch, capsys):
    sleeps = []
    consumed = []
    times = iter([0.0, 0.2, 1.0])

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(cli.client, "list_stream_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli.client, "consume_message", lambda *args, **kwargs: consumed.append(args))
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "pull", "--stream", "alpha", "--timeout", "1", "--interval", "15"],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    captured = capsys.readouterr()
    assert exc.value.code == 3
    assert json.loads(captured.out) == {"empty": True}
    assert captured.err == ""
    assert consumed == []
    assert sleeps == [0.8]


@pytest.mark.parametrize(
    ("argv", "failing_helper"),
    [
        (["portal", "ask", "--stream", "alpha", "Question?"], "create_stream_message"),
        (["portal", "pull", "--stream", "alpha"], "list_stream_messages"),
    ],
)
def test_ask_pull_client_errors_exit_1(monkeypatch, capsys, argv, failing_helper):
    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))

    def boom(*_args, **_kwargs):
        raise cli.client.GalleryClientError(500, "broken")

    monkeypatch.setattr(cli.client, failing_helper, boom)
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "error: HTTP 500: broken" in captured.err


def test_post_supersedes_defaults_feedback_to_predecessor_verdict_comment(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(
        cli.client, "post_multipart",
        lambda base_url, token, path, fields, files: {"id": "req_new", "variant_count": 1},
    )
    monkeypatch.setattr(
        cli.client, "get_request",
        lambda base_url, token, req_id: {"id": req_id, "verdict": {"comment": "make it pop"}},
    )
    monkeypatch.setattr(
        cli.client, "supersede_request",
        lambda base_url, token, req_id, successor, feedback=None: calls.append((req_id, successor, feedback))
        or {"id": req_id, "status": "superseded", "superseded_by": successor},
    )
    monkeypatch.setattr(cli, "_resolve_files", lambda patterns: ["v.png"])
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "post", "--title", "t", "--kind", "pick-one", "--supersedes", "req_old", "v.png"],
    )
    cli.main()
    assert calls == [("req_old", "req_new", "make it pop")]
    err = capsys.readouterr().err
    assert "using predecessor's verdict comment" in err


def test_post_warns_on_live_sibling_without_supersedes(monkeypatch, capsys):
    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    monkeypatch.setattr(
        cli.client, "post_multipart",
        lambda base_url, token, path, fields, files: {
            "id": "req_new", "variant_count": 1,
            "open_in_stream": [{"id": "req_live", "title": "v4", "created_at": "2026-07-17"}],
        },
    )
    monkeypatch.setattr(cli, "_resolve_files", lambda patterns: ["v.png"])
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "post", "--title", "t", "--kind", "pick-one", "--stream", "loop-a", "v.png"],
    )
    monkeypatch.setattr(cli, "_preflight_stream", lambda base_url, token, slug: None)
    cli.main()
    err = capsys.readouterr().err
    assert "already has a live request req_live" in err
    assert "portal supersede req_live --successor req_new" in err
