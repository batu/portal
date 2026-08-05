import json
import subprocess

import pytest

from gallery import agents, db


def _seed_cookie(client, token):
    response = client.get(f"/?token={token}")
    assert response.status_code == 200


def _unexpected_bridge_call(*_args, **_kwargs):
    raise AssertionError("invalid input reached the Agency subprocess bridge")


def test_bridge_directory_exposes_only_agency_provider_capabilities(monkeypatch):
    payload = [
        {
            "provider": provider,
            "sid": f"sid-{provider}",
            "label": provider,
            "replyable": True,
        }
        for provider in ("claude", "codex", "pi", "gemini")
    ]

    def fake_run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(agents.subprocess, "run", fake_run)

    sessions = agents.list_replyable_agents()

    assert [session["provider"] for session in sessions] == ["claude", "codex", "pi"]


def test_regex_valid_unsupported_provider_stops_before_bridge_and_endpoint(
    client,
    token,
    monkeypatch,
):
    monkeypatch.setattr(agents.subprocess, "run", _unexpected_bridge_call)

    assert agents.submit_to_agent("gemini", "sid-live", "Inspect this") == {
        "outcome": "failed",
        "detail": "invalid_target",
    }

    _seed_cookie(client, token)
    response = client.post(
        "/agents/gemini/sid-live/messages",
        json={"text": "Inspect this"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid agent provider"
    assert db.list_targeted_messages() == []


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
def test_unicode_paragraph_separator_stops_before_bridge_and_endpoint(
    separator,
    client,
    token,
    monkeypatch,
):
    text = f"first{separator}second"
    monkeypatch.setattr(agents.subprocess, "run", _unexpected_bridge_call)

    assert agents.submit_to_agent("codex", "sid-live", text) == {
        "outcome": "failed",
        "detail": "invalid_message",
    }

    _seed_cookie(client, token)
    response = client.post(
        "/agents/codex/sid-live/messages",
        json={"text": text},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "text must be one paragraph without control characters"
    assert db.list_targeted_messages() == []
