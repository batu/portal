from gallery import config, db, server


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def tiny_png_bytes() -> bytes:
    """A minimal valid 1x1 transparent PNG, hand-encoded (no Pillow dependency in tests)."""
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000100ffff03000006000557bfabd4000000"
        "0049454e44ae426082"
    )


def _upload_files(n=3):
    return [("files", (f"v{i}.png", tiny_png_bytes(), "image/png")) for i in range(1, n + 1)]


def test_health_unauthenticated(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "open_count": 0}


def test_create_requires_auth(client):
    resp = client.post("/api/requests", data={"title": "t", "kind": "pick-one"}, files=_upload_files())
    assert resp.status_code == 401


def test_create_list_get_decide_flow(client, token):
    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Pick the best crop", "project": "fabrika/find_the_dog", "kind": "pick-one", "context": "**pick one**"},
        files=_upload_files(3),
    )
    assert create.status_code == 200
    body = create.json()
    assert body["variant_count"] == 3
    req_id = body["id"]
    assert req_id.startswith("req_")

    # list: shows up as open
    listed = client.get("/api/requests?status=open", headers=auth_headers(token))
    assert listed.status_code == 200
    ids = [r["id"] for r in listed.json()]
    assert req_id in ids

    # get: full detail
    detail = client.get(f"/api/requests/{req_id}", headers=auth_headers(token))
    assert detail.status_code == 200
    d = detail.json()
    assert d["status"] == "open"
    assert len(d["variants"]) == 3
    assert d["variants"][0]["idx"] == 1
    assert d["verdict"] is None

    # media is servable with the token
    media_path = d["variants"][0]["media_path"]
    media_resp = client.get(f"/media/{req_id}/{media_path}?token={token}")
    assert media_resp.status_code == 200

    # decide
    verdict_resp = client.post(
        f"/api/requests/{req_id}/verdict",
        headers=auth_headers(token),
        json={"selected": [2], "comment": "this one"},
    )
    assert verdict_resp.status_code == 200
    v = verdict_resp.json()
    assert v["selected"] == [2]
    assert v["comment"] == "this one"

    # now decided
    detail2 = client.get(f"/api/requests/{req_id}", headers=auth_headers(token))
    assert detail2.json()["status"] == "decided"
    assert detail2.json()["verdict"]["selected"] == [2]

    # re-posting revises the verdict, request stays decided
    revise = client.post(
        f"/api/requests/{req_id}/verdict",
        headers=auth_headers(token),
        json={"selected": [1, 3]},
    )
    assert revise.status_code == 200
    detail3 = client.get(f"/api/requests/{req_id}", headers=auth_headers(token))
    assert detail3.json()["status"] == "decided"
    assert detail3.json()["verdict"]["selected"] == [1, 3]


def test_decide_rejects_bad_index(client, token):
    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "t", "kind": "pick-one"},
        files=_upload_files(2),
    )
    req_id = create.json()["id"]
    resp = client.post(
        f"/api/requests/{req_id}/verdict",
        headers=auth_headers(token),
        json={"selected": [99]},
    )
    assert resp.status_code == 400


def test_decide_rejects_unknown_request(client, token):
    resp = client.post(
        "/api/requests/req_ffffff/verdict",
        headers=auth_headers(token),
        json={"selected": []},
    )
    assert resp.status_code == 404


def test_invalid_kind_rejected(client, token):
    resp = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "t", "kind": "not-a-kind"},
        files=_upload_files(1),
    )
    assert resp.status_code == 400


def test_request_before_upload_is_stored_outside_variants(client, token):
    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Before after", "kind": "before-after"},
        files=[
            ("before", ("nested/before.png", tiny_png_bytes(), "image/png")),
            ("files", ("after-a.png", tiny_png_bytes(), "image/png")),
            ("files", ("after-b.png", tiny_png_bytes(), "image/png")),
        ],
    )
    assert create.status_code == 200
    req_id = create.json()["id"]

    detail = client.get(f"/api/requests/{req_id}", headers=auth_headers(token))
    assert detail.status_code == 200
    request_body = detail.json()
    assert request_body["before_media_path"] == "__before.png"
    assert request_body["before_media_type"] == "image"
    assert [v["idx"] for v in request_body["variants"]] == [1, 2]

    before_resp = client.get(f"/media/{req_id}/__before.png?token={token}")
    assert before_resp.status_code == 200
    assert before_resp.content == tiny_png_bytes()

    verdict = client.post(
        f"/api/requests/{req_id}/verdict",
        headers=auth_headers(token),
        json={"selected": [1], "comment": "after a"},
    )
    assert verdict.status_code == 200
    assert verdict.json()["selected"] == [1]


def test_before_after_request_page_uses_pick_one_browser_flow(client, token):
    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Before after web", "kind": "before-after"},
        files=_upload_files(1),
    )
    assert create.status_code == 200
    req_id = create.json()["id"]

    page = client.get(f"/r/{req_id}?token={token}")
    script = client.get("/static/app.js")

    assert page.status_code == 200
    assert 'data-kind="before-after"' in page.text
    assert script.status_code == 200
    assert '"before-after": true' in script.text


def test_legacy_request_closed_stream_error_is_409_and_cleans_media(client, token, monkeypatch):
    first = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "First", "project": "closed/project", "kind": "pick-one"},
        files=_upload_files(1),
    )
    assert first.status_code == 200
    closed = client.post("/api/streams/proj-closed-project/close", headers=auth_headers(token))
    assert closed.status_code == 200
    monkeypatch.setattr(server.db, "new_request_id", lambda: "req_after_close")

    second = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Second", "project": "closed/project", "kind": "pick-one"},
        files=_upload_files(1),
    )

    assert second.status_code == 409
    assert not (config.media_dir() / "req_after_close").exists()


def test_legacy_request_notification_thread_failure_does_not_fail_request(client, token, monkeypatch):
    class FailingThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("thread unavailable")

    monkeypatch.setattr(server.threading, "Thread", FailingThread)

    response = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Still created", "kind": "pick-one"},
        files=_upload_files(1),
    )

    assert response.status_code == 200
    assert db.get_request(response.json()["id"]) is not None


def test_legacy_request_reuses_auth_config_for_notification_url(client, token, monkeypatch, data_dir):
    cfg = data_dir[1]
    calls = 0

    class FakeThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    def flaky_load_config():
        nonlocal calls
        calls += 1
        if calls == 1:
            return cfg
        raise RuntimeError("config reloaded after persistence")

    monkeypatch.setattr(server.threading, "Thread", FakeThread)
    monkeypatch.setattr(server.config, "load_config", flaky_load_config)

    response = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Single config read", "kind": "pick-one"},
        files=_upload_files(1),
    )

    assert response.status_code == 200
    assert calls == 1
    assert db.get_request(response.json()["id"]) is not None


def test_request_id_collision_does_not_delete_existing_media(client, token, monkeypatch):
    first = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "First", "kind": "pick-one"},
        files=[("files", ("first.png", b"first", "image/png"))],
    )
    assert first.status_code == 200
    first_id = first.json()["id"]
    detail = client.get(f"/api/requests/{first_id}", headers=auth_headers(token))
    first_media_path = detail.json()["variants"][0]["media_path"]
    ids = iter([first_id, "req_retry"])
    monkeypatch.setattr(server.db, "new_request_id", lambda: next(ids))

    second = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Second", "kind": "pick-one"},
        files=[("files", ("second.png", b"second", "image/png"))],
    )

    assert second.status_code == 200
    assert second.json()["id"] == "req_retry"
    old_media = client.get(f"/media/{first_id}/{first_media_path}?token={token}")
    assert old_media.status_code == 200
    assert old_media.content == b"first"


def test_legacy_verdict_closed_stream_error_is_409(client, token):
    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Closed verdict", "project": "closed/verdict", "kind": "pick-one"},
        files=_upload_files(1),
    )
    assert create.status_code == 200
    req_id = create.json()["id"]
    closed = client.post("/api/streams/proj-closed-verdict/close", headers=auth_headers(token))
    assert closed.status_code == 200

    api_verdict = client.post(
        f"/api/requests/{req_id}/verdict",
        headers=auth_headers(token),
        json={"selected": [1]},
    )
    web_verdict = client.post(f"/r/{req_id}/decide?token={token}", json={"selected": [1]})

    assert api_verdict.status_code == 409
    assert web_verdict.status_code == 409


def test_web_index_requires_token(client, token):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login")

    resp = client.get(f"/?token={token}", follow_redirects=False)
    assert resp.status_code == 200
    assert "gallery_token" in resp.cookies


def test_web_decide_flow(client, token):
    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Web decide test", "kind": "approve"},
        files=_upload_files(1),
    )
    req_id = create.json()["id"]

    page = client.get(f"/r/{req_id}?token={token}")
    assert page.status_code == 200
    assert "Web decide test" in page.text

    decide = client.post(f"/r/{req_id}/decide?token={token}", json={"selected": [1]})
    assert decide.status_code == 200

    detail = client.get(f"/api/requests/{req_id}", headers=auth_headers(token))
    assert detail.json()["status"] == "decided"
