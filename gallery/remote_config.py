"""Firebase Remote Config editing for a game's live parameters.

Lets the portal retune a shipped game's remote values (ad gating, economy
knobs) without a rebuild or a trip to the Firebase console.

The live Remote Config template is the source of truth: every read pulls the
published template, and a publish re-reads it, applies only the changed values,
and pushes it back. Nothing is cached and no template is stored here, so the
portal can never publish a stale copy over someone else's console edit.

Auth and transport are delegated to the `firebase` CLI already installed and
logged in on this host — the portal stores no service-account key. Commands run
against a temp directory via `firebase -c`, so this does not depend on any
repo checkout being present.

Per-game wiring lives in `~/.gallery/config.json`:

    "remote_config": {
      "marble-run": {
        "project": "marble-run-basegamelab",
        "groups": ["Ads"]
      }
    }

`groups` is optional; when present only those parameter groups are editable,
which keeps the page focused on the knobs a human actually retunes.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import config

CONFIG_KEY = "remote_config"
FIREBASE_BIN_DEFAULT = "firebase"
COMMAND_TIMEOUT_S = 180


class RemoteConfigError(RuntimeError):
    """A remote-config read or publish could not be completed."""


def game_settings(slug: str) -> dict[str, Any] | None:
    """Per-game remote-config wiring, or None when the game has none."""
    section = config.load_config().get(CONFIG_KEY) or {}
    settings = section.get(slug)
    if not isinstance(settings, dict) or not settings.get("project"):
        return None
    return settings


def _firebase_bin(settings: dict[str, Any]) -> str:
    return settings.get("firebase_bin") or FIREBASE_BIN_DEFAULT


def _run(args: list[str], *, cwd: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise RemoteConfigError(
            "firebase CLI not found — install firebase-tools on this host"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RemoteConfigError(f"firebase CLI timed out after {COMMAND_TIMEOUT_S}s") from exc


def read_template(settings: dict[str, Any]) -> dict[str, Any]:
    """Fetch the currently published template."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "template.json"
        result = _run(
            [
                _firebase_bin(settings),
                "remoteconfig:get",
                "--project",
                settings["project"],
                "--output",
                str(out),
                "--non-interactive",
            ],
            cwd=tmp,
        )
        if result.returncode != 0 or not out.is_file():
            raise RemoteConfigError(_cli_error("read", result))
        return json.loads(out.read_text())


def _cli_error(action: str, result: subprocess.CompletedProcess) -> str:
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    tail = detail[-1] if detail else f"exit code {result.returncode}"
    return f"firebase {action} failed: {tail}"


def _iter_param_locations(template: dict[str, Any], allowed_groups: list[str] | None):
    """Yield (group_name, params_dict) for every editable parameter container.

    Ungrouped parameters live under the template's top-level `parameters`; the
    console calls that section "(no group)".
    """
    if allowed_groups is None:
        top = template.get("parameters")
        if isinstance(top, dict) and top:
            yield None, top
    for name, group in (template.get("parameterGroups") or {}).items():
        if allowed_groups is not None and name not in allowed_groups:
            continue
        params = group.get("parameters")
        if isinstance(params, dict) and params:
            yield name, params


def editable_params(template: dict[str, Any], settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the template into a form-friendly list, sorted for a stable page."""
    allowed = settings.get("groups")
    allowed_groups = list(allowed) if isinstance(allowed, list) and allowed else None
    rows: list[dict[str, Any]] = []
    for group_name, params in _iter_param_locations(template, allowed_groups):
        for key in sorted(params):
            param = params[key]
            rows.append(
                {
                    "key": key,
                    "group": group_name,
                    "type": param.get("valueType", "STRING"),
                    "value": (param.get("defaultValue") or {}).get("value", ""),
                    "description": param.get("description", ""),
                }
            )
    return rows


def coerce_value(value_type: str, raw: str) -> str:
    """Validate a submitted value against its declared type.

    Remote Config stores every value as a string; the type only says how the
    client will parse it, so a bad number here becomes a silently-defaulted
    value on the device. Rejecting it at the form is the whole point.
    """
    text = (raw or "").strip()
    if value_type == "BOOLEAN":
        lowered = text.lower()
        if lowered in {"true", "1", "on", "yes"}:
            return "true"
        if lowered in {"false", "0", "off", "no", ""}:
            return "false"
        raise RemoteConfigError(f"expected a boolean, got {raw!r}")
    if value_type == "NUMBER":
        try:
            number = float(text)
        except ValueError as exc:
            raise RemoteConfigError(f"expected a number, got {raw!r}") from exc
        if number != number or number in (float("inf"), float("-inf")):
            raise RemoteConfigError(f"expected a finite number, got {raw!r}")
        return str(int(number)) if number.is_integer() else str(number)
    return text


def apply_updates(
    template: dict[str, Any],
    settings: dict[str, Any],
    updates: dict[str, str],
) -> tuple[dict[str, Any], list[str]]:
    """Write validated updates into a copy of the template.

    Returns the new template and the keys whose value actually changed. Only
    parameters the page exposes may be written — an unknown key is a bug or a
    hand-crafted request, and either way must not reach the console.
    """
    allowed = settings.get("groups")
    allowed_groups = list(allowed) if isinstance(allowed, list) and allowed else None
    editable = {row["key"]: row for row in editable_params(template, settings)}
    unknown = sorted(set(updates) - set(editable))
    if unknown:
        raise RemoteConfigError(f"unknown parameter(s): {', '.join(unknown)}")

    updated = json.loads(json.dumps(template))
    changed: list[str] = []
    for _group, params in _iter_param_locations(updated, allowed_groups):
        for key, param in params.items():
            if key not in updates:
                continue
            new_value = coerce_value(param.get("valueType", "STRING"), updates[key])
            default = param.setdefault("defaultValue", {})
            if default.get("value") != new_value:
                default["value"] = new_value
                changed.append(key)
    return updated, sorted(changed)


def publish(settings: dict[str, Any], updates: dict[str, str]) -> list[str]:
    """Apply updates to the live template and publish. Returns changed keys.

    A no-op edit does not publish — pushing an identical template would burn a
    Remote Config version and muddy the console's change history.
    """
    template = read_template(settings)
    updated, changed = apply_updates(template, settings, updates)
    if not changed:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        template_path = Path(tmp) / "template.json"
        template_path.write_text(json.dumps(updated, indent=2))
        # `template` resolves against the process CWD, not firebase.json, so it
        # must be absolute for the deploy to find it from the temp dir.
        firebase_json = Path(tmp) / "firebase.json"
        firebase_json.write_text(json.dumps({"remoteconfig": {"template": str(template_path)}}))
        result = _run(
            [
                _firebase_bin(settings),
                "deploy",
                "--only",
                "remoteconfig",
                "-c",
                str(firebase_json),
                "--project",
                settings["project"],
                "--non-interactive",
            ],
            cwd=tmp,
        )
        if result.returncode != 0:
            raise RemoteConfigError(_cli_error("publish", result))
    return changed
