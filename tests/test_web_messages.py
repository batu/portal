from gallery import agents, db


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_cookie(client, token, slug):
    response = client.get(f"/s/{slug}?token={token}")
    assert response.status_code == 200
    return response


def test_note_twin_creates_to_agent_message_visible_via_api(client, token):
    db.create_stream("alpha", "session", "Alpha stream")
    _seed_cookie(client, token, "alpha")

    response = client.post("/s/alpha/note", json={"text": "Steer here"})

    assert response.status_code == 200
    message = response.json()
    assert message["direction"] == "to_agent"
    assert message["text"] == "Steer here"

    listed = client.get("/api/streams/alpha/messages?direction=to_agent", headers=auth_headers(token))
    assert listed.status_code == 200
    assert [item["text"] for item in listed.json()] == ["Steer here"]

    unconsumed = client.get(
        "/api/streams/alpha/messages?direction=to_agent&unconsumed=1",
        headers=auth_headers(token),
    )
    assert unconsumed.status_code == 200
    assert [item["text"] for item in unconsumed.json()] == ["Steer here"]


def test_answer_twin_creates_to_agent_message_and_consumes_question_once(client, token):
    stream = db.create_stream("alpha", "session", "Alpha stream")
    question = db.create_message(stream["id"], "to_human", "Which option?")
    _seed_cookie(client, token, "alpha")

    response = client.post(
        "/s/alpha/answer",
        json={"text": "Use option B", "question_id": question["id"]},
    )
    stale = client.post(
        "/s/alpha/answer",
        json={"text": "Use option C", "question_id": question["id"]},
    )

    assert response.status_code == 200
    assert response.json()["direction"] == "to_agent"
    assert response.json()["text"] == "Use option B"
    assert stale.status_code == 409

    messages = db.list_messages(stream["id"])
    answered_question = next(item for item in messages if item["id"] == question["id"])
    answers = [item for item in messages if item["direction"] == "to_agent"]
    assert answered_question["consumed_at"] is not None
    assert [item["text"] for item in answers] == ["Use option B"]

    listed = client.get("/api/streams/alpha/messages?direction=to_agent", headers=auth_headers(token))
    assert [item["text"] for item in listed.json()] == ["Use option B"]

    unconsumed = client.get(
        "/api/streams/alpha/messages?direction=to_agent&unconsumed=1",
        headers=auth_headers(token),
    )
    assert unconsumed.status_code == 200
    assert [item["text"] for item in unconsumed.json()] == ["Use option B"]


def test_web_message_twins_require_web_auth(client):
    note = client.post("/s/alpha/note", json={"text": "hi"})
    answer = client.post("/s/alpha/answer", json={"text": "hi", "question_id": "m_missing"})

    assert note.status_code == 401
    assert answer.status_code == 401


def test_web_message_twins_validate_inputs_and_answer_source(client, token):
    stream = db.create_stream("alpha", "session", "Alpha stream")
    other = db.create_stream("other", "session", "Other stream")
    cross_question = db.create_message(other["id"], "to_human", "Other question?", message_id="m_other")
    not_question = db.create_message(stream["id"], "to_agent", "Existing note", message_id="m_note")
    _seed_cookie(client, token, "alpha")

    responses = [
        client.post("/s/Bad/note", json={"text": "hi"}),
        client.post("/s/alpha/note", json=["not", "object"]),
        client.post("/s/alpha/note", json={"text": "   "}),
        client.post("/s/alpha/answer", json={"text": "A", "question_id": "bad/id"}),
        client.post("/s/alpha/answer", json={"text": "A", "question_id": "m_missing"}),
        client.post("/s/alpha/answer", json={"text": "A", "question_id": cross_question["id"]}),
        client.post("/s/alpha/answer", json={"text": "A", "question_id": not_question["id"]}),
    ]

    assert [response.status_code for response in responses] == [400, 400, 400, 400, 404, 404, 400]
    assert [item["text"] for item in db.list_messages(stream["id"], direction="to_agent")] == ["Existing note"]
    assert db.list_messages(other["id"])[0]["consumed_at"] is None
    assert db.list_messages(stream["id"], direction="to_agent")[0]["consumed_at"] is None


def test_web_message_twins_do_not_autocreate_missing_streams(client, token):
    db.create_stream("alpha", "session", "Alpha stream")
    _seed_cookie(client, token, "alpha")

    note = client.post("/s/missing/note", json={"text": "No stream"})
    answer = client.post("/s/missing/answer", json={"text": "No stream", "question_id": "m_missing"})

    assert note.status_code == 404
    assert answer.status_code == 404
    assert db.get_stream("missing") is None
    assert db.list_messages(db.get_stream("alpha")["id"]) == []


def test_answer_twin_rejects_invalid_text_without_side_effects(client, token, monkeypatch):
    stream = db.create_stream("alpha", "session", "Alpha stream")
    question = db.create_message(stream["id"], "to_human", "Which option?", message_id="m_question")
    _seed_cookie(client, token, "alpha")
    monkeypatch.setattr("gallery.server.MAX_MESSAGE_TEXT_LENGTH", 4)

    responses = [
        client.post("/s/alpha/answer", json={"question_id": question["id"]}),
        client.post("/s/alpha/answer", json={"text": "   ", "question_id": question["id"]}),
        client.post("/s/alpha/answer", json={"text": 123, "question_id": question["id"]}),
        client.post("/s/alpha/answer", json={"text": "12345", "question_id": question["id"]}),
    ]

    assert [response.status_code for response in responses] == [400, 400, 400, 400]
    messages = db.list_messages(stream["id"])
    assert len(messages) == 1
    assert messages[0]["id"] == question["id"]
    assert messages[0]["consumed_at"] is None


def test_closed_stream_rejects_note_and_answer_twins_and_hides_forms(client, token):
    stream = db.create_stream("closed", "session", "Closed stream")
    question = db.create_message(stream["id"], "to_human", "Still there?")
    db.close_stream("closed")
    page = _seed_cookie(client, token, "closed")

    note = client.post("/s/closed/note", json={"text": "Too late"})
    answer = client.post(
        "/s/closed/answer",
        json={"text": "Too late", "question_id": question["id"]},
    )

    assert note.status_code == 409
    assert answer.status_code == 409
    assert "Archived stream. Posts and decisions are read-only." in page.text
    assert "data-stream-note-form" not in page.text
    assert "data-answer-form" not in page.text
    messages = db.list_messages(stream["id"])
    assert [item["direction"] for item in messages] == ["to_human"]
    assert messages[0]["id"] == question["id"]
    assert messages[0]["consumed_at"] is None


def test_stream_page_renders_questions_and_message_states_newest_first(client, token):
    stream = db.create_stream("alpha", "session", "Alpha stream")
    older = db.create_message(
        stream["id"],
        "to_human",
        "Older question?",
        created_at="2026-07-08T09:00:00+00:00",
        message_id="m_older",
    )
    newer = db.create_message(
        stream["id"],
        "to_human",
        "Newer question?",
        created_at="2026-07-08T10:00:00+00:00",
        message_id="m_newer",
    )
    consumed_question = db.create_message(stream["id"], "to_human", "Answered already?", message_id="m_done")
    queued = db.create_message(stream["id"], "to_agent", "Queued note", message_id="m_queued")
    picked_up = db.create_message(stream["id"], "to_agent", "Picked up note", message_id="m_picked")
    db.consume_message(consumed_question["id"])
    db.consume_message(picked_up["id"])

    page = client.get(f"/s/alpha?token={token}")

    assert page.status_code == 200
    assert "data-stream-note-form" in page.text
    assert 'method="post" action="/s/alpha/note"' in page.text
    assert 'method="post" action="/s/alpha/answer"' in page.text
    assert "Agent asks" in page.text
    assert page.text.index("Newer question?") < page.text.index("Older question?")
    assert f'value="{newer["id"]}"' in page.text
    assert f'value="{older["id"]}"' in page.text
    assert f'value="{consumed_question["id"]}"' not in page.text
    assert "Answered already?" in page.text
    assert "Answered questions" in page.text
    assert "Queued note" in page.text
    assert "Picked up note" in page.text
    assert '<span class="status-badge queued">queued</span>' in page.text
    assert '<span class="status-badge picked-up">picked up</span>' in page.text
    assert queued["consumed_at"] is None


def test_stream_page_escapes_message_text_and_does_not_leak_token(client, token):
    stream = db.create_stream("escape", "session", "Escape stream")
    db.create_message(stream["id"], "to_human", '<script>alert("x")</script> & wait')
    db.create_message(stream["id"], "to_agent", "<b>raw</b> & queued")

    page = client.get(f"/s/escape?token={token}")

    assert page.status_code == 200
    assert "<script>" not in page.text
    assert "<b>raw</b>" not in page.text
    assert "&lt;script&gt;" in page.text
    assert "&lt;b&gt;raw&lt;/b&gt;" in page.text
    assert "token=" not in page.text


def test_static_stream_message_js_posts_without_query_token_and_handles_status(client):
    script = client.get("/static/app.js")

    assert script.status_code == 200
    assert 'return "/s/" + encodeURIComponent(slug) + "/" + action;' in script.text
    assert 'return "/s/" + encodeURIComponent(slug) + "/" + action + window.location.search;' not in script.text
    assert 'credentials: "same-origin"' in script.text
    assert '"Content-Type": "application/json"' in script.text
    assert "data-stream-note-form" in script.text
    assert "data-answer-form" in script.text
    assert "data-form-status" in script.text
    assert "window.location.reload()" in script.text
    assert "button.disabled = false" in script.text


def test_stream_note_can_target_exact_agent_and_submits_immediately(client, token, monkeypatch):
    db.create_stream("alpha", "session", "Alpha stream")
    monkeypatch.setattr(agents, "list_replyable_agents", lambda: [])
    _seed_cookie(client, token, "alpha")
    calls = []

    def submitted(provider, sid, text):
        calls.append((provider, sid, text))
        return {"outcome": "submitted_to_terminal", "detail": "literal_and_enter_sent"}

    monkeypatch.setattr(agents, "submit_to_agent", submitted)

    payload = {
        "text": "Steer this session",
        "target_provider": "codex",
        "target_session_id": "sid-live",
        "idempotency_key": "portal_test_stream_submission",
    }
    response = client.post("/s/alpha/note", json=payload)
    reconciled = client.post("/s/alpha/note", json=payload)

    assert response.status_code == 200
    assert response.json()["delivery_state"] == "submitted_to_terminal"
    assert reconciled.status_code == 200
    assert reconciled.json()["id"] == response.json()["id"]
    assert calls == [("codex", "sid-live", "Steer this session")]
    assert db.list_messages(db.get_stream("alpha")["id"], direction="to_agent", unconsumed=True) == []


def test_stream_page_renders_agent_selector_and_failed_retry(monkeypatch, client, token):
    stream = db.create_stream("alpha", "session", "Alpha stream")
    message = db.create_targeted_message(stream["id"], "Try again", "codex", "sid-live")
    db.claim_message_delivery(message["id"])
    db.complete_message_delivery(message["id"], "failed", "session_not_replyable")
    monkeypatch.setattr(
        agents,
        "list_replyable_agents",
        lambda: [
            {
                "provider": "codex",
                "sid": "sid-live",
                "label": "portal-main",
                "project": "portal",
                "task": "feat/agents",
                "state": "working",
                "freshness_seconds": 3.0,
                "replyable": True,
            }
        ],
    )

    page = client.get(f"/s/alpha?token={token}")
    directory = client.get("/agents/directory")

    assert page.status_code == 200
    assert "Choose delivery target" in page.text
    assert directory.status_code == 200
    assert directory.json()["sessions"][0]["provider"] == "codex"
    assert directory.json()["sessions"][0]["sid"] == "sid-live"
    assert "submitted to terminal" in page.text
    assert "failed" in page.text
    assert 'data-agent-retry-form' in page.text
    assert f'action="/agents/messages/{message["id"]}/retry"' in page.text


def test_stream_target_pair_validation_does_not_create_message(client, token, monkeypatch):
    stream = db.create_stream("alpha", "session", "Alpha stream")
    monkeypatch.setattr(agents, "list_replyable_agents", lambda: [])
    _seed_cookie(client, token, "alpha")

    responses = [
        client.post("/s/alpha/note", json={"text": "Half", "target_provider": "codex"}),
        client.post("/s/alpha/note", json={"text": "Half", "target_session_id": "sid-live"}),
        client.post(
            "/s/alpha/note",
            json={"text": "line one\nline two", "target_provider": "codex", "target_session_id": "sid-live"},
        ),
    ]

    assert [response.status_code for response in responses] == [400, 400, 400]
    assert db.list_messages(stream["id"]) == []
