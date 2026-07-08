import json
import tomllib
from pathlib import Path

import pytest

from gallery import cli


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
    for verb in ["init", "post", "wait", "status", "list", "serve", "stream", "report"]:
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
    assert "error: HTTP 404: stream missing (request created: req_123)" in capsys.readouterr().err


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
    assert json.loads(capsys.readouterr().out) == {"id": "req_123", "variant_count": 1}


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
