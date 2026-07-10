"""Interactive view requests: kind=view posts an HTML view with an opaque JSON verdict."""

import json

from gallery import db, server


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


def test_superseded_view_renders_banner_instead_of_redirect(client, token):
    old_id = _create_view(client, token).json()["id"]
    new_id = _create_view(client, token).json()["id"]
    resp = client.post(
        f"/api/requests/{old_id}/supersede",
        json={"successor": new_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200

    # A live view redirects to its producer HTML; a terminal view must fall
    # through to the Portal page so the lifecycle banner is reachable.
    live = client.get(f"/r/{new_id}", params={"token": token}, follow_redirects=False)
    assert live.status_code == 303

    page = client.get(f"/r/{old_id}", params={"token": token}, follow_redirects=False)
    assert page.status_code == 200
    assert "Superseded" in page.text
    assert f'href="/r/{new_id}"' in page.text


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
    client.post(
        f"/r/{req_id}/decide",
        json={"payload": {"frames": [{"t": 1.0}]}, "redecide": True},
        params={"token": token},
    )
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


def test_producer_html_gets_context_header(client, token):
    # View branch: home link + stream + status chip, even with no step/ask metadata.
    req_id = _create_view(client, token).json()["id"]
    resp = client.get(f"/media/{req_id}/01_picker.html", params={"token": token})
    assert 'href="/"' in resp.text and "Portal</a>" in resp.text
    assert 'href="/s/' in resp.text  # stream crumb
    assert ">open<" in resp.text  # status chip for an open request
    # Graceful: no metadata means no Step:/Ask: labels leak in.
    assert "Step:" not in resp.text and "Ask:" not in resp.text

    # Report branch: home link + stream, and NO status chip (reports have no status).
    resp = client.post(
        "/api/streams/reports/posts",
        data={"type": "report", "title": "r", "author": "a"},
        files=[("files", ("report.html", b"<html><body><p>hi</p></body></html>", "text/html"))],
        headers=auth_headers(token),
    )
    post_id = resp.json()["post"]["id"]
    resp = client.get(f"/media/{post_id}/01_report.html", params={"token": token})
    assert 'href="/"' in resp.text and "Portal</a>" in resp.text
    assert 'href="/s/reports"' in resp.text
    assert ">open<" not in resp.text and "Step:" not in resp.text


def test_view_header_shows_step_ask_and_status(client, token):
    resp = client.post(
        "/api/requests",
        data={
            "title": "Pick frames",
            "kind": "view",
            "step": "frame picking",
            "ask": "pick the winning frame",
            "purpose": "choose the hero shot",
        },
        files=[("files", ("picker.html", VIEW_HTML, "text/html"))],
        headers=auth_headers(token),
    )
    req_id = resp.json()["id"]
    assert db.get_request(req_id)["step"] == "frame picking"
    assert db.get_request(req_id)["ask"] == "pick the winning frame"

    page = client.get(f"/media/{req_id}/01_picker.html", params={"token": token})
    assert "frame picking" in page.text
    assert "pick the winning frame" in page.text
    assert ">open<" in page.text
    # Producer content is preserved alongside the header.
    assert "picker" in page.text


def test_report_header_shows_metadata_without_status(client, token):
    resp = client.post(
        "/api/streams/reports/posts",
        data={
            "type": "report",
            "title": "r",
            "author": "a",
            "body": json.dumps({"step": "render review", "ask": "confirm the cut"}),
        },
        files=[("files", ("report.html", b"<html><body><p>hi</p></body></html>", "text/html"))],
        headers=auth_headers(token),
    )
    post_id = resp.json()["post"]["id"]
    page = client.get(f"/media/{post_id}/01_report.html", params={"token": token})
    assert "render review" in page.text
    assert "confirm the cut" in page.text
    assert ">open<" not in page.text and ">decided<" not in page.text


def test_producer_html_is_byte_preserved_apart_from_header(client, token):
    original = b"<html><body>ORIGINAL PRODUCER BYTES</body></html>"
    resp = client.post(
        "/api/streams/reports/posts",
        data={"type": "report", "title": "r", "author": "a"},
        files=[("files", ("report.html", original, "text/html"))],
        headers=auth_headers(token),
    )
    post_id = resp.json()["post"]["id"]
    served = client.get(f"/media/{post_id}/01_report.html", params={"token": token}).content
    # The header fragment is injected once, right after the opening <body> tag;
    # stripping exactly that fragment reproduces the original file bytes.
    seam = original.index(b"<body>") + len(b"<body>")
    assert served[:seam] == original[:seam]
    assert served.endswith(original[seam:])
    fragment = served[seam : len(served) - (len(original) - seam)]
    assert served == original[:seam] + fragment + original[seam:]
    assert served.count(b"Portal</a>") == 1


def test_header_injection_without_body_tag_keeps_doctype_first(client, token):
    # A valid HTML page with no explicit <body> tag: the header must land AFTER
    # the doctype, never before it (content before <!doctype> forces quirks mode).
    original = b"<!DOCTYPE html>\n<p>bare report</p>"
    resp = client.post(
        "/api/streams/reports/posts",
        data={"type": "report", "title": "r", "author": "a"},
        files=[("files", ("report.html", original, "text/html"))],
        headers=auth_headers(token),
    )
    post_id = resp.json()["post"]["id"]
    served = client.get(f"/media/{post_id}/01_report.html", params={"token": token}).content
    assert served.startswith(b"<!DOCTYPE html>")
    assert served.count(b"Portal</a>") == 1
    assert served.endswith(b"<p>bare report</p>")


def test_report_header_metadata_is_bounded_and_coerced(client, token):
    # Report body_json is arbitrary JSON: non-string metadata must be dropped
    # (never rendered as a Python repr) and oversized strings truncated.
    huge = "y" * 5000
    resp = client.post(
        "/api/streams/reports/posts",
        data={
            "type": "report",
            "title": "r",
            "author": "a",
            "body": json.dumps({"step": {"nested": 1}, "ask": huge}),
        },
        files=[("files", ("report.html", b"<html><body><p>hi</p></body></html>", "text/html"))],
        headers=auth_headers(token),
    )
    post_id = resp.json()["post"]["id"]
    page = client.get(f"/media/{post_id}/01_report.html", params={"token": token})
    assert "nested" not in page.text  # dict dropped, no repr leak
    assert "y" * server.MAX_TITLE_LENGTH in page.text  # bounded, not blanked
    assert "y" * (server.MAX_TITLE_LENGTH + 1) not in page.text
