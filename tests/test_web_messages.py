from gallery import db


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
    assert [item["direction"] for item in db.list_messages(stream["id"])] == ["to_human"]


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
    same_second_first = db.create_message(
        stream["id"],
        "to_human",
        "First same-second question?",
        created_at="2026-07-08T10:00:00+00:00",
        message_id="m_same_first",
    )
    same_second_second = db.create_message(
        stream["id"],
        "to_human",
        "Second same-second question?",
        created_at="2026-07-08T10:00:00+00:00",
        message_id="m_same_second",
    )
    consumed_question = db.create_message(stream["id"], "to_human", "Answered already?", message_id="m_done")
    queued = db.create_message(stream["id"], "to_agent", "Queued note", message_id="m_queued")
    picked_up = db.create_message(stream["id"], "to_agent", "Picked up note", message_id="m_picked")
    db.consume_message(consumed_question["id"])
    db.consume_message(picked_up["id"])

    page = client.get(f"/s/alpha?token={token}")

    assert page.status_code == 200
    assert "data-stream-note-form" in page.text
    assert "Agent asks" in page.text
    assert page.text.index("Newer question?") < page.text.index("Older question?")
    assert page.text.index("Second same-second question?") < page.text.index("First same-second question?")
    assert f'value="{newer["id"]}"' in page.text
    assert f'value="{same_second_first["id"]}"' in page.text
    assert f'value="{same_second_second["id"]}"' in page.text
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
