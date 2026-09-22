import json

from gallery import client as gallery_client
from gallery import config
from gallery import db
from gallery import server


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def tiny_png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000100ffff03000006000557bfabd4000000"
        "0049454e44ae426082"
    )


def _request_uploads(n=1):
    return [("files", (f"variant-{i}.png", tiny_png_bytes(), "image/png")) for i in range(1, n + 1)]


def test_stream_routes_require_bearer_auth(client):
    assert client.post("/api/streams", json={"slug": "alpha", "kind": "session", "title": "Alpha"}).status_code == 401
    assert client.post("/api/streams/alpha/close").status_code == 401
    assert client.get("/api/streams/alpha").status_code == 401
    assert client.post(
        "/api/streams/alpha/posts",
        data={"type": "report", "title": "Report", "author": "codex"},
    ).status_code == 401
    assert client.get("/api/streams/alpha/posts/p_123456").status_code == 401


def test_stream_create_close_get_round_trip(client, token):
    create = client.post(
        "/api/streams",
        headers=auth_headers(token),
        json={"slug": "alpha", "kind": "session", "title": "Alpha"},
    )
    assert create.status_code == 200
    assert create.json()["slug"] == "alpha"
    assert create.json()["kind"] == "session"
    assert create.json()["title"] == "Alpha"
    assert create.json()["closed_at"] is None

    get = client.get("/api/streams/alpha", headers=auth_headers(token))
    assert get.status_code == 200
    assert get.json()["slug"] == "alpha"
    assert get.json()["posts"] == []

    close = client.post("/api/streams/alpha/close", headers=auth_headers(token))
    assert close.status_code == 200
    assert close.json()["closed_at"] is not None

    closed_get = client.get("/api/streams/alpha", headers=auth_headers(token))
    assert closed_get.status_code == 200
    assert closed_get.json()["closed_at"] == close.json()["closed_at"]

    rejected = client.post(
        "/api/streams/alpha/posts",
        headers=auth_headers(token),
        data={"type": "report", "title": "Too late", "author": "codex"},
    )
    assert rejected.status_code == 409


def test_report_post_to_unknown_stream_auto_creates_and_serves_media(client, token):
    create = client.post(
        "/api/streams/session-0708/posts",
        headers=auth_headers(token),
        data={
            "type": "report",
            "title": "Layout pass",
            "author": "codex",
            "body": json.dumps({"summary": "ok"}),
        },
        files=[("files", ("report.png", tiny_png_bytes(), "image/png"))],
    )
    assert create.status_code == 200
    payload = create.json()
    post = payload["post"]
    assert post["id"].startswith("p_")
    assert post["stream"] == "session-0708"
    assert post["type"] == "report"
    assert post["body"]["summary"] == "ok"
    assert post["body"]["files"][0]["media_type"] == "image/png"
    media_path = post["body"]["files"][0]["media_path"]

    stream_get = client.get("/api/streams/session-0708", headers=auth_headers(token))
    assert stream_get.status_code == 200
    stream = stream_get.json()
    assert stream["kind"] == "session"
    assert [p["id"] for p in stream["posts"]] == [post["id"]]
    assert stream["posts"][0]["stream"] == "session-0708"

    media = client.get(f"/media/{post['id']}/{media_path}?token={token}")
    assert media.status_code == 200
    assert media.headers["x-content-type-options"] == "nosniff"
    assert media.content == tiny_png_bytes()


def test_stream_post_get_includes_public_stream_slug(client, token):
    create = client.post(
        "/api/streams/public-slug/posts",
        headers=auth_headers(token),
        data={"type": "report", "title": "Report", "author": "codex"},
    )
    assert create.status_code == 200
    post = create.json()["post"]

    get = client.get(f"/api/streams/public-slug/posts/{post['id']}", headers=auth_headers(token))

    assert get.status_code == 200
    assert get.json()["stream"] == "public-slug"


def test_legacy_requests_are_visible_in_project_and_inbox_streams(client, token):
    project_create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Pick", "project": "fabrika/x", "kind": "pick-one"},
        files=_request_uploads(1),
    )
    inbox_create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Inbox", "kind": "approve"},
        files=_request_uploads(1),
    )
    assert project_create.status_code == 200
    assert inbox_create.status_code == 200

    project_stream = client.get("/api/streams/proj-fabrika-x", headers=auth_headers(token))
    assert project_stream.status_code == 200
    project_posts = project_stream.json()["posts"]
    assert project_posts[0]["type"] == "decision"
    assert project_posts[0]["body"] == {"request_id": project_create.json()["id"]}

    inbox_stream = client.get("/api/streams/inbox", headers=auth_headers(token))
    assert inbox_stream.status_code == 200
    inbox_posts = inbox_stream.json()["posts"]
    assert inbox_posts[0]["body"] == {"request_id": inbox_create.json()["id"]}


def test_explicit_stream_sets_authoritative_stream_id_and_single_decision_post(client, token):
    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Owned by alpha", "project": "fabrika/x", "kind": "pick-one", "stream": "alpha"},
        files=_request_uploads(1),
    )
    assert create.status_code == 200
    req_id = create.json()["id"]

    alpha = db.get_stream("alpha")
    assert alpha is not None
    assert db.get_request(req_id)["stream_id"] == alpha["id"]
    assert db.get_request(req_id)["project"] == "fabrika/x"

    stream = client.get("/api/streams/alpha", headers=auth_headers(token))
    assert stream.status_code == 200
    posts = stream.json()["posts"]
    assert [p["type"] for p in posts] == ["decision"]
    assert posts[0]["body"] == {"request_id": req_id}

    # ownership moved to alpha: the project-derived stream was never created.
    assert client.get("/api/streams/proj-fabrika-x", headers=auth_headers(token)).status_code == 404


def test_absent_stream_keeps_legacy_project_ownership(client, token):
    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Legacy owned", "project": "navigation/project", "kind": "pick-one"},
        files=_request_uploads(1),
    )
    assert create.status_code == 200
    req_id = create.json()["id"]

    proj_stream = db.get_stream(db._stream_slug_for_project("navigation/project"))
    assert proj_stream is not None
    assert db.get_request(req_id)["stream_id"] == proj_stream["id"]
    assert db.get_stream("alpha") is None


def test_blank_stream_field_falls_back_to_legacy_project_ownership(client, token):
    # A direct API caller sending an empty or whitespace-only stream field must
    # get the same legacy ownership as an absent field (the CLI cannot send
    # these; argparse rejects them before any HTTP call).
    for blank in ("", "   "):
        create = client.post(
            "/api/requests",
            headers=auth_headers(token),
            data={"title": "Blank stream", "project": "navigation/project", "kind": "pick-one", "stream": blank},
            files=_request_uploads(1),
        )
        assert create.status_code == 200
        req_id = create.json()["id"]

        proj_stream = db.get_stream(db._stream_slug_for_project("navigation/project"))
        assert proj_stream is not None
        assert db.get_request(req_id)["stream_id"] == proj_stream["id"]


def test_explicit_stream_matching_legacy_slug_yields_single_decision_post(client, token):
    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Explicit legacy", "project": "fabrika/x", "kind": "pick-one", "stream": "proj-fabrika-x"},
        files=_request_uploads(1),
    )
    assert create.status_code == 200
    req_id = create.json()["id"]

    proj_stream = db.get_stream("proj-fabrika-x")
    assert proj_stream is not None
    assert db.get_request(req_id)["stream_id"] == proj_stream["id"]

    stream = client.get("/api/streams/proj-fabrika-x", headers=auth_headers(token))
    assert stream.status_code == 200
    posts = stream.json()["posts"]
    assert [p["type"] for p in posts] == ["decision"]
    assert posts[0]["body"] == {"request_id": req_id}


def test_post_to_closed_explicit_stream_rejected_with_409_no_row_no_media(client, token):
    assert client.post(
        "/api/streams",
        headers=auth_headers(token),
        json={"slug": "alpha", "kind": "session", "title": "Alpha"},
    ).status_code == 200
    assert client.post("/api/streams/alpha/close", headers=auth_headers(token)).status_code == 200

    rejected = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Too late", "kind": "pick-one", "stream": "alpha"},
        files=_request_uploads(1),
    )
    assert rejected.status_code == 409

    assert db.list_requests() == []
    media_root = config.media_dir()
    assert not media_root.exists() or list(media_root.iterdir()) == []


def test_invalid_explicit_stream_slug_rejected_400_no_row(client, token):
    rejected = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Bad slug", "kind": "pick-one", "stream": "Bad Slug"},
        files=_request_uploads(1),
    )
    assert rejected.status_code == 400
    assert db.list_requests() == []


def test_closing_explicit_stream_makes_request_decide_409(client, token):
    assert client.post(
        "/api/streams",
        headers=auth_headers(token),
        json={"slug": "alpha", "kind": "session", "title": "Alpha"},
    ).status_code == 200

    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Owned by alpha", "kind": "pick-one", "stream": "alpha"},
        files=_request_uploads(1),
    )
    assert create.status_code == 200
    req_id = create.json()["id"]

    assert client.post("/api/streams/alpha/close", headers=auth_headers(token)).status_code == 200

    verdict = client.post(
        f"/api/requests/{req_id}/verdict",
        headers=auth_headers(token),
        json={"selected": [1], "comment": "nope"},
    )
    assert verdict.status_code == 409


def test_legacy_project_stream_slug_is_bounded_and_routable(client, token):
    project = "ab/" * 80

    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Long project", "project": project, "kind": "pick-one"},
        files=_request_uploads(1),
    )
    assert create.status_code == 200

    slug = db._stream_slug_for_project(project)
    assert len(slug) <= db.STREAM_SLUG_MAX_LENGTH
    assert server.STREAM_SLUG_RE.fullmatch(slug)

    stream = client.get(f"/api/streams/{slug}", headers=auth_headers(token))
    assert stream.status_code == 200
    assert stream.json()["posts"][0]["body"] == {"request_id": create.json()["id"]}


def test_overlong_legacy_project_stream_slugs_do_not_collide_after_close(client, token):
    common_prefix = "ab/" * 80
    first_project = f"{common_prefix}first"
    second_project = f"{common_prefix}second"
    first_slug = db._stream_slug_for_project(first_project)
    second_slug = db._stream_slug_for_project(second_project)

    assert first_slug != second_slug

    first = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "First long project", "project": first_project, "kind": "pick-one"},
        files=_request_uploads(1),
    )
    assert first.status_code == 200
    assert client.post(f"/api/streams/{first_slug}/close", headers=auth_headers(token)).status_code == 200

    second = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Second long project", "project": second_project, "kind": "pick-one"},
        files=_request_uploads(1),
    )
    assert second.status_code == 200

    first_stream = client.get(f"/api/streams/{first_slug}", headers=auth_headers(token))
    second_stream = client.get(f"/api/streams/{second_slug}", headers=auth_headers(token))
    assert first_stream.status_code == 200
    assert second_stream.status_code == 200
    assert first_stream.json()["posts"][0]["body"] == {"request_id": first.json()["id"]}
    assert second_stream.json()["posts"][0]["body"] == {"request_id": second.json()["id"]}


def test_stream_decision_post_references_existing_request_and_is_stream_scoped(client, token):
    request_create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Decision source", "kind": "pick-one"},
        files=_request_uploads(1),
    )
    req_id = request_create.json()["id"]

    create = client.post(
        "/api/streams/decisions/posts",
        headers=auth_headers(token),
        data={
            "type": "decision",
            "title": "Decision mirror",
            "author": "codex",
            "body": json.dumps({"request_id": req_id}),
        },
    )
    assert create.status_code == 200
    post = create.json()["post"]
    assert post["body"] == {"request_id": req_id}

    get = client.get(f"/api/streams/decisions/posts/{post['id']}", headers=auth_headers(token))
    assert get.status_code == 200
    assert get.json()["id"] == post["id"]

    other = client.post(
        "/api/streams",
        headers=auth_headers(token),
        json={"slug": "other", "kind": "session", "title": "Other"},
    )
    assert other.status_code == 200
    assert client.get(f"/api/streams/other/posts/{post['id']}", headers=auth_headers(token)).status_code == 404


def test_stream_decision_post_rejects_missing_or_unknown_request(client, token):
    missing = client.post(
        "/api/streams/decisions/posts",
        headers=auth_headers(token),
        data={"type": "decision", "title": "Missing", "author": "codex", "body": "{}"},
    )
    unknown = client.post(
        "/api/streams/decisions/posts",
        headers=auth_headers(token),
        data={
            "type": "decision",
            "title": "Unknown",
            "author": "codex",
            "body": json.dumps({"request_id": "req_missing"}),
        },
    )

    assert missing.status_code == 400
    assert unknown.status_code == 404


def test_oversized_report_post_warns_but_succeeds(client, token, monkeypatch):
    monkeypatch.setattr(server, "POST_UPLOAD_SOFT_CAP_BYTES", 4)

    create = client.post(
        "/api/streams/big/posts",
        headers=auth_headers(token),
        data={"type": "report", "title": "Big", "author": "codex"},
        files=[("files", ("big.bin", b"123456", "application/octet-stream"))],
    )
    assert create.status_code == 200
    assert "warning" in create.json()
    assert create.json()["post"]["body"]["files"][0]["size"] == 6


def test_stream_create_rejects_non_object_json(client, token):
    create = client.post("/api/streams", headers=auth_headers(token), json=["not", "an", "object"])

    assert create.status_code == 400
    assert create.json()["detail"] == "JSON body must be an object"


def test_stream_create_rejects_response_unsafe_text(client, token):
    create = client.post(
        "/api/streams",
        headers={**auth_headers(token), "Content-Type": "application/json"},
        content=b'{"slug":"unsafe-text","kind":"session","title":"\\ud800"}',
    )

    assert create.status_code == 400
    assert create.json()["detail"] == "body JSON contains invalid unicode"


def test_stream_post_rejects_response_unsafe_body_json(client, token):
    nan_body = client.post(
        "/api/streams/unsafe-json/posts",
        headers=auth_headers(token),
        data={"type": "report", "title": "NaN", "author": "codex", "body": '{"x": NaN}'},
    )
    surrogate_body = client.post(
        "/api/streams/unsafe-json/posts",
        headers=auth_headers(token),
        data={"type": "report", "title": "Surrogate", "author": "codex", "body": '{"x": "\\ud800"}'},
    )

    assert nan_body.status_code == 400
    assert surrogate_body.status_code == 400


def test_media_serves_html_variants_as_attachment(client, token):
    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "HTML variant", "kind": "pick-one"},
        files=[("files", ("variant.html", b"<script>alert(1)</script>", "text/html"))],
    )
    assert create.status_code == 200
    req_id = create.json()["id"]
    media_path = db.get_request(req_id)["variants"][0]["media_path"]

    media = client.get(f"/media/{req_id}/{media_path}?token={token}")
    assert media.status_code == 200
    assert media.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in media.headers
    assert "attachment" in media.headers["content-disposition"]


def test_media_serves_legacy_single_segment_filenames_with_spaces(client, token):
    media_dir = config.media_dir() / "req_legacy"
    media_dir.mkdir(parents=True)
    (media_dir / "01_Screen Shot.png").write_bytes(tiny_png_bytes())

    media = client.get(f"/media/req_legacy/01_Screen%20Shot.png?token={token}")

    assert media.status_code == 200
    assert media.content == tiny_png_bytes()


def test_media_rejects_traversal_and_uploads_use_safe_filenames(client, token):
    outside = config.media_dir().parent / "outside.png"
    outside.write_bytes(b"outside")

    traversal = client.get(f"/media/req_legacy/..%2Foutside.png?token={token}")
    assert traversal.status_code == 404

    create = client.post(
        "/api/streams/safe-name/posts",
        headers=auth_headers(token),
        data={"type": "report", "title": "Safe", "author": "codex"},
        files=[("files", ("nested/report image.png", b"safe", "image/png"))],
    )
    assert create.status_code == 200
    media_path = create.json()["post"]["body"]["files"][0]["media_path"]
    assert "/" not in media_path
    assert "\\" not in media_path


def test_post_id_collision_does_not_delete_existing_media(client, token, monkeypatch):
    first = client.post(
        "/api/streams/collision/posts",
        headers=auth_headers(token),
        data={"type": "report", "title": "First", "author": "codex"},
        files=[("files", ("report.png", b"first", "image/png"))],
    )
    assert first.status_code == 200
    first_post = first.json()["post"]
    first_media_path = first_post["body"]["files"][0]["media_path"]
    ids = iter([first_post["id"], "p_retry123"])
    monkeypatch.setattr(server.db, "new_post_id", lambda: next(ids))

    second = client.post(
        "/api/streams/collision/posts",
        headers=auth_headers(token),
        data={"type": "report", "title": "Second", "author": "codex"},
        files=[("files", ("report.png", b"second", "image/png"))],
    )

    assert second.status_code == 200
    assert second.json()["post"]["id"] == "p_retry123"
    old_media = client.get(f"/media/{first_post['id']}/{first_media_path}?token={token}")
    assert old_media.status_code == 200
    assert old_media.content == b"first"


def test_client_stream_helpers_call_expected_methods_paths_and_payloads(monkeypatch, tmp_path):
    calls = []

    def fake_request(method, url, headers, data=None):
        calls.append({"method": method, "url": url, "headers": headers, "data": data})
        return {"ok": True}

    monkeypatch.setattr(gallery_client, "_request", fake_request)
    upload = tmp_path / "report.html"
    upload.write_text("<html></html>")

    gallery_client.create_stream("http://gallery", "tok", "alpha", "session", "Alpha")
    gallery_client.close_stream("http://gallery", "tok", "alpha")
    gallery_client.get_stream("http://gallery", "tok", "alpha")
    gallery_client.get_stream_post("http://gallery", "tok", "alpha", "p_123456")
    gallery_client.create_stream_post(
        "http://gallery",
        "tok",
        "alpha",
        "report",
        "Report",
        "codex",
        body={"summary": "ok"},
        files=[upload],
    )

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "http://gallery/api/streams"
    assert calls[0]["headers"]["Authorization"] == "Bearer tok"
    assert calls[0]["headers"]["Content-Type"] == "application/json"
    assert calls[1]["url"] == "http://gallery/api/streams/alpha/close"
    assert calls[2]["method"] == "GET"
    assert calls[2]["url"] == "http://gallery/api/streams/alpha"
    assert calls[3]["url"] == "http://gallery/api/streams/alpha/posts/p_123456"
    assert calls[3]["headers"]["Authorization"] == "Bearer tok"
    assert calls[4]["method"] == "POST"
    assert calls[4]["url"] == "http://gallery/api/streams/alpha/posts"
    assert calls[4]["headers"]["Authorization"] == "Bearer tok"
    assert calls[4]["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="body"' in calls[4]["data"]
    assert b'"summary": "ok"' in calls[4]["data"]
    assert b'name="files"; filename="report.html"' in calls[4]["data"]


def _post_report(client, token, files):
    create = client.post(
        "/api/streams/fixes/posts",
        headers=auth_headers(token),
        data={"type": "report", "title": "Report", "author": "codex"},
        files=files,
    )
    assert create.status_code == 200
    return create.json()["post"]


def test_report_assets_resolve_by_original_name(client, token):
    post = _post_report(
        client,
        token,
        [
            ("files", ("page.html", b'<img src="shot.png">', "text/html")),
            ("files", ("shot.png", tiny_png_bytes(), "image/png")),
        ],
    )
    assert post["body"]["files"][1]["media_path"] == "02_shot.png"

    by_original = client.get(f"/media/{post['id']}/shot.png?token={token}")
    by_stored = client.get(f"/media/{post['id']}/02_shot.png?token={token}")
    unknown = client.get(f"/media/{post['id']}/other.png?token={token}")

    assert by_original.status_code == 200
    assert by_original.content == tiny_png_bytes()
    assert by_stored.content == tiny_png_bytes()
    assert unknown.status_code == 404


def test_replace_post_files_overwrites_by_name_and_appends_new(client, token):
    post = _post_report(
        client,
        token,
        [
            ("files", ("page.html", b"<p>v1</p>", "text/html")),
            ("files", ("shot.png", tiny_png_bytes(), "image/png")),
        ],
    )

    replaced = client.post(
        f"/api/posts/{post['id']}/files",
        headers=auth_headers(token),
        files=[
            ("files", ("page.html", b"<p>v2</p>", "text/html")),
            ("files", ("extra.png", tiny_png_bytes(), "image/png")),
        ],
    )

    assert replaced.status_code == 200
    payload = replaced.json()
    assert payload["replaced"] == ["01_page.html"]
    assert payload["added"] == ["03_extra.png"]
    assert [f["media_path"] for f in payload["post"]["body"]["files"]] == [
        "01_page.html",
        "02_shot.png",
        "03_extra.png",
    ]
    page = client.get(f"/media/{post['id']}/01_page.html?token={token}")
    assert b"<p>v2</p>" in page.content
    assert client.get(f"/media/{post['id']}/extra.png?token={token}").status_code == 200
    fetched = client.get(f"/api/posts/{post['id']}", headers=auth_headers(token)).json()
    assert fetched["body"]["files"] == payload["post"]["body"]["files"]
    assert not list((config.media_dir() / post["id"]).glob(".*"))


def test_replace_post_files_requires_auth_and_known_post(client, token):
    files = [("files", ("a.png", tiny_png_bytes(), "image/png"))]
    assert client.post("/api/posts/p_missing/files", files=files).status_code == 401
    assert client.get("/api/posts/p_missing").status_code == 401
    assert client.post("/api/posts/p_missing/files", headers=auth_headers(token), files=files).status_code == 404
    assert client.get("/api/posts/p_missing", headers=auth_headers(token)).status_code == 404
