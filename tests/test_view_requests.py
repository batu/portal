"""Interactive view requests: kind=view posts an HTML view with an opaque JSON verdict."""

import json

from gallery import db


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


VIEW_HTML = b"<!doctype html><script>console.log('view')</script><p>picker</p>"
VIEW_CSP = "sandbox allow-scripts allow-same-origin allow-forms"


def _create_view(client, token, files=None, title="Pick frames"):
    files = files or [
        ("files", ("picker.html", VIEW_HTML, "text/html")),
        ("files", ("clip.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")),
    ]
    return client.post(
        "/api/requests",
        data={"title": title, "kind": "view"},
        files=files,
        headers=auth_headers(token),
    )


def test_view_requires_html_entry(client, token):
    resp = client.post(
        "/api/requests",
        data={"title": "no entry", "kind": "view"},
        files=[("files", ("clip.mp4", b"data", "video/mp4"))],
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert "HTML entry" in resp.json()["detail"]


def test_view_html_served_with_scripts_enabled(client, token):
    req_id = _create_view(client, token).json()["id"]
    resp = client.get(f"/media/{req_id}/01_picker.html", params={"token": token})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.headers["content-security-policy"] == VIEW_CSP


def test_report_html_stays_script_blocked(client, token):
    resp = client.post(
        "/api/streams/reports/posts",
        data={"type": "report", "title": "r", "author": "a"},
        files=[("files", ("report.html", b"<p>hi</p>", "text/html"))],
        headers=auth_headers(token),
    )
    post_id = resp.json()["post"]["id"]
    resp = client.get(f"/media/{post_id}/01_report.html", params={"token": token})
    assert resp.status_code == 200
    assert resp.headers["content-security-policy"] == "sandbox allow-same-origin"


def test_view_verdict_payload_roundtrip(client, token):
    req_id = _create_view(client, token).json()["id"]
    payload = {"frames": [{"t": 12.4, "label": "menu", "source": "agent"}, {"t": 31.0, "label": "level", "source": "human"}]}

    resp = client.post(f"/r/{req_id}/decide", json={"payload": payload}, params={"token": token})
    assert resp.status_code == 200
    assert resp.json()["payload"] == payload

    resp = client.get(f"/api/requests/{req_id}", headers=auth_headers(token))
    body = resp.json()
    assert body["status"] == "decided"
    assert body["verdict"]["payload"] == payload
    assert body["verdict"]["selected"] == []


def test_view_verdict_requires_payload(client, token):
    req_id = _create_view(client, token).json()["id"]
    resp = client.post(f"/r/{req_id}/decide", json={"comment": "no payload"}, params={"token": token})
    assert resp.status_code == 400
    assert "payload" in resp.json()["detail"]


def test_view_verdict_payload_latest_wins(client, token):
    req_id = _create_view(client, token).json()["id"]
    client.post(f"/r/{req_id}/decide", json={"payload": {"frames": []}}, params={"token": token})
    client.post(f"/r/{req_id}/decide", json={"payload": {"frames": [{"t": 1.0}]}}, params={"token": token})
    verdict = db.get_latest_verdict(req_id)
    assert verdict["payload"] == {"frames": [{"t": 1.0}]}


def test_non_view_verdict_has_no_payload(client, token):
    resp = client.post(
        "/api/requests",
        data={"title": "pick", "kind": "pick-one"},
        files=[("files", ("v1.png", b"png", "image/png"))],
        headers=auth_headers(token),
    )
    req_id = resp.json()["id"]
    resp = client.post(f"/r/{req_id}/decide", json={"selected": [1]}, params={"token": token})
    assert resp.status_code == 200
    assert resp.json()["payload"] is None


def test_view_request_page_redirects_to_entry_html(client, token):
    req_id = _create_view(client, token).json()["id"]
    resp = client.get(f"/r/{req_id}", params={"token": token}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/media/{req_id}/01_picker.html?token={token}"

    resp = client.get(f"/r/{req_id}", params={"token": token}, follow_redirects=True)
    assert resp.status_code == 200
    assert resp.headers["content-security-policy"] == VIEW_CSP


def test_view_verdict_payload_size_capped(client, token):
    req_id = _create_view(client, token).json()["id"]
    big = {"blob": "x" * 1_000_001}
    resp = client.post(f"/r/{req_id}/decide", json={"payload": big}, params={"token": token})
    assert resp.status_code == 400
    assert "too large" in resp.json()["detail"]


def test_view_wait_shape_via_api_verdict(client, token):
    """Bearer-token verdict endpoint accepts view payloads too (agent-side parity)."""
    req_id = _create_view(client, token).json()["id"]
    payload = {"frames": [{"t": 3.2, "label": "win", "source": "agent"}]}
    resp = client.post(f"/api/requests/{req_id}/verdict", json={"payload": payload}, headers=auth_headers(token))
    assert resp.status_code == 200
    assert json.loads(json.dumps(resp.json()["payload"])) == payload
