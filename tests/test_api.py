from types import SimpleNamespace

import pytest
from starlette.datastructures import Headers

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

    # re-posting revises the verdict, request stays decided (redecide flag required)
    revise = client.post(
        f"/api/requests/{req_id}/verdict",
        headers=auth_headers(token),
        json={"selected": [1, 3], "redecide": True},
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


def _create_request(client, token, kind="pick-one", n=2, title="t"):
    resp = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": title, "kind": kind},
        files=_upload_files(n),
    )
    assert resp.status_code == 200
    return resp.json()["id"]


def test_close_request_sets_status_and_reason(client, token):
    req_id = _create_request(client, token)
    resp = client.post(
        f"/api/requests/{req_id}/close",
        headers=auth_headers(token),
        json={"reason": "stale queue"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"
    assert resp.json()["close_reason"] == "stale queue"

    detail = client.get(f"/api/requests/{req_id}", headers=auth_headers(token))
    assert detail.json()["status"] == "closed"
    assert detail.json()["verdict"] is None


def test_close_requires_auth_and_reason(client, token):
    req_id = _create_request(client, token)
    assert client.post(f"/api/requests/{req_id}/close", json={"reason": "x"}).status_code == 401
    missing = client.post(f"/api/requests/{req_id}/close", headers=auth_headers(token), json={})
    assert missing.status_code == 400


def test_close_unknown_request_is_404(client, token):
    resp = client.post(
        "/api/requests/req_ffffff/close",
        headers=auth_headers(token),
        json={"reason": "gone"},
    )
    assert resp.status_code == 404


def test_second_close_is_409(client, token):
    req_id = _create_request(client, token)
    client.post(f"/api/requests/{req_id}/close", headers=auth_headers(token), json={"reason": "one"})
    again = client.post(f"/api/requests/{req_id}/close", headers=auth_headers(token), json={"reason": "two"})
    assert again.status_code == 409


def test_supersede_chain_sets_successor_and_banner(client, token):
    old_id = _create_request(client, token, title="Old picker")
    new_id = _create_request(client, token, title="Live picker")
    resp = client.post(
        f"/api/requests/{old_id}/supersede",
        headers=auth_headers(token),
        json={"successor": new_id},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "superseded"
    assert resp.json()["superseded_by"] == new_id

    page = client.get(f"/r/{old_id}?token={token}")
    assert page.status_code == 200
    assert "Superseded" in page.text
    assert f'href="/r/{new_id}"' in page.text
    assert 'id="decide-btn"' not in page.text


def test_supersede_self_is_400_and_unknown_successor_404(client, token):
    req_id = _create_request(client, token)
    self_resp = client.post(
        f"/api/requests/{req_id}/supersede",
        headers=auth_headers(token),
        json={"successor": req_id},
    )
    assert self_resp.status_code == 400
    unknown = client.post(
        f"/api/requests/{req_id}/supersede",
        headers=auth_headers(token),
        json={"successor": "req_absent"},
    )
    assert unknown.status_code == 404


def test_supersede_requires_auth(client, token):
    old_id = _create_request(client, token)
    new_id = _create_request(client, token)
    resp = client.post(f"/api/requests/{old_id}/supersede", json={"successor": new_id})
    assert resp.status_code == 401


def test_supersede_rejects_terminal_successor(client, token):
    a_id = _create_request(client, token)
    b_id = _create_request(client, token)
    first = client.post(f"/api/requests/{a_id}/supersede", headers=auth_headers(token), json={"successor": b_id})
    assert first.status_code == 200

    # b -> a would advertise a dead request as the live version (an A<->B cycle)
    cycle = client.post(f"/api/requests/{b_id}/supersede", headers=auth_headers(token), json={"successor": a_id})
    assert cycle.status_code == 400
    assert "not live" in cycle.json()["detail"]

    closed_id = _create_request(client, token)
    client.post(f"/api/requests/{closed_id}/close", headers=auth_headers(token), json={"reason": "dead"})
    dead = client.post(f"/api/requests/{b_id}/supersede", headers=auth_headers(token), json={"successor": closed_id})
    assert dead.status_code == 400


def test_closed_request_page_shows_banner_without_decide(client, token):
    req_id = _create_request(client, token)
    client.post(f"/api/requests/{req_id}/close", headers=auth_headers(token), json={"reason": "obsolete queue"})

    page = client.get(f"/r/{req_id}?token={token}")
    assert page.status_code == 200
    assert "Closed" in page.text
    assert "obsolete queue" in page.text
    assert 'id="decide-btn"' not in page.text


def test_stream_page_labels_retired_decision_posts(client, token):
    resp = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "Stream lifecycle", "kind": "pick-one", "project": "proj/lifecycle"},
        files=_upload_files(2),
    )
    assert resp.status_code == 200
    req_id = resp.json()["id"]
    client.post(f"/api/requests/{req_id}/close", headers=auth_headers(token), json={"reason": "stale"})

    slug = db._stream_slug_for_project("proj/lifecycle")
    page = client.get(f"/s/{slug}?token={token}")
    assert page.status_code == 200
    assert '<span class="status-badge closed">closed</span>' in page.text
    assert '<span class="status-badge pending">pending</span>' not in page.text


def test_decide_on_superseded_returns_409_with_successor(client, token):
    old_id = _create_request(client, token)
    new_id = _create_request(client, token)
    client.post(f"/api/requests/{old_id}/supersede", headers=auth_headers(token), json={"successor": new_id})

    api = client.post(f"/api/requests/{old_id}/verdict", headers=auth_headers(token), json={"selected": [1]})
    assert api.status_code == 409
    assert api.json()["detail"]["successor"] == new_id

    web = client.post(f"/r/{old_id}/decide?token={token}", json={"selected": [1]})
    assert web.status_code == 409
    assert web.json()["detail"]["successor"] == new_id


def test_decide_on_closed_returns_409_with_reason(client, token):
    req_id = _create_request(client, token)
    client.post(f"/api/requests/{req_id}/close", headers=auth_headers(token), json={"reason": "obsolete"})

    resp = client.post(f"/api/requests/{req_id}/verdict", headers=auth_headers(token), json={"selected": [1]})
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason"] == "obsolete"

    web = client.post(f"/r/{req_id}/decide?token={token}", json={"selected": [1]})
    assert web.status_code == 409
    assert web.json()["detail"]["reason"] == "obsolete"


def test_redecide_lock_requires_explicit_flag(client, token):
    req_id = _create_request(client, token)
    first = client.post(f"/api/requests/{req_id}/verdict", headers=auth_headers(token), json={"selected": [1]})
    assert first.status_code == 200

    blocked = client.post(f"/api/requests/{req_id}/verdict", headers=auth_headers(token), json={"selected": [2]})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["verdict_count"] == 1

    allowed = client.post(
        f"/api/requests/{req_id}/verdict",
        headers=auth_headers(token),
        json={"selected": [2], "redecide": True},
    )
    assert allowed.status_code == 200
    detail = client.get(f"/api/requests/{req_id}", headers=auth_headers(token))
    assert detail.json()["verdict"]["selected"] == [2]


def test_index_open_list_excludes_closed_and_superseded(client, token):
    open_id = _create_request(client, token, title="Still open")
    decided_id = _create_request(client, token, title="Decided one")
    closed_id = _create_request(client, token, title="Closed one")
    old_id = _create_request(client, token, title="Superseded one")
    new_id = _create_request(client, token, title="Successor")

    client.post(f"/api/requests/{decided_id}/verdict", headers=auth_headers(token), json={"selected": [1]})
    client.post(f"/api/requests/{closed_id}/close", headers=auth_headers(token), json={"reason": "stale"})
    client.post(f"/api/requests/{old_id}/supersede", headers=auth_headers(token), json={"successor": new_id})

    assert db.open_count() == 2  # open_id + new_id

    page = client.get(f"/?token={token}")
    assert page.status_code == 200
    open_section = page.text.split("Streams")[0]
    assert "Still open" in open_section
    assert "Closed one" not in open_section
    assert "Superseded one" not in open_section
    # retired requests are still surfaced somewhere on the index
    assert "Closed one" in page.text
    assert "Superseded one" in page.text


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


def test_request_metadata_round_trip(client, token):
    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={
            "title": "Pick a frame",
            "kind": "pick-one",
            "step": "  frame picking  ",
            "purpose": "choose the hero shot",
            "ask": "pick the winning frame",
        },
        files=_upload_files(1),
    )
    assert create.status_code == 200
    req_id = create.json()["id"]

    detail = client.get(f"/api/requests/{req_id}", headers=auth_headers(token)).json()
    assert detail["step"] == "frame picking"  # stripped
    assert detail["purpose"] == "choose the hero shot"
    assert detail["ask"] == "pick the winning frame"


def test_request_metadata_omitted_or_blank_is_null(client, token):
    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "No metadata", "kind": "pick-one", "step": "   "},
        files=_upload_files(1),
    )
    assert create.status_code == 200
    detail = client.get(f"/api/requests/{create.json()['id']}", headers=auth_headers(token)).json()
    assert detail["step"] is None
    assert detail["purpose"] is None
    assert detail["ask"] is None


def test_request_metadata_too_long_rejected(client, token):
    for field in ("step", "purpose", "ask"):
        resp = client.post(
            "/api/requests",
            headers=auth_headers(token),
            data={"title": "t", "kind": "pick-one", field: "x" * (server.MAX_TITLE_LENGTH + 1)},
            files=_upload_files(1),
        )
        assert resp.status_code == 400
        assert f"{field} is too long" in resp.json()["detail"]


# --- Upload size cap (P5e) -------------------------------------------------


def test_upload_over_limit_rejected_with_413(client, token):
    cfg = config.load_config()
    cfg["max_upload_bytes"] = 100
    config.save_config(cfg)

    resp = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "too big", "kind": "pick-one"},
        files=_upload_files(1),
    )
    assert resp.status_code == 413
    detail = resp.json()["detail"]
    assert "100" in detail and "bytes" in detail  # message names the limit

    # No row and no media dir left behind by the rejected upload.
    assert client.get("/api/requests", headers=auth_headers(token)).json() == []
    assert not any(config.media_dir().iterdir())


def test_default_config_small_upload_unaffected(client, token):
    # Default 64 MB config: a small upload is byte-for-byte unaffected.
    resp = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "fine", "kind": "pick-one"},
        files=_upload_files(3),
    )
    assert resp.status_code == 200
    assert resp.json()["variant_count"] == 3


def test_upload_limit_boundary_is_strict(client, token):
    # Capture the exact multipart Content-Length httpx sends (deterministic for
    # identical files: httpx uses a fixed-length boundary).
    files_data = {"title": "boundary", "kind": "pick-one"}
    probe = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data=files_data,
        files=_upload_files(1),
    )
    assert probe.status_code == 200
    body_size = int(probe.request.headers["content-length"])

    # Limit exactly equal to the body → accepted (check is strictly greater-than).
    cfg = config.load_config()
    cfg["max_upload_bytes"] = body_size
    config.save_config(cfg)
    at_limit = client.post(
        "/api/requests", headers=auth_headers(token), data=files_data, files=_upload_files(1)
    )
    assert at_limit.status_code == 200

    # One byte under → rejected.
    cfg["max_upload_bytes"] = body_size - 1
    config.save_config(cfg)
    over = client.post(
        "/api/requests", headers=auth_headers(token), data=files_data, files=_upload_files(1)
    )
    assert over.status_code == 413


def test_enforce_upload_size_ignores_missing_or_malformed_length():
    # A missing or unpar-seable Content-Length falls through to normal handling
    # (documents the trusted-client Content-Length pre-check, not streaming).
    server._enforce_upload_size(SimpleNamespace(headers=Headers({})), 100)
    server._enforce_upload_size(
        SimpleNamespace(headers=Headers({"content-length": "not-a-number"})), 100
    )
    with pytest.raises(server.HTTPException) as exc:
        server._enforce_upload_size(
            SimpleNamespace(headers=Headers({"content-length": "101"})), 100
        )
    assert exc.value.status_code == 413


# --- Filename double-prefix guard (P5e) ------------------------------------


def _stored_paths(client, token, files):
    resp = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "prefix", "kind": "pick-one"},
        files=files,
    )
    assert resp.status_code == 200
    detail = client.get(f"/api/requests/{resp.json()['id']}", headers=auth_headers(token)).json()
    return detail["variants"]


def test_plain_filename_prefixed_once(client, token):
    variants = _stored_paths(client, token, [("files", ("v.png", tiny_png_bytes(), "image/png"))])
    assert variants[0]["media_path"] == "01_v.png"


def test_pre_prefixed_filename_not_doubled(client, token):
    variants = _stored_paths(client, token, [("files", ("01_x.png", tiny_png_bytes(), "image/png"))])
    assert variants[0]["media_path"] == "01_x.png"


def test_pre_prefixed_name_decoupled_from_upload_position(client, token):
    # A baked ordinal that differs from the upload position is preserved: the
    # filename keeps `05_`, while the positional idx is 2.
    variants = _stored_paths(
        client,
        token,
        [
            ("files", ("a.png", tiny_png_bytes(), "image/png")),
            ("files", ("05_v.png", tiny_png_bytes(), "image/png")),
        ],
    )
    assert variants[0]["media_path"] == "01_a.png"
    assert variants[1]["media_path"] == "05_v.png"
    assert variants[1]["idx"] == 2


def test_three_digit_leading_number_is_prefixed_normally(client, token):
    # Only an exact two-digit `^\d{2}_` marker counts as an ordinal; `123_` does not.
    variants = _stored_paths(
        client, token, [("files", ("123_x.png", tiny_png_bytes(), "image/png"))]
    )
    assert variants[0]["media_path"] == "01_123_x.png"


def test_colliding_stored_names_do_not_overwrite(client, token):
    # keep-as-is drops the positional uniqueness guarantee: a plain first file is
    # stored as `01_x.png`, and a later baked `01_x.png` would map to the same
    # name. The first must keep its baked name; the second must be disambiguated
    # (not silently overwrite it), and both files must keep their own bytes.
    resp = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "collide", "kind": "pick-one"},
        files=[
            ("files", ("x.png", b"AAAA", "image/png")),
            ("files", ("01_x.png", b"BBBB", "image/png")),
        ],
    )
    assert resp.status_code == 200
    req_id = resp.json()["id"]

    variants = client.get(f"/api/requests/{req_id}", headers=auth_headers(token)).json()["variants"]
    names = [v["media_path"] for v in variants]
    assert names[0] == "01_x.png"  # first occurrence keeps its baked name
    assert len(set(names)) == 2  # second stored distinctly, no silent overwrite

    # Each stored file resolves to its own uploaded bytes.
    assert client.get(f"/media/{req_id}/{names[0]}", params={"token": token}).content == b"AAAA"
    assert client.get(f"/media/{req_id}/{names[1]}", params={"token": token}).content == b"BBBB"


def test_verdict_fires_notify_hook(client, data_dir, tmp_path):
    """A recorded verdict launches the configured verdict_notify_command with
    the request/verdict payload in env vars — and a decide never fails on it."""
    import json as json_lib
    import time

    token = config.load_config()["token"]
    out = tmp_path / "hook-out.txt"
    cfg = config.load_config()
    cfg["verdict_notify_command"] = (
        f'printf "%s|%s|%s" "$PORTAL_REQ_ID" "$PORTAL_VERDICT_SELECTED" "$PORTAL_CHAIN_URL" > {out}'
    )
    config.save_config(cfg)

    req_id = _create_request(client, token, kind="pick-one", n=2, title="hooked")
    resp = client.post(
        f"/api/requests/{req_id}/verdict",
        json={"selected": [2], "comment": "pick the second"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200

    for _ in range(50):
        if out.exists() and out.read_text():
            break
        time.sleep(0.05)
    assert out.exists(), "verdict notify hook did not run"
    got_id, got_selected, got_chain = out.read_text().split("|")
    assert got_id == req_id
    assert json_lib.loads(got_selected) == [2]
    assert got_chain.endswith(f"/c/{req_id}")


def test_verdict_succeeds_when_notify_hook_is_broken(client, data_dir):
    token = config.load_config()["token"]
    cfg = config.load_config()
    cfg["verdict_notify_command"] = "/nonexistent-binary-hopefully"
    config.save_config(cfg)

    req_id = _create_request(client, token, kind="pick-one", n=1, title="hook-broken")
    resp = client.post(
        f"/api/requests/{req_id}/verdict",
        json={"selected": [1]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200


def test_post_into_stream_with_live_sibling_reports_open_in_stream(client, data_dir):
    token = config.load_config()["token"]
    first = client.post(
        "/api/requests",
        data={"title": "v1", "kind": "pick-one", "stream": "loop-a"},
        files=_upload_files(1),
        headers=auth_headers(token),
    ).json()
    second = client.post(
        "/api/requests",
        data={"title": "v2", "kind": "pick-one", "stream": "loop-a"},
        files=_upload_files(1),
        headers=auth_headers(token),
    ).json()
    assert [s["id"] for s in second["open_in_stream"]] == [first["id"]]
    # no explicit stream -> no guardrail payload
    plain = client.post(
        "/api/requests",
        data={"title": "solo", "kind": "pick-one"},
        files=_upload_files(1),
        headers=auth_headers(token),
    ).json()
    assert "open_in_stream" not in plain


def test_static_url_is_content_hashed_and_stable(data_dir):
    first = server.static_url("style.css")
    assert first.startswith("/static/style.css?v=")
    assert len(first.split("v=")[1]) == 8
    assert server.static_url("style.css") == first
    assert server.static_url("does-not-exist.css") == "/static/does-not-exist.css"


def test_pages_use_hashed_static_urls(client, data_dir):
    token = config.load_config()["token"]
    page = client.get(f"/?token={token}")
    assert "style.css?v=" in page.text and "style.css?v=5" not in page.text


def test_gif_upload_gets_loop_mp4_sibling_and_template_uses_it(client, data_dir, tmp_path, monkeypatch):
    """GIF variants gain a .loop.mp4 sibling (background transcode) and pages
    render the loop video instead of the GIF once it exists."""
    import shutil as shutil_mod
    import time

    token = config.load_config()["token"]
    if shutil_mod.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    # a tiny 2-frame gif via PIL is unavailable; use ffmpeg itself to make one
    import subprocess as sp
    gif_path = tmp_path / "tiny.gif"
    sp.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=16x16:d=0.2", str(gif_path)],
        check=True,
    )
    resp = client.post(
        "/api/requests",
        data={"title": "gif-loop", "kind": "pick-one"},
        files=[("files", ("anim.gif", gif_path.read_bytes(), "image/gif"))],
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    req_id = resp.json()["id"]

    media_dir = config.media_dir() / req_id
    for _ in range(100):
        if list(media_dir.glob("*.loop.mp4")):
            break
        time.sleep(0.1)
    assert list(media_dir.glob("*.loop.mp4")), "loop mp4 sibling was not created"

    page = client.get(f"/r/{req_id}?token={token}")
    assert "variant-loop" in page.text
    assert ".loop.mp4" in page.text
