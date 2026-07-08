import json

from gallery import client as gallery_client
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
    assert post["type"] == "report"
    assert post["body"]["summary"] == "ok"
    assert post["body"]["files"][0]["media_type"] == "image/png"
    media_path = post["body"]["files"][0]["media_path"]

    stream_get = client.get("/api/streams/session-0708", headers=auth_headers(token))
    assert stream_get.status_code == 200
    stream = stream_get.json()
    assert stream["kind"] == "session"
    assert [p["id"] for p in stream["posts"]] == [post["id"]]

    media = client.get(f"/media/{post['id']}/{media_path}?token={token}")
    assert media.status_code == 200
    assert media.headers["x-content-type-options"] == "nosniff"
    assert media.content == tiny_png_bytes()


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


def test_media_serves_active_content_as_attachment(client, token):
    create = client.post(
        "/api/streams/html-report/posts",
        headers=auth_headers(token),
        data={"type": "report", "title": "HTML", "author": "codex"},
        files=[("files", ("report.html", b"<script>alert(1)</script>", "text/html"))],
    )
    assert create.status_code == 200
    post = create.json()["post"]
    media_path = post["body"]["files"][0]["media_path"]

    media = client.get(f"/media/{post['id']}/{media_path}?token={token}")
    assert media.status_code == 200
    assert media.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in media.headers["content-disposition"]


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
    assert calls[1]["url"] == "http://gallery/api/streams/alpha/close"
    assert calls[2]["method"] == "GET"
    assert calls[2]["url"] == "http://gallery/api/streams/alpha"
    assert calls[3]["url"] == "http://gallery/api/streams/alpha/posts/p_123456"
    assert calls[4]["method"] == "POST"
    assert calls[4]["url"] == "http://gallery/api/streams/alpha/posts"
    assert b'name="body"' in calls[4]["data"]
    assert b'"summary": "ok"' in calls[4]["data"]
    assert b'name="files"; filename="report.html"' in calls[4]["data"]
