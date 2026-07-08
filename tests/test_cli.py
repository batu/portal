import json
import tomllib
from pathlib import Path

import pytest

from gallery import cli


def _stub_open_stream(monkeypatch):
    monkeypatch.setattr(cli.client, "get_stream", lambda *_args, **_kwargs: {"closed_at": None})


def test_pyproject_exposes_portal_and_gallery_scripts():
    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())

    assert pyproject["project"]["scripts"]["portal"] == "gallery.cli:main"
    assert pyproject["project"]["scripts"]["gallery"] == "gallery.cli:main"


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
    for verb in ["init", "post", "wait", "status", "list", "serve", "stream", "report", "ask", "pull"]:
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
            },
            "files": [upload],
        }
    ]
    assert json.loads(capsys.readouterr().out) == {"id": "req_123", "variant_count": 1}


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


def test_post_stream_creates_decision_post_with_request_id(monkeypatch, tmp_path, capsys):
    upload = tmp_path / "variant.png"
    upload.write_bytes(b"png")
    request_posts = []
    stream_posts = []

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

    def fake_create_stream_post(base_url, token, slug, type, title, author, body=None, files=None):
        stream_posts.append(
            {
                "base_url": base_url,
                "token": token,
                "slug": slug,
                "type": type,
                "title": title,
                "author": author,
                "body": body,
                "files": files,
            }
        )
        return {"post": {"id": "p_123"}}

    monkeypatch.setattr(cli.client, "create_stream_post", fake_create_stream_post)
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
            },
            "files": [upload],
        }
    ]
    assert stream_posts == [
        {
            "base_url": "http://gallery",
            "token": "tok",
            "slug": "alpha",
            "type": "decision",
            "title": "t",
            "author": "portal",
            "body": {"request_id": "req_123"},
            "files": [],
        }
    ]
    assert json.loads(capsys.readouterr().out) == {
        "id": "req_123",
        "variant_count": 1,
        "stream_post": {"post": {"id": "p_123"}},
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
    monkeypatch.setattr(cli.client, "create_stream_post", lambda *args, **kwargs: {"post": {"id": "p_123"}})
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


def test_post_stream_attach_failure_mentions_created_request(monkeypatch, tmp_path, capsys):
    upload = tmp_path / "variant.png"
    upload.write_bytes(b"png")

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    _stub_open_stream(monkeypatch)
    monkeypatch.setattr(
        cli.client,
        "post_multipart",
        lambda _base_url, _token, _path, _fields, _files: {"id": "req_123", "variant_count": 1},
    )

    def fail_stream_post(*_args, **_kwargs):
        raise cli.client.GalleryClientError(404, "stream missing")

    monkeypatch.setattr(cli.client, "create_stream_post", fail_stream_post)
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "post", "--stream", "alpha", "--title", "t", "--kind", "pick-one", str(upload)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "id": "req_123",
        "variant_count": 1,
        "stream_post": {
            "stream": "alpha",
            "type": "decision",
            "body": {"request_id": "req_123"},
            "status": "attach-failed",
            "error": "HTTP 404: stream missing",
        },
    }
    assert "error: HTTP 404: stream missing (request created: req_123)" in captured.err


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
    stream_posts = []

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
        lambda *args, **kwargs: events.append("create_stream_post")
        or stream_posts.append((args, kwargs))
        or {"post": {"id": "p_123"}},
    )
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "post", "--stream", "alpha", "--title", "t", "--kind", "pick-one", str(upload)],
    )

    cli.main()

    assert len(request_posts) == 1
    assert len(stream_posts) == 1
    assert events == ["get_stream", "post_multipart", "create_stream_post"]


def test_post_stream_missing_request_id_exits_1(monkeypatch, tmp_path, capsys):
    upload = tmp_path / "variant.png"
    upload.write_bytes(b"png")

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    _stub_open_stream(monkeypatch)
    monkeypatch.setattr(cli.client, "post_multipart", lambda *_args, **_kwargs: {"variant_count": 1})
    monkeypatch.setattr(
        cli.client,
        "create_stream_post",
        lambda *args, **kwargs: pytest.fail("request id is required before stream attachment"),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "post", "--stream", "alpha", "--title", "t", "--kind", "pick-one", str(upload)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert "error: request response missing id" in capsys.readouterr().err


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


@pytest.mark.parametrize(
    ("argv_prefix", "stream"),
    [
        ([], "inbox"),
        (["--project", "fabrika/find_the_dog"], "proj-fabrika-find-the-dog"),
    ],
)
def test_post_stream_skips_duplicate_legacy_stream_attach(monkeypatch, tmp_path, capsys, argv_prefix, stream):
    upload = tmp_path / "variant.png"
    upload.write_bytes(b"png")
    request_posts = []

    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://gallery", "tok"))
    _stub_open_stream(monkeypatch)

    def fake_post_multipart(base_url, token, path, fields, files):
        request_posts.append((base_url, token, path, fields, files))
        return {"id": "req_123", "variant_count": 1}

    monkeypatch.setattr(cli.client, "post_multipart", fake_post_multipart)
    monkeypatch.setattr(
        cli.client,
        "create_stream_post",
        lambda *args, **kwargs: pytest.fail("legacy stream already contains the request decision post"),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "portal",
            "post",
            "--stream",
            stream,
            *argv_prefix,
            "--title",
            "t",
            "--kind",
            "pick-one",
            str(upload),
        ],
    )

    cli.main()

    assert len(request_posts) == 1
    assert json.loads(capsys.readouterr().out) == {
        "id": "req_123",
        "variant_count": 1,
        "stream_post": {
            "stream": stream,
            "type": "decision",
            "body": {"request_id": "req_123"},
            "status": "already-attached",
        },
    }


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
