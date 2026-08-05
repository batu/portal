import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from gallery import agents, db


def test_fleet_listing_uses_bounded_argv_and_returns_only_sanitized_replyable_sessions(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="""[
              {"provider":"codex","label":"portal-1","project":"portal","task":"feat/agents",
               "state":"working","freshness_seconds":12.5,"sid":"sid-live","replyable":true},
              {"provider":"codex","label":"child","project":"portal","task":"tests","state":"working",
               "freshness_seconds":1,"sid":"sid-child","replyable":false},
              {"provider":"claude","label":"dead","project":"portal","task":"main","state":"idle",
               "freshness_seconds":8,"sid":"sid-dead","replyable":false}
            ]""",
            stderr="",
        )

    monkeypatch.setattr(agents.subprocess, "run", fake_run)

    result = agents.list_replyable_agents()

    assert result == [
        {
            "provider": "codex",
            "sid": "sid-live",
            "label": "portal-1",
            "project": "portal",
            "task": "feat/agents",
            "state": "working",
            "freshness_seconds": 12.5,
            "replyable": True,
        }
    ]
    assert calls == [
        (
            ["agency", "fleet", "--reply-targets", "--json"],
            {
                "capture_output": True,
                "text": True,
                "timeout": agents.FLEET_TIMEOUT_SECONDS,
                "check": False,
            },
        )
    ]
    assert "pane" not in result[0]
    assert "what" not in result[0]


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (FileNotFoundError(), "Agency is unavailable."),
        (subprocess.TimeoutExpired(["agency"], 1), "Agency did not return Fleet state in time."),
    ],
)
def test_fleet_listing_reports_safe_unavailability(monkeypatch, failure, message):
    def fake_run(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(agents.subprocess, "run", fake_run)

    with pytest.raises(agents.AgentBridgeError, match=message):
        agents.list_replyable_agents()


def test_terminal_submission_uses_exact_provider_sid_and_stdin(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout='{"outcome":"submitted_to_terminal","detail":"literal_and_enter_sent"}',
            stderr="",
        )

    monkeypatch.setattr(agents.subprocess, "run", fake_run)

    result = agents.submit_to_agent("codex", "sid-live", "Inspect release flow")

    assert result == {
        "outcome": "submitted_to_terminal",
        "detail": "literal_and_enter_sent",
    }
    assert calls == [
        (
            ["agency", "fleet", "--provider", "codex", "--reply", "sid-live", "--json"],
            {
                "input": "Inspect release flow",
                "capture_output": True,
                "text": True,
                "timeout": agents.SUBMIT_TIMEOUT_SECONDS,
                "check": False,
            },
        )
    ]


def test_terminal_submission_timeout_is_unknown_because_input_may_have_arrived(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["agency"], 1)

    monkeypatch.setattr(agents.subprocess, "run", fake_run)

    assert agents.submit_to_agent("codex", "sid-live", "Inspect release flow") == {
        "outcome": "unknown",
        "detail": "agency_timeout",
    }


def test_terminal_submission_missing_executable_is_retryable_failure(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(agents.subprocess, "run", fake_run)

    assert agents.submit_to_agent("codex", "sid-live", "Inspect release flow") == {
        "outcome": "failed",
        "detail": "agency_unavailable",
    }


def test_terminal_submission_preserves_agency_safe_reason(monkeypatch):
    monkeypatch.setattr(
        agents.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, stdout='{"outcome":"failed","reason":"session_not_replyable"}', stderr=""
        ),
    )

    assert agents.submit_to_agent("codex", "sid-live", "Inspect release flow") == {
        "outcome": "failed",
        "detail": "session_not_replyable",
    }


@pytest.mark.parametrize("stdout", ["not json", "{}", '[]', '{"outcome":"delivered"}'])
def test_terminal_submission_malformed_response_is_unknown(monkeypatch, stdout):
    monkeypatch.setattr(
        agents.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=stdout, stderr="secret"),
    )

    assert agents.submit_to_agent("codex", "sid-live", "Inspect release flow") == {
        "outcome": "unknown",
        "detail": "invalid_agency_response",
    }


def test_targeted_message_attempts_are_append_only_and_only_success_consumes(data_dir):
    stream = db.create_stream("alpha", "session", "Alpha")
    message = db.create_targeted_message(stream["id"], "First", "codex", "sid-live", message_id="m_one")

    claimed = db.claim_message_delivery(message["id"])
    failed = db.complete_message_delivery(claimed["id"], "failed", "session_not_replyable")
    reclaimed = db.claim_message_delivery(failed["id"])
    delivered = db.complete_message_delivery(reclaimed["id"], "submitted_to_terminal", "literal_and_enter_sent")

    assert message["delivery_state"] == "pending"
    assert failed["delivery_state"] == "failed"
    assert failed["consumed_at"] is None
    assert delivered["delivery_state"] == "submitted_to_terminal"
    assert delivered["consumed_at"] is not None
    assert [attempt["outcome"] for attempt in db.list_message_delivery_attempts(message["id"])] == [
        "failed",
        "submitted_to_terminal",
    ]


def test_client_submission_key_is_unique_and_bound_to_immutable_targeted_intent(data_dir):
    stream = db.create_stream("alpha", "session", "Alpha")
    key = "portal_test_submission_database"

    first, created = db.create_or_get_targeted_message(
        stream["id"], "First", "codex", "sid-live", key
    )
    reconciled, replay_created = db.create_or_get_targeted_message(
        stream["id"], "First", "codex", "sid-live", key
    )

    assert created is True
    assert replay_created is False
    assert reconciled["id"] == first["id"]
    assert reconciled["client_submission_key"] == key
    with pytest.raises(db.MessageIdempotencyConflictError, match="different agent message"):
        db.create_or_get_targeted_message(
            stream["id"], "Changed", "codex", "sid-live", key
        )


def test_concurrent_client_submission_key_creation_returns_one_durable_message(data_dir):
    stream = db.create_stream("alpha", "session", "Alpha")

    def create():
        return db.create_or_get_targeted_message(
            stream["id"],
            "First",
            "codex",
            "sid-live",
            "portal_test_submission_concurrent_db",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))

    assert len({message["id"] for message, _created in results}) == 1
    assert sorted(created for _message, created in results) == [False, True]
    assert len(db.list_targeted_messages()) == 1


def test_generic_messages_remain_keyless_and_non_idempotent(data_dir):
    stream = db.create_stream("alpha", "session", "Alpha")

    first = db.create_message(stream["id"], "to_agent", "Same text")
    second = db.create_message(stream["id"], "to_agent", "Same text")

    assert first["id"] != second["id"]
    assert first["client_submission_key"] is None
    assert second["client_submission_key"] is None


def test_targeted_message_is_never_visible_to_generic_pull(data_dir):
    stream = db.create_stream("alpha", "session", "Alpha")
    generic = db.create_message(stream["id"], "to_agent", "Generic", message_id="m_generic")
    targeted = db.create_targeted_message(
        stream["id"], "Targeted", "codex", "sid-live", message_id="m_targeted"
    )

    queued = db.list_messages(stream["id"], direction="to_agent", unconsumed=True)

    assert [message["id"] for message in queued] == [generic["id"]]
    assert targeted["consumed_at"] is None
    with pytest.raises(db.MessageDeliveryStateError, match="targeted message"):
        db.consume_message(targeted["id"])


def test_unknown_delivery_requires_explicit_confirmation_before_retry(data_dir):
    stream = db.create_stream("alpha", "session", "Alpha")
    message = db.create_targeted_message(stream["id"], "First", "codex", "sid-live")
    db.claim_message_delivery(message["id"])
    unknown = db.complete_message_delivery(message["id"], "unknown", "enter_result_unknown")

    assert unknown["consumed_at"] is None
    with pytest.raises(db.MessageDeliveryStateError, match="cannot be submitted from state unknown"):
        db.claim_message_delivery(message["id"])
    assert db.claim_message_delivery(message["id"], allow_unknown=True)["delivery_state"] == "submitting"


def test_restart_recovers_interrupted_delivery_once_and_still_requires_confirmation(data_dir):
    stream = db.create_stream("alpha", "session", "Alpha")
    message = db.create_targeted_message(stream["id"], "First", "codex", "sid-live")
    db.claim_message_delivery(message["id"])

    db.reset_connection()
    db.connect()

    recovered = db.get_message(message["id"])
    assert recovered["delivery_state"] == "unknown"
    assert recovered["consumed_at"] is None
    assert [
        (attempt["outcome"], attempt["detail"])
        for attempt in db.list_message_delivery_attempts(message["id"])
    ] == [("unknown", "portal_restart_interrupted")]

    # Reopening the same database must not append another recovery attempt.
    db.reset_connection()
    db.connect()
    assert len(db.list_message_delivery_attempts(message["id"])) == 1

    with pytest.raises(db.MessageDeliveryStateError, match="cannot be submitted from state unknown"):
        db.claim_message_delivery(message["id"])
    assert db.claim_message_delivery(message["id"], allow_unknown=True)["delivery_state"] == "submitting"


def test_delivery_claim_is_atomic(data_dir):
    stream = db.create_stream("alpha", "session", "Alpha")
    message = db.create_targeted_message(stream["id"], "First", "codex", "sid-live")

    def claim():
        try:
            return db.claim_message_delivery(message["id"])["delivery_state"]
        except db.MessageDeliveryStateError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: claim(), range(2)))

    assert sorted(outcomes) == ["rejected", "submitting"]


def test_closed_stream_rejects_delivery_retry(data_dir):
    stream = db.create_stream("closed", "session", "Closed")
    message = db.create_targeted_message(stream["id"], "First", "codex", "sid-live")
    db.claim_message_delivery(message["id"])
    db.complete_message_delivery(message["id"], "failed", "session_not_replyable")
    db.close_stream("closed")

    with pytest.raises(db.StreamClosedError):
        db.claim_message_delivery(message["id"])
