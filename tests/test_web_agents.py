import threading
from concurrent.futures import ThreadPoolExecutor

from gallery import agents, db, server


LIVE_AGENT = {
    "provider": "codex",
    "sid": "sid-live",
    "label": "portal-main",
    "project": "portal",
    "task": "feat/agents",
    "state": "working",
    "freshness_seconds": 4.0,
    "replyable": True,
}


def _seed_cookie(client, token):
    response = client.get(f"/?token={token}")
    assert response.status_code == 200
    return response


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _submission_key(label):
    return f"portal_test_submission_{label}"


def test_agents_page_requires_cookie_and_renders_curated_live_sessions(client, token, monkeypatch):
    monkeypatch.setattr(agents, "list_replyable_agents", lambda: [LIVE_AGENT])

    missing = client.get("/agents", follow_redirects=False)
    page = client.get(f"/agents?token={token}")

    assert missing.status_code == 303
    assert missing.headers["location"].startswith("/login")
    assert page.status_code == 200
    assert '<a href="/agents">Agents</a>' in page.text
    assert "portal-main" in page.text
    assert "feat/agents" in page.text
    assert "data-agent-message-form" in page.text
    assert "Terminal steering" in page.text
    assert "chat" not in page.text.lower()
    assert "token=" not in page.text


def test_agents_page_survives_agency_unavailable_and_keeps_history(client, token, monkeypatch):
    stream = db.create_stream("agent-conversations", "pinned", "Agent conversations")
    message = db.create_targeted_message(stream["id"], "Saved comment", "codex", "sid-old")
    db.claim_message_delivery(message["id"])
    db.complete_message_delivery(message["id"], "failed", "agency_unavailable")

    def unavailable():
        raise agents.AgentBridgeError("Agency is unavailable.")

    monkeypatch.setattr(agents, "list_replyable_agents", unavailable)

    page = client.get(f"/agents?token={token}")

    assert page.status_code == 200
    assert "Agency is unavailable." in page.text
    assert "Saved comment" in page.text
    assert "failed" in page.text
    assert "data-agent-retry-form" in page.text


def test_agent_message_submission_persists_attempt_and_reports_terminal_submission(client, token, monkeypatch):
    _seed_cookie(client, token)
    calls = []

    def submitted(provider, sid, text):
        calls.append((provider, sid, text))
        return {"outcome": "submitted_to_terminal", "detail": "literal_and_enter_sent"}

    monkeypatch.setattr(agents, "submit_to_agent", submitted)

    response = client.post(
        "/agents/codex/sid-live/messages",
        json={"text": "Inspect release flow", "idempotency_key": _submission_key("release")},
    )

    assert response.status_code == 200
    assert response.json()["delivery_state"] == "submitted_to_terminal"
    assert response.json()["consumed_at"] is not None
    assert calls == [("codex", "sid-live", "Inspect release flow")]
    stored = db.list_targeted_messages()
    assert [message["text"] for message in stored] == ["Inspect release flow"]
    assert stored[0]["delivery_attempt_count"] == 1
    assert stored[0]["latest_delivery_detail"] == "literal_and_enter_sent"


def test_lost_response_repeat_reconciles_existing_message_without_resubmission(client, token, monkeypatch):
    _seed_cookie(client, token)
    calls = []

    def submitted(provider, sid, text):
        calls.append((provider, sid, text))
        return {"outcome": "submitted_to_terminal", "detail": "literal_and_enter_sent"}

    monkeypatch.setattr(agents, "submit_to_agent", submitted)
    payload = {
        "text": "Exactly once",
        "idempotency_key": _submission_key("lost_response"),
    }

    first = client.post("/agents/codex/sid-live/messages", json=payload)
    # Model a client that never saw `first`, then repeats the same immutable intent.
    reconciled = client.post("/agents/codex/sid-live/messages", json=payload)
    conflict = client.post(
        "/agents/codex/sid-live/messages",
        json={"text": "Different text", "idempotency_key": payload["idempotency_key"]},
    )

    assert first.status_code == 200
    assert reconciled.status_code == 200
    assert reconciled.json()["id"] == first.json()["id"]
    assert reconciled.json()["delivery_state"] == "submitted_to_terminal"
    assert conflict.status_code == 409
    assert calls == [("codex", "sid-live", "Exactly once")]
    stored = db.list_targeted_messages()
    assert len(stored) == 1
    assert stored[0]["client_submission_key"] == payload["idempotency_key"]


def test_concurrent_duplicate_returns_submitting_row_and_invokes_bridge_once(data_dir, monkeypatch):
    stream = db.create_stream("agent-conversations", "pinned", "Agent conversations")
    entered_bridge = threading.Event()
    release_bridge = threading.Event()
    calls = []

    def blocking_submit(provider, sid, text):
        calls.append((provider, sid, text))
        entered_bridge.set()
        assert release_bridge.wait(timeout=2)
        return {"outcome": "submitted_to_terminal", "detail": "literal_and_enter_sent"}

    monkeypatch.setattr(agents, "submit_to_agent", blocking_submit)
    args = (stream, "Concurrent comment", "codex", "sid-live", _submission_key("concurrent"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(server._create_targeted_to_agent_message, *args)
        assert entered_bridge.wait(timeout=2)
        try:
            duplicate = pool.submit(server._create_targeted_to_agent_message, *args).result(timeout=2)
        finally:
            release_bridge.set()
        first = first_future.result(timeout=2)

    assert duplicate["id"] == first["id"]
    assert duplicate["delivery_state"] == "submitting"
    assert first["delivery_state"] == "submitted_to_terminal"
    assert calls == [("codex", "sid-live", "Concurrent comment")]
    assert len(db.list_targeted_messages()) == 1


def test_repeated_initial_request_claims_preexisting_pending_record(client, token, monkeypatch):
    stream = db.create_stream("agent-conversations", "pinned", "Agent conversations")
    key = _submission_key("pending_crash")
    pending, created = db.create_or_get_targeted_message(
        stream["id"], "Resume pending", "codex", "sid-live", key
    )
    calls = []
    monkeypatch.setattr(
        agents,
        "submit_to_agent",
        lambda provider, sid, text: calls.append((provider, sid, text))
        or {"outcome": "submitted_to_terminal", "detail": "literal_and_enter_sent"},
    )
    _seed_cookie(client, token)

    response = client.post(
        "/agents/codex/sid-live/messages",
        json={"text": "Resume pending", "idempotency_key": key},
    )

    assert created is True
    assert pending["delivery_state"] == "pending"
    assert response.status_code == 200
    assert response.json()["id"] == pending["id"]
    assert response.json()["delivery_state"] == "submitted_to_terminal"
    assert calls == [("codex", "sid-live", "Resume pending")]


def test_agent_message_failure_remains_retryable_and_retry_uses_original_target(client, token, monkeypatch):
    _seed_cookie(client, token)
    outcomes = iter(
        [
            {"outcome": "failed", "detail": "session_not_replyable"},
            {"outcome": "submitted_to_terminal", "detail": "literal_and_enter_sent"},
        ]
    )
    calls = []

    def submit(provider, sid, text):
        calls.append((provider, sid, text))
        return next(outcomes)

    monkeypatch.setattr(agents, "submit_to_agent", submit)

    failed = client.post(
        "/agents/codex/sid-live/messages",
        json={"text": "Retry me", "idempotency_key": _submission_key("retry")},
    )
    reconciled = client.post(
        "/agents/codex/sid-live/messages",
        json={"text": "Retry me", "idempotency_key": _submission_key("retry")},
    )
    retried = client.post(f"/agents/messages/{failed.json()['id']}/retry", json={})

    assert failed.status_code == 200
    assert failed.json()["delivery_state"] == "failed"
    assert failed.json()["consumed_at"] is None
    assert reconciled.json()["id"] == failed.json()["id"]
    assert reconciled.json()["delivery_state"] == "failed"
    assert retried.status_code == 200
    assert retried.json()["delivery_state"] == "submitted_to_terminal"
    assert calls == [
        ("codex", "sid-live", "Retry me"),
        ("codex", "sid-live", "Retry me"),
    ]


def test_unknown_agent_message_requires_inspection_confirmation_before_retry(client, token, monkeypatch):
    _seed_cookie(client, token)
    outcomes = iter(
        [
            {"outcome": "unknown", "detail": "agency_timeout"},
            {"outcome": "submitted_to_terminal", "detail": "literal_and_enter_sent"},
        ]
    )
    monkeypatch.setattr(agents, "submit_to_agent", lambda *_args: next(outcomes))

    response = client.post(
        "/agents/codex/sid-live/messages",
        json={"text": "Did this arrive?", "idempotency_key": _submission_key("unknown")},
    )
    page = client.get("/agents")
    unconfirmed = client.post(f"/agents/messages/{response.json()['id']}/retry", json={})
    confirmed = client.post(
        f"/agents/messages/{response.json()['id']}/retry",
        json={"confirm_unknown": True},
    )

    assert response.json()["delivery_state"] == "unknown"
    assert "submission unknown" in page.text
    assert f'action="/agents/messages/{response.json()["id"]}/retry"' in page.text
    assert "I inspected the terminal" in page.text
    assert unconfirmed.status_code == 409
    assert confirmed.status_code == 200
    assert confirmed.json()["delivery_state"] == "submitted_to_terminal"


def test_bridge_exception_is_durable_unknown_and_requires_confirmation_before_retry(
    client,
    token,
    monkeypatch,
):
    _seed_cookie(client, token)
    calls = 0

    def ambiguous_then_submitted(*_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("response lost after bridge invocation")
        return {"outcome": "submitted_to_terminal", "detail": "literal_and_enter_sent"}

    monkeypatch.setattr(agents, "submit_to_agent", ambiguous_then_submitted)

    response = client.post(
        "/agents/codex/sid-live/messages",
        json={"text": "Did this arrive?", "idempotency_key": _submission_key("bridge")},
    )
    message_id = response.json()["id"]
    reconciled = client.post(
        "/agents/codex/sid-live/messages",
        json={"text": "Did this arrive?", "idempotency_key": _submission_key("bridge")},
    )
    stored = db.list_targeted_messages()[0]
    attempts = db.list_message_delivery_attempts(message_id)
    unconfirmed = client.post(f"/agents/messages/{message_id}/retry", json={})
    confirmed = client.post(
        f"/agents/messages/{message_id}/retry",
        json={"confirm_unknown": True},
    )

    assert response.status_code == 200
    assert response.json()["delivery_state"] == "unknown"
    assert reconciled.json()["id"] == message_id
    assert reconciled.json()["delivery_state"] == "unknown"
    assert response.json()["consumed_at"] is None
    assert stored["delivery_state"] == "unknown"
    assert [(attempt["outcome"], attempt["detail"]) for attempt in attempts] == [
        ("unknown", "portal_bridge_exception")
    ]
    assert unconfirmed.status_code == 409
    assert confirmed.status_code == 200
    assert confirmed.json()["delivery_state"] == "submitted_to_terminal"
    assert calls == 2


def test_agent_message_requires_bounded_url_safe_idempotency_key(client, token, monkeypatch):
    _seed_cookie(client, token)
    monkeypatch.setattr(
        agents,
        "submit_to_agent",
        lambda *_args: {"outcome": "submitted_to_terminal", "detail": "literal_and_enter_sent"},
    )

    invalid = [
        client.post("/agents/codex/sid-live/messages", json={"text": "Missing"}),
        client.post(
            "/agents/codex/sid-live/messages",
            json={"text": "Short", "idempotency_key": "too_short"},
        ),
        client.post(
            "/agents/codex/sid-live/messages",
            json={"text": "Slash", "idempotency_key": "not/url/safe/key"},
        ),
        client.post(
            "/agents/codex/sid-live/messages",
            json={"text": "Long", "idempotency_key": "a" * 129},
        ),
    ]

    assert [response.status_code for response in invalid] == [400, 400, 400, 400]
    assert db.list_targeted_messages() == []


def test_agent_submission_browser_contract_persists_key_and_marks_transport_unknown(client):
    script = client.get("/static/app.js")

    assert script.status_code == 200
    assert "window.sessionStorage.setItem(storageKey, JSON.stringify(record))" in script.text
    assert "payload.idempotency_key = clientSubmission.key" in script.text
    assert script.text.index("clientSubmission = persistClientSubmission(form, url, payload)") < script.text.index(
        "fetch(url, {"
    )
    assert "Submission status unknown. Submit again to reconcile" in script.text
    assert "setIdempotentFormLocked(form, true)" in script.text
    assert 'form.hasAttribute("data-agent-message-form")' in script.text
    assert "rememberAgentComposerFocus(form, url)" in script.text
    assert "restoreAgentComposerFocus(forms)" in script.text


def test_internal_agent_stream_cannot_be_archived_and_legacy_closure_recovers_on_send(
    client,
    token,
    monkeypatch,
):
    stream = db.create_stream("agent-conversations", "pinned", "Agent conversations")

    rejected = client.post(
        "/api/streams/agent-conversations/close",
        headers=_auth_headers(token),
    )
    assert rejected.status_code == 409
    assert db.get_stream("agent-conversations")["closed_at"] is None

    db.close_stream("agent-conversations")  # Simulate a legacy database.
    _seed_cookie(client, token)
    monkeypatch.setattr(
        agents,
        "submit_to_agent",
        lambda *_args: {"outcome": "submitted_to_terminal", "detail": "literal_and_enter_sent"},
    )

    response = client.post(
        "/agents/codex/sid-live/messages",
        json={"text": "Resume the reserved stream", "idempotency_key": _submission_key("reopen")},
    )

    assert response.status_code == 200
    assert response.json()["stream_id"] == stream["id"]
    assert response.json()["delivery_state"] == "submitted_to_terminal"
    assert db.get_stream("agent-conversations")["closed_at"] is None


def test_archived_targeted_messages_do_not_offer_impossible_retry_controls(
    client,
    token,
    monkeypatch,
):
    stream = db.create_stream("archived-delivery", "session", "Archived delivery")
    failed = db.create_targeted_message(stream["id"], "Failed delivery", "codex", "sid-failed")
    db.claim_message_delivery(failed["id"])
    db.complete_message_delivery(failed["id"], "failed", "session_not_replyable")
    unknown = db.create_targeted_message(stream["id"], "Unknown delivery", "codex", "sid-unknown")
    db.claim_message_delivery(unknown["id"])
    db.complete_message_delivery(unknown["id"], "unknown", "agency_timeout")
    db.close_stream("archived-delivery")
    monkeypatch.setattr(agents, "list_replyable_agents", lambda: [])

    agents_page = client.get(f"/agents?token={token}")
    stream_page = client.get("/s/archived-delivery")

    assert agents_page.status_code == 200
    assert stream_page.status_code == 200
    for page in (agents_page, stream_page):
        assert f'action="/agents/messages/{failed["id"]}/retry"' not in page.text
        assert f'action="/agents/messages/{unknown["id"]}/retry"' not in page.text
    assert "Failed delivery" in agents_page.text
    assert "Unknown delivery" in agents_page.text


def test_agent_mutations_require_cookie_and_validate_single_paragraph(client, token, monkeypatch):
    monkeypatch.setattr(agents, "submit_to_agent", lambda *_args: None)

    missing = client.post(
        "/agents/codex/sid-live/messages",
        json={"text": "No cookie", "idempotency_key": _submission_key("no_cookie")},
    )
    _seed_cookie(client, token)
    invalid = [
        client.post(
            "/agents/codex/sid-live/messages",
            json={"text": "line one\nline two", "idempotency_key": _submission_key("newline")},
        ),
        client.post(
            "/agents/codex/sid-live/messages",
            json={"text": "contains\u0000null", "idempotency_key": _submission_key("null")},
        ),
        client.post(
            "/agents/Codex/sid-live/messages",
            json={"text": "bad provider", "idempotency_key": _submission_key("provider")},
        ),
    ]

    assert missing.status_code == 401
    assert [response.status_code for response in invalid] == [400, 400, 400]
    assert db.list_targeted_messages() == []


def test_agent_retry_auth_unknown_and_closed_stream_errors_are_json(client, token, monkeypatch):
    stream = db.create_stream("agent-conversations", "pinned", "Agent conversations")
    message = db.create_targeted_message(stream["id"], "Saved", "codex", "sid-live")
    db.claim_message_delivery(message["id"])
    db.complete_message_delivery(message["id"], "failed", "session_not_replyable")
    db.close_stream("agent-conversations")

    missing_auth = client.post(f"/agents/messages/{message['id']}/retry", json={})
    _seed_cookie(client, token)
    missing_message = client.post("/agents/messages/m_missing/retry", json={})
    closed = client.post(f"/agents/messages/{message['id']}/retry", json={})

    assert missing_auth.status_code == 401
    assert missing_message.status_code == 404
    assert closed.status_code == 409
