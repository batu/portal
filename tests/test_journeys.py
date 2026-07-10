"""Journey primitive: db CRUD (update-in-place), JSON API, and the native
/g/<slug> story-spine page — verified end-to-end against a real-density
wool-crush fixture built from real-structure artifacts."""

import importlib.util
from pathlib import Path

from gallery import config, db


def _load_seed_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "seed_journey_demo.py"
    spec = importlib.util.spec_from_file_location("seed_journey_demo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def tiny_png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000100ffff03000006000557bfabd4000000"
        "0049454e44ae426082"
    )


def _breadcrumb_html(html):
    marker = '<nav class="breadcrumb" aria-label="Breadcrumb">'
    assert marker in html
    start = html.index(marker)
    end = html.index("</nav>", start) + len("</nav>")
    return html[start:end]


def _create_request(client, token, title="Decision source", kind="pick-one"):
    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={"title": title, "kind": kind},
        files=[("files", ("variant.png", tiny_png_bytes(), "image/png"))],
    )
    assert create.status_code == 200
    return create.json()["id"]


def _add_media_post(slug, post_id, title, files):
    """Create a real report post whose media files exist on disk (real structure)."""
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
    db.create_stream(slug, "session", title) if db.get_stream(slug) is None else None
    return db.create_post_for_stream(slug, "report", title, "codex", {"files": body_files}, post_id=post_id)


def _put_journey(client, token, slug, title, steps):
    return client.put(
        f"/api/journeys/{slug}",
        headers=auth_headers(token),
        json={"title": title, "steps": steps},
    )


# --- db CRUD / update-in-place ---


def test_upsert_get_round_trips_doc(data_dir):
    stored = db.upsert_journey("wool-crush", "Wool Crush", {"steps": [{"title": "Watch"}]})
    assert stored["slug"] == "wool-crush"
    assert stored["title"] == "Wool Crush"
    assert stored["doc"] == {"steps": [{"title": "Watch"}]}
    assert stored["created_at"] == stored["updated_at"]

    fetched = db.get_journey("wool-crush")
    assert fetched["doc"] == {"steps": [{"title": "Watch"}]}
    assert db.get_journey("missing") is None


def test_upsert_is_update_in_place_single_row_preserving_created_at(data_dir):
    first = db.upsert_journey(
        "wool-crush", "First", {"steps": [{"title": "One"}]}, created_at="2026-07-01T00:00:00+00:00"
    )
    second = db.upsert_journey("wool-crush", "Second", {"steps": [{"title": "A"}, {"title": "B"}]})

    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM journeys WHERE slug = 'wool-crush'").fetchone()[0] == 1
    assert second["title"] == "Second"
    assert second["doc"] == {"steps": [{"title": "A"}, {"title": "B"}]}
    assert second["created_at"] == first["created_at"] == "2026-07-01T00:00:00+00:00"
    assert second["updated_at"] > first["updated_at"]


def test_list_journeys_orders_by_recency_with_step_count(data_dir):
    db.upsert_journey("older", "Older", {"steps": [{"title": "x"}]}, updated_at="2026-07-01T00:00:00+00:00")
    db.upsert_journey(
        "newer", "Newer", {"steps": [{"title": "a"}, {"title": "b"}, {"title": "c"}]},
        updated_at="2026-07-02T00:00:00+00:00",
    )

    listed = db.list_journeys()
    assert [j["slug"] for j in listed] == ["newer", "older"]
    assert listed[0]["step_count"] == 3
    assert listed[1]["step_count"] == 1


# --- JSON API ---


def test_put_stores_and_get_returns_journey(client, token):
    put = _put_journey(client, token, "wool-crush", "Wool Crush", [{"title": "Watch"}])
    assert put.status_code == 200
    assert put.json()["doc"] == {"steps": [{"title": "Watch"}]}

    got = client.get("/api/journeys/wool-crush", headers=auth_headers(token))
    assert got.status_code == 200
    assert got.json()["title"] == "Wool Crush"


def test_put_same_slug_replaces_content_update_in_place(client, token):
    _put_journey(client, token, "wool-crush", "First", [{"title": "One"}])
    _put_journey(client, token, "wool-crush", "Second", [{"title": "A"}, {"title": "B"}])

    got = client.get("/api/journeys/wool-crush", headers=auth_headers(token))
    assert got.json()["title"] == "Second"
    assert [s["title"] for s in got.json()["doc"]["steps"]] == ["A", "B"]

    listed = client.get("/api/journeys", headers=auth_headers(token)).json()
    assert [j["slug"] for j in listed] == ["wool-crush"]
    assert listed[0]["step_count"] == 2


def test_get_unknown_journey_is_404(client, token):
    assert client.get("/api/journeys/nope", headers=auth_headers(token)).status_code == 404


def test_journey_api_requires_bearer_token(client, token):
    assert client.put("/api/journeys/wool-crush", json={"title": "T", "steps": []}).status_code == 401
    assert client.get("/api/journeys/wool-crush").status_code == 401
    assert client.get("/api/journeys").status_code == 401


def test_put_rejects_malformed_slug(client, token):
    assert _put_journey(client, token, "Bad Slug", "T", []).status_code == 400
    assert _put_journey(client, token, "trailing-", "T", []).status_code == 400


def test_put_rejects_malformed_docs(client, token):
    # steps not a list
    assert client.put(
        "/api/journeys/wool-crush", headers=auth_headers(token), json={"title": "T", "steps": {}}
    ).status_code == 400
    # step missing title
    assert _put_journey(client, token, "wool-crush", "T", [{"summary": "no title"}]).status_code == 400
    # media owner_id with a path separator
    assert _put_journey(
        client, token, "wool-crush", "T", [{"title": "s", "media": [{"owner_id": "a/b", "filename": "x.png"}]}]
    ).status_code == 400
    # unsafe media filename
    assert _put_journey(
        client, token, "wool-crush", "T", [{"title": "s", "media": [{"owner_id": "p_1", "filename": "../secret"}]}]
    ).status_code == 400
    # bad request_id
    assert _put_journey(
        client, token, "wool-crush", "T", [{"title": "s", "request_id": "no spaces"}]
    ).status_code == 400
    # title required
    assert client.put(
        "/api/journeys/wool-crush", headers=auth_headers(token), json={"steps": []}
    ).status_code == 400


def test_put_drops_unknown_keys_and_normalizes(client, token):
    put = _put_journey(
        client, token, "wool-crush", "T",
        [{"title": "Step", "summary": "  hi  ", "bogus": "x", "media": [{"owner_id": "p_1", "filename": "a.png", "junk": 1}]}],
    )
    assert put.status_code == 200
    step = put.json()["doc"]["steps"][0]
    assert step == {"title": "Step", "summary": "hi", "media": [{"owner_id": "p_1", "filename": "a.png"}]}


# --- /g/<slug> web page ---


def test_journey_page_requires_web_token_and_sets_cookie(client, token):
    _put_journey(client, token, "wool-crush", "Wool Crush", [{"title": "Watch"}])

    missing = client.get("/g/wool-crush", follow_redirects=False)
    ok = client.get(f"/g/wool-crush?token={token}", follow_redirects=False)
    cookie_ok = client.get("/g/wool-crush", follow_redirects=False)
    unknown = client.get(f"/g/does-not-exist?token={token}", follow_redirects=False)

    assert missing.status_code == 303
    assert missing.headers["location"].startswith("/login")
    assert ok.status_code == 200
    assert "gallery_token" in ok.cookies
    assert ok.headers["referrer-policy"] == "no-referrer"
    assert cookie_ok.status_code == 200
    assert unknown.status_code == 404


def test_journey_page_renders_breadcrumb_and_ordered_steps(client, token):
    _add_media_post("wool-crush", "p_video", "Proxy video", [("proxy.mp4", "video/mp4", b"\x00\x00mp4")])
    _put_journey(
        client, token, "wool-crush", "Wool Crush",
        [
            {"title": "Watch the proxy", "media": [{"owner_id": "p_video", "filename": "proxy.mp4"}]},
            {"title": "Pick the frames", "summary": "Choose the best keyframes."},
        ],
    )

    page = client.get(f"/g/wool-crush?token={token}")

    assert page.status_code == 200
    assert '<a href="/" class="brand">Portal</a>' in page.text
    breadcrumb = _breadcrumb_html(page.text)
    assert '<a href="/">Index</a>' in breadcrumb
    assert '<span aria-current="page">Wool Crush</span>' in breadcrumb
    assert page.text.index("Watch the proxy") < page.text.index("Pick the frames")
    assert 'src="/media/p_video/proxy.mp4?token=' in page.text
    assert "<video" in page.text
    assert "Choose the best keyframes." in page.text


def test_journey_page_shows_live_request_status(client, token):
    req_id = _create_request(client, token, title="Frame picker")
    _put_journey(client, token, "wool-crush", "Wool Crush", [{"title": "Pick", "request_id": req_id}])

    page = client.get(f"/g/wool-crush?token={token}")
    assert f'href="/r/{req_id}"' in page.text
    assert '<span class="journey-chip open">open</span>' in page.text

    decide = client.post(f"/api/requests/{req_id}/verdict", headers=auth_headers(token), json={"selected": [1]})
    assert decide.status_code == 200

    decided_page = client.get("/g/wool-crush")
    assert '<span class="journey-chip decided">decided</span>' in decided_page.text
    assert "journey-chip open" not in decided_page.text


def test_journey_page_dangling_request_renders_without_500(client, token):
    _put_journey(client, token, "wool-crush", "Wool Crush", [{"title": "Ghost", "request_id": "req_gone"}])

    page = client.get(f"/g/wool-crush?token={token}")
    assert page.status_code == 200
    assert 'href="/r/req_gone"' in page.text
    assert '<span class="journey-chip unknown">unknown</span>' in page.text


def test_journey_link_media_caption_renders_once_embed_caption_kept(client, token):
    _add_media_post(
        "wool-crush", "p_mixed", "Artifacts",
        [("report.html", "text/html", b"<html></html>"), ("still.png", "image/png", tiny_png_bytes())],
    )
    _put_journey(
        client, token, "wool-crush", "Wool Crush",
        [{"title": "Read the artifacts", "media": [
            {"owner_id": "p_mixed", "filename": "report.html", "caption": "Style report"},
            {"owner_id": "p_mixed", "filename": "still.png", "caption": "Chosen still"},
        ]}],
    )

    page = client.get(f"/g/wool-crush?token={token}")
    assert page.status_code == 200
    # Link media: the caption IS the visible link label — no duplicate figcaption.
    assert page.text.count("Style report") == 1
    assert '<figcaption class="journey-caption">Style report</figcaption>' not in page.text
    # Embedded media keeps its figcaption (its label only lands in alt text).
    assert '<figcaption class="journey-caption">Chosen still</figcaption>' in page.text


def test_journey_page_escapes_producer_text(client, token):
    _put_journey(client, token, "wool-crush", "Wool Crush", [{"title": "<script>alert(1)</script>"}])

    page = client.get(f"/g/wool-crush?token={token}")
    assert page.status_code == 200
    assert "<script>alert(1)</script>" not in page.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text


def test_index_links_existing_journeys(client, token):
    empty = client.get(f"/?token={token}")
    assert "Journeys (0)" in empty.text
    assert "No journeys yet." in empty.text

    _put_journey(client, token, "wool-crush", "Wool Crush", [{"title": "Watch"}, {"title": "Pick"}])

    page = client.get("/")
    assert "Journeys (1)" in page.text
    assert 'href="/g/wool-crush"' in page.text
    assert "2 steps" in page.text


# --- real-density wool-crush fixture (AE8) ---


def _seed_wool_crush(client, token):
    """Build real-structure artifacts (video post, two HTML report posts, two
    requests), then post a wool-crush journey referencing them. Returns the ids."""
    _add_media_post("wool-crush", "p_video", "Proxy video", [("proxy.mp4", "video/mp4", b"\x00\x00\x00mp4")])
    _add_media_post("wool-crush", "p_style", "Style report", [("style.html", "text/html", b"<html><body>style</body></html>")])
    _add_media_post("wool-crush", "p_assets", "Asset sheet", [("assets.html", "text/html", b"<html><body>assets</body></html>")])
    frame_picker = _create_request(client, token, title="Frame picker")
    token_promo = _create_request(client, token, title="Token promotion")

    steps = [
        {"title": "Watch the proxy render", "summary": "The 32MB proxy, referenced — not re-uploaded.",
         "media": [{"owner_id": "p_video", "filename": "proxy.mp4", "caption": "Proxy render"}]},
        {"title": "Pick the frames", "summary": "Choose the keyframes that define the look.",
         "request_id": frame_picker},
        {"title": "Review the style", "summary": "Palette + rendering direction.",
         "media": [{"owner_id": "p_style", "filename": "style.html", "caption": "Style report p_f6d5b8"}]},
        {"title": "Lay out the asset sheet",
         "media": [{"owner_id": "p_assets", "filename": "assets.html", "caption": "Asset sheet p_d7b881"}]},
        {"title": "Promote the tokens", "request_id": token_promo},
    ]
    resp = _put_journey(client, token, "wool-crush", "Wool Crush", steps)
    assert resp.status_code == 200
    return {"frame_picker": frame_picker, "token_promo": token_promo}


def test_wool_crush_fixture_renders_all_five_steps_end_to_end(client, token):
    ids = _seed_wool_crush(client, token)

    page = client.get(f"/g/wool-crush?token={token}")
    assert page.status_code == 200

    # Five steps, in order.
    order = [
        "Watch the proxy render",
        "Pick the frames",
        "Review the style",
        "Lay out the asset sheet",
        "Promote the tokens",
    ]
    positions = [page.text.index(title) for title in order]
    assert positions == sorted(positions)

    # Video embedded (referenced, not re-uploaded).
    assert 'src="/media/p_video/proxy.mp4?token=' in page.text
    assert "<video" in page.text
    # Both request links carry live status chips.
    assert f'href="/r/{ids["frame_picker"]}"' in page.text
    assert f'href="/r/{ids["token_promo"]}"' in page.text
    assert page.text.count('class="journey-chip open"') == 2
    # Both report links present (HTML linked, not embedded), captions once each.
    assert 'href="/media/p_style/style.html?token=' in page.text
    assert 'href="/media/p_assets/assets.html?token=' in page.text
    assert page.text.count("Style report p_f6d5b8") == 1
    assert page.text.count("Asset sheet p_d7b881") == 1

    # The referenced video actually serves.
    media = client.get(f"/media/p_video/proxy.mp4?token={token}")
    assert media.status_code == 200


# --- seed demo tooling (data, not Portal logic) ---


def test_seed_script_is_import_clean_and_builds_valid_doc(client, token):
    module = _load_seed_module()
    doc = module.build_wool_crush_doc(
        video_post="p_video",
        video_file="proxy.mp4",
        frame_picker_request="req_frame",
        style_post="p_style",
        style_file="style.html",
        assets_post="p_assets",
        assets_file="assets.html",
        token_promo_request="req_promo",
    )
    assert len(doc["steps"]) == 5
    assert doc["steps"][0]["media"][0]["owner_id"] == "p_video"
    # The producer doc passes the same deterministic validation the API enforces,
    # posted update-in-place at a stable slug.
    put = client.put(
        "/api/journeys/wool-crush-seed", headers=auth_headers(token), json={"title": "Wool Crush", **doc}
    )
    assert put.status_code == 200
    assert len(put.json()["doc"]["steps"]) == 5


def test_seed_script_local_mode_builds_self_contained_demo(data_dir):
    module = _load_seed_module()
    seeded = module._seed_local("wool-crush-demo")
    assert seeded["slug"] == "wool-crush-demo"
    assert len(seeded["doc"]["steps"]) == 2
    assert db.get_journey("wool-crush-demo") is not None
