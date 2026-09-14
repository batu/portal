"""Public browsing must never confer operator or scoped verdict authority."""
import re

import pytest

from gallery import config, db, server


@pytest.fixture
def published(client, token):
    headers = {"Authorization": f"Bearer {token}"}
    report = client.post(
        "/api/streams/public-review/posts", headers=headers,
        data={"type": "report", "title": "Public report", "author": "test"},
        files=[("files", ("report.html", b"<h1>Public report</h1>", "text/html")),
               ("files", ("clip.mp4", b"0123456789abcdef", "video/mp4"))],
    )
    assert report.status_code == 200
    ids = {"report": report.json()["post"]["id"]}
    for kind in ("pick-one", "view"):
        created = client.post(
            "/api/requests", headers=headers,
            data={"title": f"Public {kind}", "kind": kind, "stream": "public-review"},
            files=[("files", ("entry.html" if kind == "view" else "image.png",
                              b"<p>Producer view</p>" if kind == "view" else b"image",
                              "text/html" if kind == "view" else "image/png"))],
        )
        assert created.status_code == 200
        ids[kind] = created.json()["id"]
    assert client.post(
        "/api/streams/public-review/messages", headers=headers,
        json={"direction": "to_human", "text": "PRIVATE AGENT CONVERSATION"},
    ).status_code == 200
    db.upsert_journey("public-review", "Public journey", {"steps": []})
    cfg = config.load_config()
    cfg["public_viewing"] = True
    config.save_config(cfg)
    client.cookies.clear()
    return ids


def assert_no_authority(response, token, capability):
    assert token not in response.text
    assert capability not in response.text
    assert token not in str(response.headers)
    assert capability not in str(response.headers)
    assert "set-cookie" not in response.headers


def test_anonymous_pages_media_and_capability_isolation(client, token, published, monkeypatch):
    cap = server._view_capability(published["view"])
    def forbidden_mint(*args):
        pytest.fail("anonymous browsing must not mint a verdict capability")
    monkeypatch.setattr(server, "_view_capability", forbidden_mint)
    for path in ("/", "/s/public-review", "/g/public-review", "/games", f'/r/{published["pick-one"]}',
                 f'/c/{published["pick-one"]}', f'/c/{published["view"]}',
                 f'/r/{published["view"]}', f'/media/{published["view"]}/01_entry.html',
                 f'/media/{published["report"]}/01_report.html'):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.url.path != "/login", path
        assert_no_authority(response, token, cap)
        assert response.headers["cache-control"] == "no-store"
        for redirect in response.history:
            assert_no_authority(redirect, token, cap)
        if path.startswith("/s/"):
            assert "data-stream-note-form" not in response.text
            assert "PRIVATE AGENT CONVERSATION" not in response.text
        if path == f'/r/{published["pick-one"]}':
            assert 'id="decide-btn"' not in response.text
    view = client.get(f'/media/{published["view"]}/01_entry.html', headers={"Origin": "null"})
    assert view.headers["content-security-policy"] == server.VIEW_HTML_CSP
    assert "const viewToken" not in view.text
    report = client.get(f'/media/{published["report"]}/01_report.html')
    assert report.headers["content-security-policy"] == "sandbox allow-same-origin"
    assert not client.cookies


@pytest.mark.parametrize("range_value,expected,content_range", [
    ("bytes=2-5", b"2345", "bytes 2-5/16"),
    ("bytes=-4", b"cdef", "bytes 12-15/16"),
    ("bytes=12-", b"cdef", "bytes 12-15/16"),
])
def test_public_video_ranges(client, published, range_value, expected, content_range):
    response = client.get(f'/media/{published["report"]}/02_clip.mp4', headers={"Range": range_value})
    assert response.status_code == 206
    assert response.content == expected
    assert response.headers["content-range"] == content_range
    assert response.headers["accept-ranges"] == "bytes"


def test_public_viewing_does_not_unlock_write_or_admin_routes(client, published):
    # Discover every registered API/web mutation, so new routes cannot silently
    # inherit public viewing. Login is intentionally reachable, not a write bypass.
    for route in server.app.routes:
        path = route.path
        if path == "/login":
            continue
        methods = set(getattr(route, "methods", []) or [])
        if not (methods & {"POST", "PUT", "PATCH", "DELETE"}):
            continue
        replacements = {"req_id": published["pick-one"], "slug": "public-review",
                        "message_id": "msg_absent", "post_id": published["report"],
                        "provider": "codex", "session_id": "sid_absent", "version": "v1",
                        "asset_path:path": "api/test", "proxy_path:path": "api/test",
                        "editor_path:path": "api/test"}
        path = re.sub(r"\{([^}]+)\}", lambda m, values=replacements: values.get(m[1], "test"), path)
        for method in methods & {"POST", "PUT", "PATCH", "DELETE"}:
            response = client.request(method, path, json={}, follow_redirects=False)
            # Multipart validation may precede handler auth, but must not mutate.
            allowed_denials = (404,) if route.path == "/api/{editor_path:path}" else (401, 403, 422, 303)
            assert response.status_code in allowed_denials, (method, path, response.status_code)
            if response.status_code == 303:
                assert response.headers["location"].startswith("/login?")
    for path in ("/api/requests", f'/api/requests/{published["pick-one"]}',
                 "/api/streams/public-review", "/api/streams/public-review/messages",
                 "/api/journeys", "/agents", "/agents/directory",
                 "/tools/ftd-editor/",
                 "/games/public-review/remote-config"):
        assert client.get(path, follow_redirects=False).status_code in (401, 303), path
    assert db.get_request(published["pick-one"])["status"] == "open"
    # Valid upload body must be rejected by auth, not merely schema validation.
    response = client.post("/api/requests", data={"title": "Unauthorized", "kind": "pick-one"},
                           files=[("files", ("image.png", b"image", "image/png"))])
    assert response.status_code == 401
    report = client.post(
        "/api/streams/public-review/posts", data={"type": "report", "title": "Denied", "author": "test"},
        files=[("files", ("report.html", b"<h1>Denied</h1>", "text/html"))],
    )
    assert report.status_code == 401
    game = client.post(
        "/api/games/public-review/builds",
        data={"title": "Denied", "version": "v1", "changelog": "Denied"},
        files={"artifact": ("game.apk", b"build", "application/vnd.android.package-archive"),
               "video": ("clip.mp4", b"video", "video/mp4"),
               "poster": ("poster.jpg", b"poster", "image/jpeg")},
    )
    assert game.status_code == 401
    response = client.post(f'/r/{published["view"]}/decide', json={"payload": {}},
                           headers={"Origin": "null"})
    assert response.status_code == 401


def test_public_flag_can_be_disabled_without_restarting(client, published):
    cfg = config.load_config()
    cfg["public_viewing"] = False
    config.save_config(cfg)
    for path in ("/", "/s/public-review", f'/r/{published["view"]}'):
        assert client.get(path, follow_redirects=False).status_code == 303
    assert client.get(f'/media/{published["report"]}/02_clip.mp4').status_code == 401


def test_wrong_credentials_do_not_gain_write_authority(client, published, token):
    client.cookies.set(server.COOKIE_NAME, "invalid")
    response = client.get(f'/r/{published["view"]}?token=invalid')
    assert response.status_code == 200
    assert_no_authority(response, token, server._view_capability(published["view"]))
    assert "const viewToken" not in response.text
    assert client.post(f'/r/{published["view"]}/decide?token=invalid', json={"payload": {}}).status_code == 401


def test_public_game_read_routes(client, token, published):
    response = client.post(
        "/api/games/public-game/builds", headers={"Authorization": f"Bearer {token}"},
        data={"title": "Public Game", "description": "A game", "version": "v1", "changelog": "Initial release"},
        files={"artifact": ("game.apk", b"build", "application/vnd.android.package-archive"),
               "video": ("clip.mp4", b"0123456789", "video/mp4"),
               "poster": ("poster.jpg", b"poster", "image/jpeg")},
    )
    assert response.status_code == 200
    for path in ("/games", "/games/public-game", "/games/public-game/builds/v1/download"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.url.path != "/login"
        assert_no_authority(response, token, server._view_capability(published["view"]))
    response = client.get("/games/public-game/builds/v1/video", headers={"Range": "bytes=2-4"})
    assert response.status_code == 206
    assert response.content == b"234"


def test_operator_auth_still_works_in_public_mode(client, token, published):
    response = client.get(f'/r/{published["view"]}', params={"token": token}, follow_redirects=False)
    assert response.status_code == 303
    assert server._view_capability(published["view"]) in response.headers["location"]
    assert token not in response.headers["location"]
    decided = client.post(f'/r/{published["pick-one"]}/decide', json={"selected": [1]})
    assert decided.status_code == 200
    # Opaque producer documents cannot turn the operator cookie into authority.
    denied = client.post("/s/public-review/note", json={"text": "no"}, headers={"Origin": "null"})
    assert denied.status_code == 401


@pytest.mark.parametrize("setting", [None, False, "true", 1])
def test_public_viewing_is_explicit_boolean_opt_in(client, setting):
    cfg = config.load_config()
    if setting is None:
        cfg.pop("public_viewing", None)
    else:
        cfg["public_viewing"] = setting
    config.save_config(cfg)
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.get("/media/req_missing/clip.mp4").status_code == 401
