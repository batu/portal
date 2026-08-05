"""Bounded bridge to Agency's live Fleet session authority.

Portal deliberately does not inspect tmux or agent transcripts itself.  It
accepts only the small JSON contract emitted by ``agency fleet`` and exposes a
curated DTO to the web layer.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import unicodedata

FLEET_TIMEOUT_SECONDS = 3.0
SUBMIT_TIMEOUT_SECONDS = 5.0
MAX_AGENT_TEXT_LENGTH = 4_000
AGENCY_PROVIDERS = frozenset({"claude", "codex", "pi"})

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DETAIL_RE = re.compile(r"^[a-z0-9_]{1,80}$")
_OUTCOMES = {"submitted_to_terminal", "failed", "unknown"}
_INVALID_MESSAGE_CATEGORIES = {"Cc", "Zl", "Zp"}


class AgentBridgeError(RuntimeError):
    """A safe, user-displayable Fleet directory error."""


def valid_provider(value: object) -> bool:
    return isinstance(value, str) and value in AGENCY_PROVIDERS


def valid_session_id(value: object) -> bool:
    return isinstance(value, str) and _SESSION_ID_RE.fullmatch(value) is not None


def valid_single_paragraph(value: object) -> bool:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_AGENT_TEXT_LENGTH
    ):
        return False
    return not any(unicodedata.category(char) in _INVALID_MESSAGE_CATEGORIES for char in value)


def _curated_text(value: object, *, maximum: int, fallback: str = "") -> str:
    if not isinstance(value, str):
        return fallback
    value = value.strip()
    if not value or len(value) > maximum or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return fallback
    return value


def _freshness(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not math.isfinite(result) or result < 0:
        return None
    return result


def _replyable_session(row: object) -> dict | None:
    if not isinstance(row, dict):
        return None
    provider = row.get("provider")
    sid = row.get("sid")
    if (
        not valid_provider(provider)
        or not valid_session_id(sid)
        or row.get("replyable") is not True
    ):
        return None
    label = _curated_text(row.get("label"), maximum=80, fallback=f"{provider} agent")
    return {
        "provider": provider,
        "sid": sid,
        "label": label,
        "project": _curated_text(row.get("project"), maximum=100),
        "task": _curated_text(row.get("task"), maximum=120),
        "state": _curated_text(row.get("state"), maximum=32, fallback="unknown"),
        "freshness_seconds": _freshness(row.get("freshness_seconds")),
        "replyable": True,
    }


def list_replyable_agents() -> list[dict]:
    try:
        completed = subprocess.run(
            ["agency", "fleet", "--reply-targets", "--json"],
            capture_output=True,
            text=True,
            timeout=FLEET_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AgentBridgeError("Agency is unavailable.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AgentBridgeError("Agency did not return Fleet state in time.") from exc

    if completed.returncode != 0:
        raise AgentBridgeError("Agency could not read Fleet state.")
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AgentBridgeError("Agency returned invalid Fleet state.") from exc
    if not isinstance(payload, list):
        raise AgentBridgeError("Agency returned invalid Fleet state.")

    sessions = [session for row in payload if (session := _replyable_session(row)) is not None]
    return sorted(sessions, key=lambda row: (row["project"].lower(), row["label"].lower(), row["sid"]))


def _submission_result(stdout: str) -> dict | None:
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("outcome") not in _OUTCOMES:
        return None
    detail = payload.get("detail") or payload.get("reason")
    if not isinstance(detail, str) or _DETAIL_RE.fullmatch(detail) is None:
        detail = {
            "submitted_to_terminal": "literal_and_enter_sent",
            "failed": "agency_reported_failure",
            "unknown": "terminal_submission_unknown",
        }[payload["outcome"]]
    return {"outcome": payload["outcome"], "detail": detail}


def submit_to_agent(provider: str, session_id: str, text: str) -> dict:
    """Submit literal text to one exact Fleet session without using a shell.

    ``unknown`` is intentionally sticky: once the process started, a timeout or
    malformed response cannot prove whether tmux received some or all input.
    """
    if not valid_provider(provider) or not valid_session_id(session_id):
        return {"outcome": "failed", "detail": "invalid_target"}
    if not valid_single_paragraph(text):
        return {"outcome": "failed", "detail": "invalid_message"}
    try:
        completed = subprocess.run(
            ["agency", "fleet", "--provider", provider, "--reply", session_id, "--json"],
            input=text,
            capture_output=True,
            text=True,
            timeout=SUBMIT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return {"outcome": "failed", "detail": "agency_unavailable"}
    except subprocess.TimeoutExpired:
        return {"outcome": "unknown", "detail": "agency_timeout"}

    result = _submission_result(completed.stdout)
    if result is None:
        return {"outcome": "unknown", "detail": "invalid_agency_response"}
    return result
