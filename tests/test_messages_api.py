from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from gallery import client as gallery_client
from gallery import db, server


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _clock():
    values = iter(
        [
            "2026-07-08T10:00:00+00:00",
            "2026-07-08T10:00:01+00:00",
            "2026-07-08T10:00:02+00:00",
            "2026-07-08T10:00:03+00:00",
            "2026-07-08T10:00:04+00:00",
            "2026-07-08T10:00:05+00:00",
            "2026-07-08T10:00:06+00:00",
            "2026-07-08T10:00:07+00:00",
        ]
    )
    return lambda: next(values)


def test_message_helpers_round_trip_filters_and_idempotent_consume(data_dir, monkeypatch):
    db.connect()
    monkeypatch.setattr(db, "now_iso", _clock())
    stream = db.create_stream("messages", "session", "Messages")

    first = db.create_message(stream["id"], "to_agent", "Human steering")
    same_second = db.create_message(
        stream["id"],
        "to_agent",
        "Same second steering",
        created_at=first["created_at"],
    )
    second = db.create_message(stream["id"], "to_human", "Agent question")

    assert first["id"].startswith("m_")
    assert first["consumed_at"] is None
    assert [message["id"] for message in db.list_messages(stream["id"])] == [
        first["id"],
        same_second["id"],
        second["id"],
    ]
    assert [message["id"] for message in db.list_messages(stream["id"], direction="to_human")] == [second["id"]]
    assert [message["id"] for message in db.list_messages(stream["id"], since=first["created_at"])] == [
        second["id"]
    ]
    assert [message["id"] for message in db.list_messages(stream["id"], since="2026-07-08T12:00:01+02:00")] == [
        second["id"]
    ]
    with pytest.raises(ValueError, match="timezone"):
        db.list_messages(stream["id"], since="2026-07-08T10:00:01")
    assert [message["id"] for message in db.list_messages(stream["id"], unconsumed=True)] == [
        first["id"],
        same_second["id"],
        second["id"],
    ]

    consumed = db.consume_message(first["id"])
    consumed_again = db.consume_message(first["id"])

    assert consumed["consumed_at"] == "2026-07-08T10:00:03+00:00"
    assert consumed_again["consumed_at"] == consumed["consumed_at"]
    assert [message["id"] for message in db.list_messages(stream["id"], unconsumed=True)] == [
        same_second["id"],
        second["id"],
    ]


def test_message_helpers_reject_missing_and_closed_stream_mutations(data_dir):
    stream = db.create_stream("closed", "session", "Closed")
    message = db.create_message(stream["id"], "to_agent", "Before close")
    db.close_stream("closed")

    with pytest.raises(ValueError, match="stream is closed"):
        db.create_message(stream["id"], "to_agent", "Too late")
    with pytest.raises(ValueError, match="stream is closed"):
        db.consume_message(message["id"])
    with pytest.raises(ValueError, match="message not found"):
        db.consume_message("m_missing")

    assert [item["id"] for item in db.list_messages(stream["id"])] == [message["id"]]


def test_message_helpers_combine_since_direction_and_unconsumed_filters(data_dir, monkeypatch):
    db.connect()
    monkeypatch.setattr(db, "now_iso", _clock())
    stream = db.create_stream("combined", "session", "Combined")
    old_agent = db.create_message(stream["id"], "to_agent", "Old")
    consumed_agent = db.create_message(stream["id"], "to_agent", "Consumed")
    wanted_agent = db.create_message(stream["id"], "to_agent", "Wanted")
    db.create_message(stream["id"], "to_human", "Human")
    db.consume_message(consumed_agent["id"])

    filtered = db.list_messages(
        stream["id"],
        since=old_agent["created_at"],
        direction="to_agent",
        unconsumed=True,
    )

    assert [message["id"] for message in filtered] == [wanted_agent["id"]]


def test_message_since_preserves_subsecond_cursor(data_dir):
    stream = db.create_stream("subsecond", "session", "Subsecond")
    db.create_message(
        stream["id"],
        "to_agent",
        "Stale note",
        created_at="2026-07-08T10:00:00.050000+00:00",
        message_id="m_stale",
    )
    question = db.create_message(
        stream["id"],
        "to_human",
        "Question?",
        created_at="2026-07-08T10:00:00.100000+00:00",
        message_id="m_question",
    )
    reply = db.create_message(
        stream["id"],
        "to_agent",
        "Answer",
        created_at="2026-07-08T10:00:00.200000+00:00",
        message_id="m_reply",
    )

    filtered = db.list_messages(stream["id"], since=question["created_at"], direction="to_agent", unconsumed=True)

    assert [message["id"] for message in filtered] == [reply["id"]]


def test_now_iso_uses_subsecond_precision(monkeypatch):
    class FixedDateTime:
        @classmethod
        def now(cls, tz):
            return datetime(2026, 7, 8, 10, 0, 0, 123456, tzinfo=tz)

    monkeypatch.setattr(db, "datetime", FixedDateTime)

    assert db.now_iso() == "2026-07-08T10:00:00.123456+00:00"


def test_concurrent_consume_preserves_single_timestamp(data_dir):
    stream = db.create_stream("race", "session", "Race")
    message = db.create_message(stream["id"], "to_agent", "Consume once")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: db.consume_message(message["id"]), range(2)))

    assert len({result["consumed_at"] for result in results}) == 1
    assert db.list_messages(stream["id"], unconsumed=True) == []


def test_message_routes_require_bearer_auth(client):
    assert client.post("/api/streams/alpha/messages", json={"direction": "to_agent", "text": "hi"}).status_code == 401
    assert client.get("/api/streams/alpha/messages").status_code == 401
    assert client.post("/api/messages/m_123456/consume").status_code == 401


def test_message_api_round_trip_filters_consume_and_unknown_stream_autocreate(client, token, monkeypatch):
    db.connect()
    monkeypatch.setattr(db, "now_iso", _clock())

    first = client.post(
        "/api/streams/auto-created/messages",
        headers=auth_headers(token),
        json={"direction": "to_agent", "text": "Check this before the next turn"},
    )
    assert first.status_code == 200
    first_message = first.json()
    assert first_message["direction"] == "to_agent"
    assert first_message["text"] == "Check this before the next turn"

    stream = client.get("/api/streams/auto-created", headers=auth_headers(token))
    assert stream.status_code == 200
    assert stream.json()["kind"] == "session"
    assert stream.json()["posts"] == []

    second = client.post(
        "/api/streams/auto-created/messages",
        headers=auth_headers(token),
        json={"direction": "to_human", "text": "Which option should I use?"},
    )
    assert second.status_code == 200
    second_message = second.json()

    listed = client.get("/api/streams/auto-created/messages", headers=auth_headers(token))
    assert listed.status_code == 200
    assert [message["id"] for message in listed.json()] == [first_message["id"], second_message["id"]]

    to_agent = client.get(
        "/api/streams/auto-created/messages?direction=to_agent",
        headers=auth_headers(token),
    )
    assert [message["id"] for message in to_agent.json()] == [first_message["id"]]

    since = client.get(
        "/api/streams/auto-created/messages",
        headers=auth_headers(token),
        params={"since": first_message["created_at"]},
    )
    assert [message["id"] for message in since.json()] == [second_message["id"]]

    offset_since = client.get(
        "/api/streams/auto-created/messages",
        headers=auth_headers(token),
        params={"since": "2026-07-08T12:00:01+02:00"},
    )
    assert [message["id"] for message in offset_since.json()] == [second_message["id"]]

    unconsumed = client.get("/api/streams/auto-created/messages?unconsumed=1", headers=auth_headers(token))
    assert [message["id"] for message in unconsumed.json()] == [first_message["id"], second_message["id"]]

    consumed = client.post(f"/api/messages/{first_message['id']}/consume", headers=auth_headers(token))
    consumed_again = client.post(f"/api/messages/{first_message['id']}/consume", headers=auth_headers(token))
    remaining = client.get("/api/streams/auto-created/messages?unconsumed=1", headers=auth_headers(token))

    assert consumed.status_code == 200
    assert consumed.json()["consumed_at"] is not None
    assert consumed_again.status_code == 200
    assert consumed_again.json()["consumed_at"] == consumed.json()["consumed_at"]
    assert [message["id"] for message in remaining.json()] == [second_message["id"]]


def test_message_api_validates_inputs_and_read_does_not_autocreate(client, token):
    assert client.get("/api/streams/missing/messages", headers=auth_headers(token)).status_code == 404
    assert db.get_stream("missing") is None

    cases = [
        client.post("/api/streams/Bad/messages", headers=auth_headers(token), json={"direction": "to_agent", "text": "x"}),
        client.post("/api/streams/valid/messages", headers=auth_headers(token), json=["not", "object"]),
        client.post("/api/streams/valid/messages", headers=auth_headers(token), json={"direction": "sideways", "text": "x"}),
        client.post("/api/streams/valid/messages", headers=auth_headers(token), json={"direction": "to_agent"}),
        client.post("/api/streams/valid/messages", headers=auth_headers(token), json={"direction": "to_agent", "text": "  "}),
        client.post("/api/streams/valid/messages", headers=auth_headers(token), json={"direction": "to_agent", "text": 123}),
        client.get("/api/streams/valid/messages?direction=sideways", headers=auth_headers(token)),
        client.get("/api/streams/valid/messages?since=not-a-date", headers=auth_headers(token)),
        client.get("/api/streams/valid/messages?since=2026-07-08T10:00:00", headers=auth_headers(token)),
        client.get("/api/streams/valid/messages?unconsumed=true", headers=auth_headers(token)),
    ]

    assert [response.status_code for response in cases] == [400, 400, 400, 400, 400, 400, 400, 400, 400, 400]

    monkeypatch_response = client.post(
        "/api/streams/valid/messages",
        headers=auth_headers(token),
        json={"direction": "to_agent", "text": "x"},
    )
    assert monkeypatch_response.status_code == 200


def test_message_api_preserves_subsecond_since_cursor(client, token):
    stream = db.create_stream("api-subsecond", "session", "API subsecond")
    db.create_message(
        stream["id"],
        "to_agent",
        "Stale note",
        created_at="2026-07-08T10:00:00.050000+00:00",
        message_id="m_stale",
    )
    question = db.create_message(
        stream["id"],
        "to_human",
        "Question?",
        created_at="2026-07-08T10:00:00.100000+00:00",
        message_id="m_question",
    )
    db.create_message(
        stream["id"],
        "to_agent",
        "Answer",
        created_at="2026-07-08T10:00:00.200000+00:00",
        message_id="m_reply",
    )

    response = client.get(
        "/api/streams/api-subsecond/messages",
        headers=auth_headers(token),
        params={"since": question["created_at"], "direction": "to_agent", "unconsumed": "1"},
    )

    assert response.status_code == 200
    assert [message["id"] for message in response.json()] == ["m_reply"]


def test_message_api_rejects_oversized_text(client, token, monkeypatch):
    monkeypatch.setattr(server, "MAX_MESSAGE_TEXT_LENGTH", 4)

    response = client.post(
        "/api/streams/valid/messages",
        headers=auth_headers(token),
        json={"direction": "to_agent", "text": "12345"},
    )

    assert response.status_code == 400


def test_message_api_closed_stream_and_missing_consume_errors(client, token):
    created = client.post(
        "/api/streams/closing/messages",
        headers=auth_headers(token),
        json={"direction": "to_agent", "text": "Before close"},
    )
    assert created.status_code == 200
    message_id = created.json()["id"]
    assert client.post("/api/streams/closing/close", headers=auth_headers(token)).status_code == 200

    create_closed = client.post(
        "/api/streams/closing/messages",
        headers=auth_headers(token),
        json={"direction": "to_agent", "text": "Too late"},
    )
    consume_closed = client.post(f"/api/messages/{message_id}/consume", headers=auth_headers(token))
    missing_closed_like = client.post("/api/messages/m_closed_missing/consume", headers=auth_headers(token))

    assert create_closed.status_code == 409
    assert consume_closed.status_code == 409
    assert missing_closed_like.status_code == 404


def test_message_api_retries_message_id_collision(client, token, monkeypatch):
    first = client.post(
        "/api/streams/collision/messages",
        headers=auth_headers(token),
        json={"direction": "to_agent", "text": "First"},
    )
    assert first.status_code == 200
    first_id = first.json()["id"]
    ids = iter([first_id, "m_retry123"])
    monkeypatch.setattr(server.db, "new_message_id", lambda: next(ids))

    second = client.post(
        "/api/streams/collision/messages",
        headers=auth_headers(token),
        json={"direction": "to_agent", "text": "Second"},
    )

    assert second.status_code == 200
    assert second.json()["id"] == "m_retry123"
    listed = client.get("/api/streams/collision/messages", headers=auth_headers(token))
    assert [message["id"] for message in listed.json()] == [first_id, "m_retry123"]


def test_to_human_message_starts_notify_thread_and_to_agent_is_silent(client, token, monkeypatch):
    threads = []

    class FakeThread:
        def __init__(self, target, args=(), kwargs=None, daemon=None):
            self.target = target
            self.args = args
            self.kwargs = kwargs or {}
            self.daemon = daemon
            self.started = False
            threads.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(server.threading, "Thread", FakeThread)

    to_agent = client.post(
        "/api/streams/notify/messages",
        headers=auth_headers(token),
        json={"direction": "to_agent", "text": "Silent note"},
    )
    assert to_agent.status_code == 200
    assert threads == []

    to_human = client.post(
        "/api/streams/notify/messages",
        headers=auth_headers(token),
        json={"direction": "to_human", "text": "Need a decision"},
    )
    assert to_human.status_code == 200
    assert len(threads) == 1
    assert threads[0].target is server.notify.send_text
    assert threads[0].daemon is True
    assert threads[0].started is True
    assert "Need a decision" in threads[0].args[1]
    assert "/s/notify?token=" in threads[0].args[1]


def test_to_human_notification_thread_failure_does_not_fail_message_create(client, token, monkeypatch):
    class FailingThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("thread unavailable")

    monkeypatch.setattr(server.threading, "Thread", FailingThread)

    response = client.post(
        "/api/streams/notify-fail/messages",
        headers=auth_headers(token),
        json={"direction": "to_human", "text": "Still store this"},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "Still store this"


def test_to_human_notification_config_failure_does_not_fail_message_create(client, token, monkeypatch, data_dir):
    cfg = data_dir[1]
    calls = 0

    def flaky_load_config():
        nonlocal calls
        calls += 1
        if calls == 1:
            return cfg
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(server.config, "load_config", flaky_load_config)

    response = client.post(
        "/api/streams/notify-config-fail/messages",
        headers=auth_headers(token),
        json={"direction": "to_human", "text": "Still stored"},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "Still stored"


def test_client_message_helpers_call_expected_methods_paths_payloads_and_queries(monkeypatch):
    calls = []

    def fake_request(method, url, headers, data=None):
        calls.append({"method": method, "url": url, "headers": headers, "data": data})
        return {"ok": True}

    monkeypatch.setattr(gallery_client, "_request", fake_request)

    gallery_client.create_stream_message("http://gallery", "tok", "alpha/beta", "to_human", "Question?")
    gallery_client.list_stream_messages("http://gallery", "tok", "alpha")
    gallery_client.list_stream_messages(
        "http://gallery",
        "tok",
        "alpha",
        since="2026-07-08T10:00:00+00:00",
        direction="to_agent",
        unconsumed=True,
    )
    gallery_client.consume_message("http://gallery", "tok", "m_1/2")

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "http://gallery/api/streams/alpha%2Fbeta/messages"
    assert calls[0]["headers"]["Authorization"] == "Bearer tok"
    assert calls[0]["headers"]["Content-Type"] == "application/json"
    assert b'"direction": "to_human"' in calls[0]["data"]
    assert b'"text": "Question?"' in calls[0]["data"]
    assert calls[1]["method"] == "GET"
    assert calls[1]["url"] == "http://gallery/api/streams/alpha/messages"
    assert calls[2]["url"] == (
        "http://gallery/api/streams/alpha/messages"
        "?since=2026-07-08T10%3A00%3A00%2B00%3A00&direction=to_agent&unconsumed=1"
    )
    assert calls[3]["method"] == "POST"
    assert calls[3]["url"] == "http://gallery/api/messages/m_1%2F2/consume"
    assert calls[3]["headers"]["Content-Type"] == "application/json"
