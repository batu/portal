import json


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def tiny_png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000100ffff03000006000557bfabd4000000"
        "0049454e44ae426082"
    )


def content_disposition_type(response) -> str:
    return response.headers.get("content-disposition", "").split(";", 1)[0].strip().lower()


def assert_report_html_inline(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox allow-same-origin"
    assert "allow-scripts" not in response.headers["content-security-policy"]
    assert content_disposition_type(response) != "attachment"


def assert_html_attachment(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in response.headers
    assert content_disposition_type(response) == "attachment"


def test_portal_phase1_report_decision_verdict_and_archive_flow(client, token):
    project = "portal/phase1-e2e"
    slug = "proj-portal-phase1-e2e"

    report = client.post(
        f"/api/streams/{slug}/posts",
        headers=auth_headers(token),
        data={
            "type": "report",
            "title": "Portal phase 1 report",
            "author": "codex",
            "body": json.dumps({"summary": "report pushes auto-create streams"}),
        },
        files=[
            (
                "files",
                (
                    "portal-report.html",
                    b"<html><body><h1>Portal Report Rendered</h1></body></html>",
                    "text/html",
                ),
            )
        ],
    )
    assert report.status_code == 200
    report_post = report.json()["post"]
    report_media_path = report_post["body"]["files"][0]["media_path"]
    report_media_url = f"/media/{report_post['id']}/{report_media_path}"

    created_stream = client.get(f"/api/streams/{slug}", headers=auth_headers(token))
    assert created_stream.status_code == 200
    assert created_stream.json()["slug"] == slug
    assert created_stream.json()["kind"] == "session"
    assert [post["id"] for post in created_stream.json()["posts"]] == [report_post["id"]]

    report_stream_page = client.get(f"/s/{slug}?token={token}")
    assert report_stream_page.status_code == 200
    assert "Portal phase 1 report" in report_stream_page.text
    assert f'href="{report_media_url}"' in report_stream_page.text
    assert f'src="{report_media_url}"' in report_stream_page.text
    assert 'sandbox="allow-same-origin"' in report_stream_page.text
    assert "allow-scripts" not in report_stream_page.text
    assert "token=" not in report_stream_page.text

    report_media = client.get(report_media_url)
    assert_report_html_inline(report_media)
    assert b"Portal Report Rendered" in report_media.content

    request = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={
            "title": "Portal phase 1 before after",
            "kind": "before-after",
            "project": project,
            "context": "Choose the after state that best matches the report.",
        },
        files=[
            ("before", ("before.png", tiny_png_bytes(), "image/png")),
            ("files", ("after-1.png", tiny_png_bytes(), "image/png")),
            (
                "files",
                (
                    "after-2.html",
                    b"<html><body><h1>HTML variant must download</h1></body></html>",
                    "text/html",
                ),
            ),
        ],
    )
    assert request.status_code == 200
    req_id = request.json()["id"]

    request_detail = client.get(f"/api/requests/{req_id}", headers=auth_headers(token))
    assert request_detail.status_code == 200
    request_payload = request_detail.json()
    assert request_payload["project"] == project
    assert request_payload["kind"] == "before-after"
    assert [variant["idx"] for variant in request_payload["variants"]] == [1, 2]

    stream_with_request = client.get(f"/api/streams/{slug}", headers=auth_headers(token))
    assert stream_with_request.status_code == 200
    stream_posts = stream_with_request.json()["posts"]
    assert any(post["type"] == "report" and post["id"] == report_post["id"] for post in stream_posts)
    assert any(post["type"] == "decision" and post["body"] == {"request_id": req_id} for post in stream_posts)

    pending_stream_page = client.get(f"/s/{slug}")
    assert pending_stream_page.status_code == 200
    assert "Portal phase 1 before after" in pending_stream_page.text
    assert f'href="/r/{req_id}"' in pending_stream_page.text
    assert '<span class="status-badge pending">pending</span>' in pending_stream_page.text

    request_page = client.get(f"/r/{req_id}")
    assert request_page.status_code == 200
    assert 'class="request-detail"' in request_page.text
    assert 'data-kind="before-after"' in request_page.text
    assert 'data-before-default-view="toggle"' in request_page.text
    assert 'class="before-after-review" data-before-review data-mode="toggle"' in request_page.text
    assert "BEFORE" in request_page.text
    assert "data-candidate-grid" in request_page.text
    assert 'class="variant" data-idx="1"' in request_page.text
    assert 'class="variant" data-idx="2"' in request_page.text
    assert 'data-toggle-candidate="1"' in request_page.text
    assert 'data-toggle-candidate="2"' in request_page.text

    html_variant_path = request_payload["variants"][1]["media_path"]
    html_variant_media = client.get(f"/media/{req_id}/{html_variant_path}")
    assert_html_attachment(html_variant_media)

    decision_file_post = client.post(
        f"/api/streams/{slug}/posts",
        headers=auth_headers(token),
        data={
            "type": "decision",
            "title": "Decision post with HTML file",
            "author": "codex",
            "body": json.dumps({"request_id": req_id, "note": "files on decision posts are never inline"}),
        },
        files=[
            (
                "files",
                (
                    "decision.html",
                    b"<html><body><h1>Decision post attachment</h1></body></html>",
                    "text/html",
                ),
            )
        ],
    )
    assert decision_file_post.status_code == 200
    decision_post = decision_file_post.json()["post"]
    decision_media_path = decision_post["body"]["files"][0]["media_path"]
    decision_media = client.get(f"/media/{decision_post['id']}/{decision_media_path}")
    assert_html_attachment(decision_media)

    verdict = client.post(
        f"/r/{req_id}/decide",
        json={"selected": [1], "comment": "Use the first after state."},
    )
    assert verdict.status_code == 200
    assert verdict.json()["selected"] == [1]

    decided_stream_page = client.get(f"/s/{slug}")
    assert decided_stream_page.status_code == 200
    assert '<span class="status-badge decided">decided</span>' in decided_stream_page.text

    close = client.post(f"/api/streams/{slug}/close", headers=auth_headers(token))
    assert close.status_code == 200
    assert close.json()["closed_at"] is not None

    archived_stream_page = client.get(f"/s/{slug}")
    assert archived_stream_page.status_code == 200
    assert "Archived" in archived_stream_page.text
    assert "Archived stream. Posts and decisions are read-only." in archived_stream_page.text

    archived_request_page = client.get(f"/r/{req_id}")
    assert archived_request_page.status_code == 200
    assert "Archived stream. This request is read-only." in archived_request_page.text

    rejected_revision = client.post(
        f"/r/{req_id}/decide",
        json={"selected": [2], "comment": "late change"},
    )
    assert rejected_revision.status_code == 409
    assert "stream is closed" in rejected_revision.json()["detail"]
