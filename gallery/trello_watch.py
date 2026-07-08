"""Foreground Trello watcher for advancing twf cards into Portal streams."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import client, config

DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_MAX_STAGE = "aesthetics_reviewed"
BLOCKED_STAGE = "blocked_on_batu"
STATE_VERSION = 1
RUN_TIMEOUT_SECONDS = 6 * 60 * 60
OUTPUT_TAIL_CHARS = 8000
AUTHOR = "portal trello-watch"

RUNTIME_ENV_ALLOWLIST = {
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOGNAME",
    "PATH",
    "SHELL",
    "TERM",
    "TMP",
    "TMPDIR",
    "TEMP",
    "USER",
    "UV_CACHE_DIR",
    "VIRTUAL_ENV",
}
REQUIRED_TRELLO_ENV = ("TRELLO_API_KEY", "TRELLO_TOKEN")


class WatchError(Exception):
    """Raised for startup/configuration and non-transient watcher failures."""


class TrelloAPIError(WatchError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Trello HTTP {status}: {message}")
        self.status = status
        self.message = message

    @property
    def transient(self) -> bool:
        return self.status == 429 or self.status >= 500 or self.status == 0


@dataclass(frozen=True)
class WatchConfig:
    repo: Path
    board_id: str
    board_name: str | None
    lists: dict[str, str]
    trigger_list_id: str
    trigger_stage: str | None
    max_stage: str
    state_path: Path

    @property
    def ordered_stages(self) -> list[str]:
        return list(self.lists)

    def stage_for_list_id(self, list_id: str | None) -> str | None:
        if not list_id:
            return None
        for stage, configured_id in self.lists.items():
            if configured_id == list_id:
                return stage
        return None

    def stage_index(self, stage: str) -> int:
        try:
            return self.ordered_stages.index(stage)
        except ValueError as exc:
            raise WatchError(f"unknown Trello stage in config: {stage}") from exc


@dataclass(frozen=True)
class RunResult:
    returncode: int
    output: str
    timed_out: bool = False


class StateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": STATE_VERSION, "cards": {}}
        try:
            state = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise WatchError(f"corrupt trello-watch state at {self.path}: {exc}") from exc
        if not isinstance(state, dict) or not isinstance(state.get("cards"), dict):
            raise WatchError(f"invalid trello-watch state at {self.path}")
        state.setdefault("version", STATE_VERSION)
        return state

    def save(self, state: dict[str, Any]) -> None:
        config.atomic_write_json(self.path, state)


class TrelloClient:
    def __init__(
        self,
        api_key: str,
        token: str,
        *,
        base_url: str = "https://api.trello.com/1",
        opener: Callable[..., Any] | None = None,
    ):
        self.api_key = api_key
        self.token = token
        self.base_url = base_url.rstrip("/")
        self._opener = opener or urllib.request.urlopen

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
    ) -> Any:
        query = {"key": self.api_key, "token": self.token}
        if params:
            query.update(params)
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(query)}"
        encoded_data = urllib.parse.urlencode(data).encode("utf-8") if data else None
        headers = {"Accept": "application/json"}
        if encoded_data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
        try:
            with self._opener(req, timeout=30) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(detail)
                detail = parsed.get("message") or parsed.get("detail") or detail
            except json.JSONDecodeError:
                pass
            raise TrelloAPIError(exc.code, detail) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TrelloAPIError(0, str(exc)) from exc
        return json.loads(body) if body else {}

    def list_cards(self, list_id: str) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            f"/lists/{urllib.parse.quote(list_id, safe='')}/cards",
            params={"fields": "id,shortLink,name,idList,closed,idBoard,url"},
        )

    def get_card(self, card_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/cards/{urllib.parse.quote(card_id, safe='')}",
            params={"fields": "id,shortLink,name,idList,closed,idBoard,url"},
        )

    def get_card_list(self, card_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/cards/{urllib.parse.quote(card_id, safe='')}/list",
            params={"fields": "id,name"},
        )

    def list_comment_actions(self, card_id: str) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            f"/cards/{urllib.parse.quote(card_id, safe='')}/actions",
            params={"filter": "commentCard", "limit": "1000"},
        )

    def add_comment(self, card_id: str, text: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/cards/{urllib.parse.quote(card_id, safe='')}/actions/comments",
            data={"text": text},
        )


class PortalReporter:
    def __init__(self, base_url: str, token: str):
        parsed = urllib.parse.urlsplit(base_url.rstrip("/"))
        self.base_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
        self.token = token

    def stream_url(self, slug: str) -> str:
        return f"{self.base_url}/s/{urllib.parse.quote(slug, safe='')}"

    def post_report(self, slug: str, title: str, text: str, *, kind: str, card_url: str | None = None) -> dict:
        report_path = _write_report_html(slug, title, text, kind=kind, card_url=card_url)
        return client.create_stream_post(
            self.base_url,
            self.token,
            slug,
            "report",
            title,
            AUTHOR,
            body={"kind": kind},
            files=[report_path],
        )

    def post_human_message(self, slug: str, text: str) -> dict:
        return client.create_stream_message(self.base_url, self.token, slug, "to_human", text)


class Watcher:
    def __init__(
        self,
        watch_config: WatchConfig,
        trello: Any,
        portal: Any,
        *,
        state_store: StateStore | None = None,
        runner: Callable[[Path, str, dict[str, str]], RunResult] | None = None,
        clock: Callable[[], float] | None = None,
        env: dict[str, str] | None = None,
    ):
        self.config = watch_config
        self.trello = trello
        self.portal = portal
        self.state_store = state_store or StateStore(watch_config.state_path)
        self.runner = runner or run_twf_card
        self.clock = clock or time.time
        self.env = env or dict(os.environ)

    def poll_once(self) -> dict[str, Any]:
        state = self.state_store.load()
        state["version"] = STATE_VERSION
        state["context"] = {
            "repo": str(self.config.repo),
            "board_id": self.config.board_id,
            "trigger_list_id": self.config.trigger_list_id,
            "max_stage": self.config.max_stage,
        }
        summary: dict[str, Any] = {"picked_up": 0, "advanced": 0, "stopped": 0, "errored": 0, "skipped": 0}

        try:
            trigger_cards = self.trello.list_cards(self.config.trigger_list_id)
        except TrelloAPIError as exc:
            if exc.transient:
                summary["transient_error"] = str(exc)
                return summary
            raise

        for card in trigger_cards:
            self._validate_card_board(card)
            if self._pickup_card(state, card):
                summary["picked_up"] += 1

        for card_id in list(state["cards"]):
            card_state = state["cards"][card_id]
            self._process_card(state, card_state)
            action = card_state.pop("last_action", None)
            if action in {"advanced", "stopped", "errored", "skipped"}:
                summary[action] += 1
        self.state_store.save(state)
        return summary

    def _pickup_card(self, state: dict[str, Any], card: dict[str, Any]) -> bool:
        card_id = _required_card_field(card, "id")
        if card_id in state["cards"]:
            return False

        short_link = _short_link(card)
        title = str(card.get("name") or short_link)
        stream_slug = stream_slug_for_card(short_link)
        state["cards"][card_id] = {
            "card_id": card_id,
            "short_link": short_link,
            "title": title,
            "stream_slug": stream_slug,
            "card_url": card.get("url"),
            "status": "tracking",
            "pickup_reported": False,
            "human_notified": False,
            "last_seen_list_id": card.get("idList"),
        }
        self.state_store.save(state)
        self._post_pickup(state["cards"][card_id])
        state["cards"][card_id]["pickup_reported"] = True
        self.state_store.save(state)
        return True

    def _process_card(self, state: dict[str, Any], card_state: dict[str, Any]) -> None:
        if not card_state.get("pickup_reported"):
            self._post_pickup(card_state)
            card_state["pickup_reported"] = True
            self.state_store.save(state)

        status = card_state.get("status", "tracking")
        if status == "running":
            self._mark_error(
                state,
                card_state,
                "Watcher restarted while twf run-card was marked running; manual inspection required.",
            )
            return
        if status == "errored":
            self._ensure_human_notified(state, card_state, card_state.get("stop_message") or "Card is errored.")
            card_state["last_action"] = "skipped"
            return
        if status == "pending_report":
            self._finish_success_report(state, card_state)
            card_state["last_action"] = "advanced"
            return
        if status == "stopped":
            card_state["last_action"] = "skipped"
            return

        try:
            card = self.trello.get_card(card_state["card_id"])
        except TrelloAPIError as exc:
            if exc.transient:
                card_state["last_transient_error"] = str(exc)
                card_state["last_action"] = "skipped"
                return
            raise
        self._validate_card_board(card)
        card_state["title"] = str(card.get("name") or card_state.get("title") or card_state["short_link"])
        card_state["last_seen_list_id"] = card.get("idList")
        card_state["card_url"] = card.get("url") or card_state.get("card_url")

        stop_message = self._stop_message(card_state, card)
        if stop_message is not None:
            card_state["status"] = "stopped"
            card_state["stop_message"] = stop_message
            self._ensure_human_notified(state, card_state, stop_message)
            card_state["last_action"] = "stopped"
            return

        self._run_one_stage(state, card_state)

    def _post_pickup(self, card_state: dict[str, Any]) -> None:
        title = f"Picked up {card_state['title']}"
        text = "\n".join(
            [
                f"Picked up {card_state['title']}.",
                f"Trello card: {card_state.get('card_url') or card_state['short_link']}",
                f"Watcher stream: {self.portal.stream_url(card_state['stream_slug'])}",
            ]
        )
        self.portal.post_report(card_state["stream_slug"], title, text, kind="pickup", card_url=card_state.get("card_url"))

    def _stop_message(self, card_state: dict[str, Any], card: dict[str, Any]) -> str | None:
        if card.get("closed"):
            return f"Trello card {card_state['short_link']} is closed; no twf run was started."
        stage = self.config.stage_for_list_id(card.get("idList"))
        if stage is None:
            return (
                f"Trello card {card_state['short_link']} is in an unknown list; "
                "human review is required before twf can continue."
            )
        card_state["last_seen_stage"] = stage
        if stage == BLOCKED_STAGE:
            return f"Trello card {card_state['short_link']} is blocked_on_batu; human input is needed."
        if self.config.stage_index(stage) >= self.config.stage_index(self.config.max_stage):
            return (
                f"Trello card {card_state['short_link']} reached {stage}; "
                f"watcher max-stage is {self.config.max_stage}, so it will not advance further."
            )
        return None

    def _run_one_stage(self, state: dict[str, Any], card_state: dict[str, Any]) -> None:
        started_at = _iso_now(self.clock)
        card_state["status"] = "running"
        card_state["run_started_at"] = started_at
        self.state_store.save(state)

        env = build_runner_env(self.env)
        result = self.runner(self.config.repo, card_state["short_link"], env)
        tail = sanitize_text(_tail(result.output), self.env)
        finished_at = _iso_now(self.clock)
        card_state["last_run"] = {
            "started_at": started_at,
            "finished_at": finished_at,
            "returncode": result.returncode,
            "tail": tail,
            "timed_out": result.timed_out,
            "handoff_reported": False,
            "trello_commented": False,
        }
        if result.returncode != 0 or result.timed_out:
            reason = "twf run-card timed out" if result.timed_out else f"twf run-card exited {result.returncode}"
            self._mark_error(state, card_state, reason)
            return

        card_state["status"] = "pending_report"
        self.state_store.save(state)
        self._finish_success_report(state, card_state)
        card_state["last_action"] = "advanced"

    def _finish_success_report(self, state: dict[str, Any], card_state: dict[str, Any]) -> None:
        run = card_state.get("last_run") or {}
        if not run:
            self._mark_error(state, card_state, "Missing recorded twf run result; manual inspection required.")
            return
        if not run.get("handoff_reported"):
            try:
                actions = self.trello.list_comment_actions(card_state["card_id"])
            except TrelloAPIError as exc:
                if exc.transient:
                    card_state["last_transient_error"] = str(exc)
                    self.state_store.save(state)
                    return
                self._mark_error(state, card_state, f"Could not fetch Trello handoff comments: {exc}")
                return

            handoff = newest_handoff_comment(actions, since=run.get("started_at"))
            if handoff is None:
                handoff = "No structured twf handoff comment was found after this run. Human review required."
            handoff = sanitize_text(handoff, self.env)
            title = f"twf handoff for {card_state['title']}"
            self.portal.post_report(
                card_state["stream_slug"],
                title,
                handoff,
                kind="handoff",
                card_url=card_state.get("card_url"),
            )
            run["handoff_text"] = handoff
            run["handoff_reported"] = True
            self.state_store.save(state)

        if not run.get("trello_commented"):
            stream_url = self.portal.stream_url(card_state["stream_slug"])
            self.trello.add_comment(
                card_state["card_id"],
                f"Portal report: {stream_url}\nStatus: completed one twf stage for {card_state['short_link']}.",
            )
            run["trello_commented"] = True
            self.state_store.save(state)

        card_state["status"] = "tracking"
        card_state["human_notified"] = False
        self.state_store.save(state)

    def _mark_error(self, state: dict[str, Any], card_state: dict[str, Any], reason: str) -> None:
        run = card_state.get("last_run") or {}
        tail = run.get("tail") or reason
        message = f"{reason}\n\nOutput tail:\n{tail}"
        card_state["status"] = "errored"
        card_state["stop_message"] = f"Trello watcher needs human help for {card_state['short_link']}: {reason}"
        self.state_store.save(state)
        if not run.get("failure_reported"):
            self.portal.post_report(
                card_state["stream_slug"],
                f"twf failed for {card_state['title']}",
                message,
                kind="failure",
                card_url=card_state.get("card_url"),
            )
            run["failure_reported"] = True
            card_state["last_run"] = run
            self.state_store.save(state)
        self._ensure_human_notified(state, card_state, card_state["stop_message"])
        card_state["last_action"] = "errored"

    def _ensure_human_notified(self, state: dict[str, Any], card_state: dict[str, Any], text: str) -> None:
        if card_state.get("human_notified"):
            return
        self.portal.post_human_message(card_state["stream_slug"], text)
        card_state["human_notified"] = True
        self.state_store.save(state)

    def _validate_card_board(self, card: dict[str, Any]) -> None:
        board_id = card.get("idBoard")
        if board_id is not None and board_id != self.config.board_id:
            raise WatchError(
                f"Trello card {card.get('id') or '<unknown>'} belongs to board {board_id}, "
                f"not configured board {self.config.board_id}"
            )


def build_watcher(repo: Path, trigger_list: str | None = None, max_stage: str = DEFAULT_MAX_STAGE) -> Watcher:
    watch_config = load_watch_config(repo, trigger_list=trigger_list, max_stage=max_stage)
    env = dict(os.environ)
    for name in REQUIRED_TRELLO_ENV:
        if not env.get(name):
            raise WatchError(f"missing required environment variable: {name}")
    base_url, token = config.client_config()
    return Watcher(
        watch_config,
        TrelloClient(env["TRELLO_API_KEY"], env["TRELLO_TOKEN"]),
        PortalReporter(base_url, token),
        env=env,
    )


def run_loop(
    watcher: Watcher,
    *,
    interval: int = DEFAULT_INTERVAL_SECONDS,
    once: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    while True:
        watcher.poll_once()
        if once:
            return
        sleep(interval)


def load_watch_config(repo: Path, *, trigger_list: str | None = None, max_stage: str = DEFAULT_MAX_STAGE) -> WatchConfig:
    repo = repo.expanduser().resolve()
    if not repo.is_dir():
        raise WatchError(f"repo does not exist: {repo}")
    config_path = repo / "agents" / "config.json"
    if not config_path.is_file():
        raise WatchError(f"missing target repo Trello config: {config_path}")
    try:
        raw = json.loads(config_path.read_text())
    except json.JSONDecodeError as exc:
        raise WatchError(f"malformed target repo config {config_path}: {exc}") from exc
    trello = raw.get("trello")
    if not isinstance(trello, dict):
        raise WatchError(f"target repo config missing trello block: {config_path}")
    board_id = trello.get("board_id")
    lists = trello.get("lists")
    if not isinstance(board_id, str) or not board_id:
        raise WatchError("target repo trello.board_id is required")
    if not isinstance(lists, dict) or not lists or not all(isinstance(k, str) and isinstance(v, str) for k, v in lists.items()):
        raise WatchError("target repo trello.lists must be a non-empty object of stage names to list ids")

    trigger_stage, trigger_list_id = _resolve_list_value(lists, trigger_list or "todo", allow_raw=True)
    max_stage_key, _max_list_id = _resolve_list_value(lists, max_stage, allow_raw=False)
    if max_stage_key is None:
        raise WatchError(f"unknown --max-stage: {max_stage}")
    digest = hashlib.sha256(f"{repo}|{board_id}|{trigger_list_id}".encode("utf-8")).hexdigest()[:16]
    state_path = config.data_dir() / "trello-watch" / f"trello-watch-state-{digest}.json"
    return WatchConfig(
        repo=repo,
        board_id=board_id,
        board_name=trello.get("board_name"),
        lists=dict(lists),
        trigger_list_id=trigger_list_id,
        trigger_stage=trigger_stage,
        max_stage=max_stage_key,
        state_path=state_path,
    )


def _resolve_list_value(lists: dict[str, str], value: str, *, allow_raw: bool) -> tuple[str | None, str]:
    if value in lists:
        return value, lists[value]
    normalized = _normalize_stage(value)
    if normalized in lists:
        return normalized, lists[normalized]
    for stage, list_id in lists.items():
        if value == list_id:
            return stage, list_id
    if allow_raw:
        return None, value
    raise WatchError(f"unknown Trello list/stage: {value}")


def _normalize_stage(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def stream_slug_for_card(short_link: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", short_link.lower()).strip("-")
    if not slug:
        raise WatchError("Trello card shortLink cannot produce a Portal stream slug")
    return f"trello-{slug}"[:128].strip("-")


def build_runner_env(source: dict[str, str] | None = None) -> dict[str, str]:
    source = source or os.environ
    env = {name: source[name] for name in RUNTIME_ENV_ALLOWLIST if source.get(name)}
    for name in REQUIRED_TRELLO_ENV:
        if not source.get(name):
            raise WatchError(f"missing required environment variable: {name}")
        env[name] = source[name]
    return env


def run_twf_card(repo: Path, short_link: str, env: dict[str, str]) -> RunResult:
    try:
        completed = subprocess.run(
            ["twf", "run-card", short_link, "--worktree"],
            cwd=repo,
            env=env,
            shell=False,
            text=True,
            capture_output=True,
            timeout=RUN_TIMEOUT_SECONDS,
            check=False,
        )
        return RunResult(completed.returncode, f"{completed.stdout}\n{completed.stderr}")
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        output = f"{stdout}\n{stderr}\ntwf run-card timed out after {RUN_TIMEOUT_SECONDS}s"
        return RunResult(124, output, timed_out=True)


def newest_handoff_comment(actions: list[dict[str, Any]], *, since: str | None = None) -> str | None:
    candidates = []
    since_dt = _parse_trello_time(since) if since else None
    for action in actions:
        text = (((action.get("data") or {}).get("text")) if isinstance(action.get("data"), dict) else None)
        if not isinstance(text, str) or not _looks_like_handoff(text):
            continue
        action_dt = _parse_trello_time(action.get("date"))
        if since_dt is not None and action_dt is not None and action_dt < since_dt:
            continue
        candidates.append((action_dt or datetime.min.replace(tzinfo=timezone.utc), text))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def sanitize_text(text: str, secrets_source: dict[str, str] | None = None) -> str:
    scrubbed = text
    secrets_source = secrets_source or os.environ
    secret_names = {
        "TRELLO_API_KEY",
        "TRELLO_TOKEN",
        "GALLERY_TOKEN",
        "GALLERY_TELEGRAM_BOT_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_TOKEN",
    }
    for name in secret_names:
        value = secrets_source.get(name)
        if value:
            scrubbed = scrubbed.replace(value, "[redacted]")
    scrubbed = re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s]+", r"\1[redacted]", scrubbed)
    scrubbed = re.sub(r"(?i)([?&](?:token|key)=)[^&#\s]+", r"\1[redacted]", scrubbed)
    return scrubbed


def _write_report_html(slug: str, title: str, text: str, *, kind: str, card_url: str | None) -> Path:
    safe_slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-") or "trello-watch"
    digest = hashlib.sha256(f"{title}\n{text}\n{time.time_ns()}".encode("utf-8")).hexdigest()[:12]
    reports_dir = config.data_dir() / "trello-watch" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{safe_slug}-{kind}-{digest}.html"
    card_link = ""
    if card_url:
        escaped_url = html.escape(card_url, quote=True)
        card_link = f'<p><a href="{escaped_url}">Trello card</a></p>'
    escaped_title = html.escape(title)
    escaped_text = html.escape(text)
    doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escaped_title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; line-height: 1.45; color: #1f2933; }}
    main {{ max-width: 920px; }}
    h1 {{ font-size: 20px; margin: 0 0 12px; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #f5f7fa; border: 1px solid #d9e2ec; border-radius: 6px; padding: 16px; }}
    .kind {{ color: #52606d; font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em; }}
  </style>
</head>
<body>
  <main>
    <div class="kind">{html.escape(kind)}</div>
    <h1>{escaped_title}</h1>
    {card_link}
    <pre>{escaped_text}</pre>
  </main>
</body>
</html>
"""
    path.write_text(doc)
    return path


def _looks_like_handoff(text: str) -> bool:
    labels = ("Done:", "Verified-how:", "Remaining:", "Surprises:")
    return sum(label in text for label in labels) >= 2 or "twf handoff" in text.lower()


def _parse_trello_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso_now(clock: Callable[[], float]) -> str:
    return datetime.fromtimestamp(clock(), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _short_link(card: dict[str, Any]) -> str:
    value = card.get("shortLink")
    if isinstance(value, str) and value:
        return value
    url = card.get("shortUrl") or card.get("url")
    if isinstance(url, str) and "/c/" in url:
        return url.split("/c/", 1)[1].split("/", 1)[0]
    raise WatchError(f"Trello card {card.get('id') or '<unknown>'} missing shortLink")


def _required_card_field(card: dict[str, Any], key: str) -> str:
    value = card.get(key)
    if not isinstance(value, str) or not value:
        raise WatchError(f"Trello card missing required field: {key}")
    return value


def _tail(text: str) -> str:
    return text[-OUTPUT_TAIL_CHARS:]
