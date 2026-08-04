import re


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def tiny_png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000100ffff03000006000557bfabd4000000"
        "0049454e44ae426082"
    )


def _variant_uploads(n=2):
    return [("files", (f"after-{i}.png", tiny_png_bytes(), "image/png")) for i in range(1, n + 1)]


def _create_request(client, token, *, kind="pick-one", before=True, variants=2, project=None):
    files = []
    if before:
        files.append(("before", ("before.png", tiny_png_bytes(), "image/png")))
    files.extend(_variant_uploads(variants))
    data = {"title": f"{kind} before", "kind": kind}
    if project is not None:
        data["project"] = project
    create = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data=data,
        files=files,
    )
    assert create.status_code == 200
    return create.json()["id"]


def _selectable_variant_indices(html):
    return re.findall(r'class="variant" data-idx="(\d+)"', html)


def test_before_request_renders_before_block_switcher_and_non_selectable_baseline(client, token):
    req_id = _create_request(client, token, kind="pick-one", before=True, variants=2)

    page = client.get(f"/r/{req_id}?token={token}")

    assert page.status_code == 200
    assert 'data-before-default-view="side-by-side"' in page.text
    assert 'class="before-after-review" data-before-review data-mode="side-by-side"' in page.text
    assert 'class="before-side-by-side" data-before-block data-side-by-side' in page.text
    assert '<div class="before-card">' in page.text
    assert '<div class="before-card after-card">' in page.text
    assert "AFTER 1" in page.text
    assert "AFTER 2" in page.text
    assert "BEFORE" in page.text
    assert f'/media/{req_id}/__before.png?token=' in page.text
    assert 'role="group" aria-label="Before after view"' in page.text
    assert 'data-before-view="side-by-side" aria-pressed="true"' in page.text
    assert 'data-before-view="toggle" aria-pressed="false"' in page.text
    assert 'class="toggle-view" data-before-toggle hidden' in page.text
    assert 'class="toggle-frame" data-toggle-frame tabindex="0" role="button" aria-pressed="false"' in page.text
    assert 'data-toggle-candidate="1"' in page.text
    assert 'data-toggle-candidate="2"' in page.text

    before_region = page.text[page.text.index("data-before-block") : page.text.index("data-candidate-grid")]
    side_by_side_region = page.text[page.text.index("data-before-block") : page.text.index('class="toggle-view"')]
    assert 'class="variant"' not in before_region
    assert "data-idx=" not in before_region
    assert "tabindex=" not in side_by_side_region
    assert 'role="button"' not in side_by_side_region
    assert page.text.index("data-before-block") < page.text.index('class="variant" data-idx="1"')
    assert _selectable_variant_indices(page.text) == ["1", "2"]
    assert 'class="variant" data-idx="1" tabindex="0" role="button" aria-pressed="false"' in page.text

    detail = client.get(f"/api/requests/{req_id}", headers=auth_headers(token))
    assert detail.status_code == 200
    assert [v["idx"] for v in detail.json()["variants"]] == [1, 2]


def test_before_after_kind_defaults_to_toggle_and_uses_variant_verdicts(client, token):
    req_id = _create_request(client, token, kind="before-after", before=True, variants=2)

    page = client.get(f"/r/{req_id}?token={token}")

    assert page.status_code == 200
    assert 'data-kind="before-after"' in page.text
    assert 'data-before-default-view="toggle"' in page.text
    assert 'data-before-view="side-by-side" aria-pressed="false"' in page.text
    assert 'data-before-view="toggle" aria-pressed="true"' in page.text
    assert 'class="before-side-by-side" data-before-block data-side-by-side hidden' in page.text
    assert 'class="toggle-view" data-before-toggle>' in page.text
    assert _selectable_variant_indices(page.text) == ["1", "2"]

    invalid = client.post(f"/r/{req_id}/decide?token={token}", json={"selected": [0]})
    assert invalid.status_code == 400
    assert "selected indices not found" in invalid.json()["detail"]

    decided = client.post(f"/r/{req_id}/decide?token={token}", json={"selected": [1]})
    assert decided.status_code == 200
    detail = client.get(f"/api/requests/{req_id}", headers=auth_headers(token))
    assert detail.json()["status"] == "decided"
    assert detail.json()["verdict"]["selected"] == [1]


def test_request_without_before_keeps_existing_key_markup(client, token):
    req_id = _create_request(client, token, kind="pick-one", before=False, variants=1)

    page = client.get(f"/r/{req_id}?token={token}")

    assert page.status_code == 200
    assert (
        f'<section class="request-detail" data-req-id="{req_id}" data-kind="pick-one" data-status="open">'
        in page.text
    )
    assert '<div class="variant-grid" style="--variant-cols: 1">' in page.text
    assert '<div class="variant" data-idx="1">' in page.text
    assert '<div class="decision-panel">' in page.text
    assert '<button type="button" class="btn decide" id="decide-btn">Decide</button>' in page.text
    assert _selectable_variant_indices(page.text) == ["1"]
    assert "data-before-default-view" not in page.text
    assert "before-after-review" not in page.text
    assert "data-before-review" not in page.text
    assert "data-before-view" not in page.text
    assert "data-before-toggle" not in page.text
    assert "data-toggle-frame" not in page.text
    assert "BEFORE" not in page.text


def test_before_request_non_selecting_kinds_do_not_render_inert_candidate_buttons(client, token):
    req_id = _create_request(client, token, kind="approve", before=True, variants=1)

    page = client.get(f"/r/{req_id}?token={token}")

    assert page.status_code == 200
    assert 'data-before-default-view="side-by-side" data-can-decide="true"' in page.text
    assert '<div class="variant" data-idx="1">' in page.text
    assert 'data-idx="1" tabindex=' not in page.text
    assert 'data-idx="1" role="button"' not in page.text
    assert 'data-idx="1" aria-pressed=' not in page.text
    assert '<button type="button" class="btn approve" data-approve="yes">Approve</button>' in page.text


def test_before_request_in_closed_stream_is_not_selectable(client, token):
    req_id = _create_request(
        client,
        token,
        kind="before-after",
        before=True,
        variants=1,
        project="closed/project",
    )
    close = client.post("/api/streams/proj-closed-project/close", headers=auth_headers(token))
    assert close.status_code == 200

    page = client.get(f"/r/{req_id}?token={token}")

    assert page.status_code == 200
    assert "Archived stream. This request is read-only." in page.text
    assert 'data-before-default-view="toggle" data-can-decide="false"' in page.text
    assert '<div class="variant" data-idx="1">' in page.text
    assert 'data-idx="1" tabindex=' not in page.text
    assert 'data-idx="1" role="button"' not in page.text
    assert 'data-idx="1" aria-pressed=' not in page.text
    assert '<div class="decision-panel">' not in page.text


def test_static_js_keeps_before_after_pick_one_and_persistent_toggle_hooks(client):
    script = client.get("/static/app.js")

    assert script.status_code == 200
    assert '"before-after": true' in script.text
    assert "data-before-review" in script.text
    assert "data-toggle-frame" in script.text
    assert "show-before" in script.text
    assert "keydown" in script.text
    assert "event.key !== \" \"" in script.text
    assert "activeToggleIdx" in script.text
    assert "toggleBeforeFrame" in script.text
    assert 'event.target.closest("video")' in script.text
    assert "event.target !== toggleFrame" in script.text
    assert 'event.key !== "Enter"' in script.text
    assert 'toggleFrame.setAttribute("aria-pressed", showBefore ? "true" : "false")' in script.text
    assert '"Showing after. Activate to show before"' in script.text
    assert "setToggleShowingBefore(false)" in script.text
    assert "blinkToggleFrame" not in script.text
    assert "blinkTimer" not in script.text
    assert "pauseVideos(root)" in script.text
    assert "syncActiveToggleIdx(idxOf(el))" in script.text
    assert "isToggleMode() && pickOneKinds[kind] && pos !== -1" in script.text
    assert 'event.target.closest && event.target.closest("a")' in script.text
    assert "event.target !== el" in script.text
    assert 'section.dataset.canDecide === "false"' in script.text


def test_static_js_renders_decide_409_dict_detail(client):
    # P5b made the decide 409 detail a dict; the decide handler must normalize it to a
    # readable string (not "[object Object]") while passing plain-string details through.
    script = client.get("/static/app.js")

    assert script.status_code == 200
    # the throw routes through the normalizer, not raw interpolation of err.detail
    assert "decideErrorMessage(err.detail)" in script.text
    # string details pass through verbatim
    assert 'typeof detail === "string"' in script.text
    # each known dict shape and the human field it renders
    assert '"verdict_exists"' in script.text
    assert "detail.verdict_count" in script.text
    assert '"superseded"' in script.text
    assert "detail.successor" in script.text
    assert '"closed"' in script.text
    assert "detail.reason" in script.text
