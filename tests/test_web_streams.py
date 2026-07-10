from gallery import config, db


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def tiny_png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000100ffff03000006000557bfabd4000000"
        "0049454e44ae426082"
    )


def _create_request(client, token, title="Decision source", project=None):
    data = {"title": title, "kind": "pick-one"}
    if project is not None:
        data["project"] = project
    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data=data,
        files=[("files", ("variant.png", tiny_png_bytes(), "image/png"))],
    )
    assert create.status_code == 200
    return create.json()["id"]


def _breadcrumb_html(html):
    marker = '<nav class="breadcrumb" aria-label="Breadcrumb">'
    assert marker in html
    start = html.index(marker)
    end = html.index("</nav>", start) + len("</nav>")
    return html[start:end]


def _add_report_post(slug, post_id, title, created_at, filename="report.html"):
    return _add_report_post_files(
        slug,
        post_id,
        title,
        created_at,
        [(filename, "text/html", f"<html><body>{title}</body></html>".encode())],
    )


def _add_report_post_files(slug, post_id, title, created_at, files):
    media_dir = config.media_dir() / post_id
    media_dir.mkdir(parents=True)
    body_files = []
    for filename, media_type, content in files:
        (media_dir / filename).write_bytes(content)
        body_files.append(
            {
                "media_path": filename,
                "media_type": media_type,
                "size": len(content),
                "original_name": filename,
            }
        )
    return db.create_post_for_stream(
        slug,
        "report",
        title,
        "codex",
        {"files": body_files},
        created_at=created_at,
        post_id=post_id,
    )


def test_stream_page_requires_web_token_and_sets_cookie(client, token):
    db.create_stream("alpha", "session", "Alpha stream")

    missing = client.get("/s/alpha", follow_redirects=False)
    invalid = client.get("/s/alpha?token=wrong", follow_redirects=False)
    ok = client.get(f"/s/alpha?token={token}", follow_redirects=False)
    cookie_ok = client.get("/s/alpha", follow_redirects=False)
    unknown = client.get(f"/s/missing?token={token}", follow_redirects=False)

    assert missing.status_code == 303
    assert missing.headers["location"].startswith("/login")
    assert invalid.status_code == 303
    assert ok.status_code == 200
    assert "gallery_token" in ok.cookies
    assert ok.headers["referrer-policy"] == "no-referrer"
    assert cookie_ok.status_code == 200
    assert unknown.status_code == 404


def test_stream_page_renders_index_breadcrumb_and_brand_link(client, token):
    db.create_stream("alpha", "session", "Alpha stream")

    page = client.get(f"/s/alpha?token={token}")

    assert page.status_code == 200
    assert '<a href="/" class="brand">Portal</a>' in page.text
    breadcrumb = _breadcrumb_html(page.text)
    assert '<a href="/">Index</a>' in breadcrumb
    assert '<span aria-current="page">Alpha stream</span>' in breadcrumb
    assert "token=" not in breadcrumb
    assert "&larr; Home" not in page.text


def test_request_page_renders_index_stream_breadcrumb_and_brand_link(client, token):
    project = "navigation/project"
    stream_slug = db._stream_slug_for_project(project)
    db.create_stream(stream_slug, "session", "Navigation stream")
    req_id = _create_request(client, token, title="Breadcrumb request", project=project)

    page = client.get(f"/r/{req_id}?token={token}")

    assert page.status_code == 200
    assert '<a href="/" class="brand">Portal</a>' in page.text
    breadcrumb = _breadcrumb_html(page.text)
    index_crumb = '<a href="/">Index</a>'
    stream_crumb = f'<a href="/s/{stream_slug}">Navigation stream</a>'
    request_crumb = '<span aria-current="page">Breadcrumb request</span>'
    assert index_crumb in breadcrumb
    assert stream_crumb in breadcrumb
    assert request_crumb in breadcrumb
    assert breadcrumb.index(index_crumb) < breadcrumb.index(stream_crumb) < breadcrumb.index(request_crumb)
    assert "token=" not in breadcrumb
    assert f'<a class="back-link" href="/s/{stream_slug}">' not in page.text


def test_request_page_without_stream_uses_index_request_breadcrumb(client, token):
    req_id = _create_request(client, token, title="Legacy request")
    conn = db.connect()
    conn.execute("UPDATE requests SET stream_id = NULL WHERE id = ?", (req_id,))
    conn.commit()

    page = client.get(f"/r/{req_id}?token={token}")

    assert page.status_code == 200
    breadcrumb = _breadcrumb_html(page.text)
    assert breadcrumb.count('<a href="/">Index</a>') == 1
    assert '<span aria-current="page">Legacy request</span>' in breadcrumb
    assert 'href="/s/' not in breadcrumb
    assert "Home" not in breadcrumb
    assert "token=" not in breadcrumb


def test_stream_page_renders_report_and_decision_posts_newest_first(client, token):
    db.create_stream("alpha", "session", "Alpha stream")
    report = _add_report_post("alpha", "p_report", "Report pass", "2026-07-08T09:00:00+00:00")
    req_id = _create_request(client, token)
    db.create_post_for_stream(
        "alpha",
        "decision",
        "Decision mirror",
        "codex",
        {"request_id": req_id},
        created_at="2026-07-08T10:00:00+00:00",
        post_id="p_decision",
    )

    page = client.get(f"/s/alpha?token={token}")
    media_url = f"/media/{report['id']}/report.html"

    assert page.status_code == 200
    assert page.text.index("Decision mirror") < page.text.index("Report pass")
    assert "Report pass" in page.text
    assert f'href="{media_url}"' in page.text
    assert f'src="{media_url}"' in page.text
    assert 'sandbox="allow-same-origin"' in page.text
    assert "allow-scripts" not in page.text
    assert f'href="/r/{req_id}"' in page.text
    assert '<span class="status-badge pending">pending</span>' in page.text
    assert "token=" not in page.text

    media = client.get(media_url)
    assert media.status_code == 200
    assert media.headers["x-content-type-options"] == "nosniff"
    # Producer HTML is served with the context header injected right after the
    # opening <body> tag, so the round-trip is original-plus-header at a single
    # seam, not byte-identical. The original content survives intact.
    assert media.content.startswith(b"<html><body>")
    assert media.content.endswith(b"Report pass</body></html>")
    assert b'href="/"' in media.content and b"Portal</a>" in media.content
    assert "attachment" not in media.headers.get("content-disposition", "")

    decide = client.post(f"/api/requests/{req_id}/verdict", headers=auth_headers(token), json={"selected": [1]})
    assert decide.status_code == 200
    decided_page = client.get("/s/alpha")
    assert '<span class="status-badge decided">decided</span>' in decided_page.text


def test_stream_report_prefers_html_file_for_iframe(client, token):
    db.create_stream("multi-file", "session", "Multi-file stream")
    _add_report_post_files(
        "multi-file",
        "p_multi_file",
        "Bundle report",
        "2026-07-08T09:00:00+00:00",
        [
            ("notes.txt", "text/plain", b"notes"),
            ("report.html", "text/html", b"<html><body>report</body></html>"),
        ],
    )

    page = client.get(f"/s/multi-file?token={token}")

    assert page.status_code == 200
    assert 'href="/media/p_multi_file/report.html"' in page.text
    assert 'src="/media/p_multi_file/report.html"' in page.text
    assert "/media/p_multi_file/notes.txt" not in page.text


def test_report_html_media_is_inline_but_html_variant_stays_attachment(client, token):
    db.create_stream("inline-report", "session", "Inline report stream")
    report = _add_report_post(
        "inline-report",
        "p_inline_report",
        "Inline report",
        "2026-07-08T09:00:00+00:00",
    )
    variant = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": "HTML variant", "kind": "pick-one"},
        files=[("files", ("variant.html", b"<html><body>variant</body></html>", "text/html"))],
    )
    assert variant.status_code == 200
    req_id = variant.json()["id"]
    request_body = db.get_request(req_id)
    variant_path = request_body["variants"][0]["media_path"]

    report_media = client.get(f"/media/{report['id']}/report.html?token={token}")
    variant_media = client.get(f"/media/{req_id}/{variant_path}?token={token}")

    assert report_media.status_code == 200
    assert report_media.headers["content-type"].startswith("text/html")
    assert report_media.headers["x-content-type-options"] == "nosniff"
    assert report_media.headers["content-security-policy"] == "sandbox allow-same-origin"
    assert "allow-scripts" not in report_media.headers["content-security-policy"]
    assert "attachment" not in report_media.headers.get("content-disposition", "")
    assert variant_media.status_code == 200
    assert variant_media.headers["content-type"].startswith("text/html")
    assert variant_media.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in variant_media.headers
    assert "attachment" in variant_media.headers["content-disposition"]


def test_report_html_media_uses_stored_type_and_csp_sandbox(client, token):
    db.create_stream("stored-html", "session", "Stored HTML stream")
    _add_report_post_files(
        "stored-html",
        "p_stored_html",
        "Stored type report",
        "2026-07-08T09:00:00+00:00",
        [
            ("report.bin", "text/html", b"<html><body><script>alert(1)</script></body></html>"),
            ("extension.html", "text/plain", b"<html><body>extension</body></html>"),
            ("html-image.png", "text/html; charset=utf-8", b"<html><body>image name</body></html>"),
        ],
    )

    stored_type = client.get(f"/media/p_stored_html/report.bin?token={token}")
    html_extension = client.get(f"/media/p_stored_html/extension.html?token={token}")
    image_extension = client.get(f"/media/p_stored_html/html-image.png?token={token}")
    cookie_seed = client.get(f"/s/stored-html?token={token}")
    cookie_only = client.get("/media/p_stored_html/report.bin")

    assert cookie_seed.status_code == 200
    assert stored_type.status_code == 200
    assert stored_type.headers["content-type"].startswith("text/html")
    assert stored_type.headers["x-content-type-options"] == "nosniff"
    assert stored_type.headers["content-security-policy"] == "sandbox allow-same-origin"
    assert "allow-scripts" not in stored_type.headers["content-security-policy"]
    assert "attachment" not in stored_type.headers.get("content-disposition", "")
    assert html_extension.status_code == 200
    assert html_extension.headers["content-type"].startswith("text/html")
    assert html_extension.headers["content-security-policy"] == "sandbox allow-same-origin"
    assert "attachment" not in html_extension.headers.get("content-disposition", "")
    assert image_extension.status_code == 200
    assert image_extension.headers["content-type"].startswith("text/html")
    assert image_extension.headers["content-security-policy"] == "sandbox allow-same-origin"
    assert "attachment" not in image_extension.headers.get("content-disposition", "")
    assert cookie_only.status_code == 200
    assert cookie_only.headers["content-security-policy"] == "sandbox allow-same-origin"
    assert "attachment" not in cookie_only.headers.get("content-disposition", "")


def test_non_report_post_html_media_stays_attachment(client, token):
    db.create_stream("decision-files", "session", "Decision files stream")
    req_id = _create_request(client, token)
    media_dir = config.media_dir() / "p_decision_file"
    media_dir.mkdir(parents=True)
    media_body = b"<html><body>decision file</body></html>"
    (media_dir / "decision.html").write_bytes(media_body)
    db.create_post_for_stream(
        "decision-files",
        "decision",
        "Decision with file",
        "codex",
        {
            "request_id": req_id,
            "files": [
                {
                    "media_path": "decision.html",
                    "media_type": "text/html",
                    "size": len(media_body),
                    "original_name": "decision.html",
                }
            ],
        },
        created_at="2026-07-08T09:00:00+00:00",
        post_id="p_decision_file",
    )

    media = client.get(f"/media/p_decision_file/decision.html?token={token}")

    assert media.status_code == 200
    assert media.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in media.headers
    assert "attachment" in media.headers["content-disposition"]


def test_stream_page_handles_archived_empty_and_malformed_posts(client, token):
    db.create_stream("archive", "session", "Archive stream")
    db.create_post_for_stream(
        "archive",
        "report",
        "No files",
        "codex",
        {"files": []},
        created_at="2026-07-08T09:00:00+00:00",
        post_id="p_no_files",
    )
    db.create_post_for_stream(
        "archive",
        "decision",
        "Bad decision",
        "codex",
        {},
        created_at="2026-07-08T10:00:00+00:00",
        post_id="p_bad_decision",
    )
    db.close_stream("archive")
    db.create_stream("empty", "pinned", "Empty stream")

    archived = client.get(f"/s/archive?token={token}")
    empty = client.get(f"/s/empty?token={token}")

    assert archived.status_code == 200
    assert "Archived" in archived.text
    assert "Report media unavailable." in archived.text
    assert "Decision unavailable." in archived.text
    assert "<form" not in archived.text
    assert "textarea" not in archived.text
    assert empty.status_code == 200
    assert "No posts yet." in empty.text


def test_request_page_for_closed_stream_is_read_only(client, token):
    req_id = _create_request(client, token, title="Closed request")
    closed = client.post("/api/streams/inbox/close", headers=auth_headers(token))
    assert closed.status_code == 200

    stream_page = client.get(f"/s/inbox?token={token}")
    request_page = client.get(f"/r/{req_id}")

    assert stream_page.status_code == 200
    assert "Archived" in stream_page.text
    assert f'href="/r/{req_id}"' in stream_page.text
    assert request_page.status_code == 200
    assert "Archived stream. This request is read-only." in request_page.text
    assert "comment-box" not in request_page.text
    assert "decide-btn" not in request_page.text


def test_index_lists_streams_section(client, token):
    empty = client.get(f"/?token={token}")
    assert empty.status_code == 200
    assert "Streams (0)" in empty.text
    assert "No streams yet." in empty.text

    db.create_stream("older", "pinned", "Older stream")
    _add_report_post("older", "p_older", "Older report", "2026-01-01T00:00:00+00:00")
    db.create_stream("newer", "session", "Newer stream")
    _add_report_post("newer", "p_newer_one", "Newer report one", "2026-01-02T00:00:00+00:00")
    _add_report_post("newer", "p_newer_two", "Newer report two", "2026-01-03T00:00:00+00:00")
    db.close_stream("newer")

    page = client.get("/")

    assert page.status_code == 200
    assert "Streams (2)" in page.text
    assert page.text.index("Newer stream") < page.text.index("Older stream")
    assert 'href="/s/newer"' in page.text
    assert 'href="/s/older"' in page.text
    assert "session" in page.text
    assert "pinned" in page.text
    assert "2 posts" in page.text
    assert "1 post" in page.text
    assert "latest" in page.text
    assert "Archived" in page.text
    assert "Open (" in page.text
    assert "Decided (" in page.text
