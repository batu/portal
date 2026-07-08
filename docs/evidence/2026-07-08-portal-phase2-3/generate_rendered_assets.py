"""Generate Portal phase-2/3 rendered HTML/header evidence artifacts."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from gallery import config, db, trello_watch

EVIDENCE_DIR = Path(__file__).resolve().parent
ASSETS = EVIDENCE_DIR / "assets"
GENERATED_ID_RE = re.compile(r"\b(req|p|s|m)_[0-9a-fA-F]+\b")

BOARD_ID = "board-1"
TODO_ID = "list-todo"
WORKED_ID = "list-worked"
MAX_ID = "list-max"
BLOCKED_ID = "list-blocked"


class IsoClock:
    def __init__(self):
        self.current = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        value = self.current
        self.current += timedelta(seconds=1)
        return value.isoformat()


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def tiny_png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000100ffff03000006000557bfabd4000000"
        "0049454e44ae426082"
    )


def normalize_generated_ids(
    text: str,
    id_map: dict[str, str],
    id_counters: dict[str, int],
) -> str:
    def replace(match: re.Match[str]) -> str:
        generated_id = match.group(0)
        if generated_id not in id_map:
            prefix = match.group(1)
            id_counters[prefix] = id_counters.get(prefix, 0) + 1
            id_map[generated_id] = f"{prefix}_evidence_{id_counters[prefix]}"
        return id_map[generated_id]

    return GENERATED_ID_RE.sub(replace, text)


def normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def save_text(
    name: str,
    text: str,
    token: str,
    id_map: dict[str, str],
    id_counters: dict[str, int],
) -> None:
    assert token not in text, f"raw bearer token leaked into {name}"
    normalized = normalize_text(normalize_generated_ids(text, id_map, id_counters))
    (ASSETS / name).write_text(normalized, encoding="utf-8")


def header_dump(response) -> str:
    names = [
        "content-type",
        "x-content-type-options",
        "content-security-policy",
        "content-disposition",
    ]
    lines = [f"status: {response.status_code}"]
    for name in names:
        lines.append(f"{name}: {response.headers.get(name, '<absent>')}")
    return "\n".join(lines) + "\n"


def write_repo(root: Path) -> Path:
    repo = root / "repo"
    (repo / "agents").mkdir(parents=True)
    payload = {
        "trello": {
            "board_id": BOARD_ID,
            "board_name": "phase23 board",
            "lists": {
                "todo": TODO_ID,
                "worked": WORKED_ID,
                "aesthetics_reviewed": MAX_ID,
                "blocked_on_batu": BLOCKED_ID,
            },
        }
    }
    (repo / "agents" / "config.json").write_text(json.dumps(payload), encoding="utf-8")
    return repo


def card(list_id: str = TODO_ID) -> dict:
    return {
        "id": "card-1",
        "shortLink": "hVtTtwRa",
        "name": "Phase 2/3 proof",
        "idList": list_id,
        "idBoard": BOARD_ID,
        "closed": False,
        "url": "https://trello.com/c/hVtTtwRa",
    }


def handoff() -> dict:
    return {
        "date": "2026-07-08T10:00:00Z",
        "data": {
            "text": "\n".join(
                [
                    "Done: implemented one stage",
                    "Verified-how: focused fake watcher run",
                    "Remaining: next twf stage",
                    "Surprises: none",
                ]
            )
        },
    }


class FakeTrello:
    def __init__(self, watched_card: dict):
        self.trigger_cards = [watched_card]
        self.cards = {watched_card["id"]: watched_card}
        self.actions = {watched_card["id"]: [handoff()]}
        self.comments: list[tuple[str, str]] = []

    def list_cards(self, _list_id: str) -> list[dict]:
        return list(self.trigger_cards)

    def get_card(self, card_id: str) -> dict:
        return self.cards[card_id]

    def list_comment_actions(self, card_id: str) -> list[dict]:
        return list(self.actions.get(card_id, []))

    def add_comment(self, card_id: str, text: str) -> dict:
        self.comments.append((card_id, text))
        return {"id": f"comment-{len(self.comments)}"}


class FakePortal:
    def __init__(self):
        self.reports: list[dict] = []
        self.messages: list[dict] = []

    def stream_url(self, slug: str) -> str:
        return f"http://portal.local/s/{slug}"

    def post_report(self, slug: str, title: str, text: str, *, kind: str, card_url: str | None = None) -> dict:
        self.reports.append(
            {
                "slug": slug,
                "title": title,
                "text": text,
                "kind": kind,
                "card_url": card_url,
            }
        )
        return {"post": {"id": f"p_{len(self.reports)}"}}

    def post_human_message(self, slug: str, text: str) -> dict:
        self.messages.append({"slug": slug, "text": text})
        return {"id": f"m_{len(self.messages)}"}


def generate_stream_and_header_assets(client: TestClient, token: str, id_map: dict[str, str], id_counters: dict[str, int]) -> None:
    slug = "phase23-inbox-evidence"
    question_text = "Which rollout should I assume?"
    answer_text = "Assume the cookie twin path is correct."
    note_text = "Please review the queued steering note next turn."

    question = client.post(
        f"/api/streams/{slug}/messages",
        headers=auth_headers(token),
        json={"direction": "to_human", "text": question_text},
    )
    question.raise_for_status()
    question_id = question.json()["id"]

    unanswered = client.get(f"/s/{slug}?token={token}")
    unanswered.raise_for_status()
    save_text("stream-unanswered-question.html", unanswered.text, token, id_map, id_counters)

    answer = client.post(f"/s/{slug}/answer", json={"text": answer_text, "question_id": question_id})
    answer.raise_for_status()
    answer_id = answer.json()["id"]

    answered_queued = client.get(f"/s/{slug}")
    answered_queued.raise_for_status()
    save_text("stream-answered-question-queued-answer.html", answered_queued.text, token, id_map, id_counters)

    consumed_answer = client.post(f"/api/messages/{answer_id}/consume", headers=auth_headers(token))
    consumed_answer.raise_for_status()
    answer_picked_up = client.get(f"/s/{slug}")
    answer_picked_up.raise_for_status()
    save_text("stream-picked-up-answer.html", answer_picked_up.text, token, id_map, id_counters)

    note = client.post(f"/s/{slug}/note", json={"text": note_text})
    note.raise_for_status()
    note_id = note.json()["id"]
    note_queued = client.get(f"/s/{slug}")
    note_queued.raise_for_status()
    save_text("stream-queued-note.html", note_queued.text, token, id_map, id_counters)

    consumed_note = client.post(f"/api/messages/{note_id}/consume", headers=auth_headers(token))
    consumed_note.raise_for_status()
    note_picked_up = client.get(f"/s/{slug}")
    note_picked_up.raise_for_status()
    save_text("stream-picked-up-note.html", note_picked_up.text, token, id_map, id_counters)

    stream = db.get_stream(slug)
    assert stream is not None
    db.create_message(stream["id"], "to_human", "Closed question still readable")
    db.create_message(stream["id"], "to_agent", "Closed note still readable")
    closed = client.post(f"/api/streams/{slug}/close", headers=auth_headers(token))
    closed.raise_for_status()
    archived = client.get(f"/s/{slug}")
    archived.raise_for_status()
    save_text("stream-archived.html", archived.text, token, id_map, id_counters)

    rejected_closed_report = client.post(
        f"/api/streams/{slug}/posts",
        headers=auth_headers(token),
        data={
            "type": "report",
            "title": "Inbox evidence report",
            "author": "codex",
            "body": json.dumps({"summary": "report HTML stays inline"}),
        },
        files=[
            (
                "files",
                (
                    "report.html",
                    b"<html><body><h1>Inline report</h1></body></html>",
                    "text/html",
                ),
            )
        ],
    )
    assert rejected_closed_report.status_code == 409

    media_slug = "phase23-media-evidence"
    report = client.post(
        f"/api/streams/{media_slug}/posts",
        headers=auth_headers(token),
        data={
            "type": "report",
            "title": "Inbox evidence report",
            "author": "codex",
            "body": json.dumps({"summary": "report HTML stays inline"}),
        },
        files=[
            (
                "files",
                (
                    "report.html",
                    b"<html><body><h1>Inline report</h1></body></html>",
                    "text/html",
                ),
            )
        ],
    )
    report.raise_for_status()
    report_post = report.json()["post"]
    report_media_path = report_post["body"]["files"][0]["media_path"]
    client.get(f"/s/{media_slug}?token={token}").raise_for_status()
    report_media = client.get(f"/media/{report_post['id']}/{report_media_path}")
    report_media.raise_for_status()

    request = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={
            "title": "Inbox evidence HTML variant",
            "kind": "pick-one",
            "project": "portal/phase23-media-evidence",
        },
        files=[
            ("files", ("safe.png", tiny_png_bytes(), "image/png")),
            (
                "files",
                (
                    "variant.html",
                    b"<html><body><h1>Attachment variant</h1></body></html>",
                    "text/html",
                ),
            ),
        ],
    )
    request.raise_for_status()
    req_id = request.json()["id"]
    detail = client.get(f"/api/requests/{req_id}", headers=auth_headers(token))
    detail.raise_for_status()
    html_variant_path = detail.json()["variants"][1]["media_path"]
    html_variant = client.get(f"/media/{req_id}/{html_variant_path}")
    html_variant.raise_for_status()

    decision = client.post(
        f"/api/streams/{media_slug}/posts",
        headers=auth_headers(token),
        data={
            "type": "decision",
            "title": "Decision post HTML attachment",
            "author": "codex",
            "body": json.dumps({"request_id": req_id}),
        },
        files=[
            (
                "files",
                (
                    "decision.html",
                    b"<html><body><h1>Decision attachment</h1></body></html>",
                    "text/html",
                ),
            )
        ],
    )
    decision.raise_for_status()
    decision_post = decision.json()["post"]
    decision_media_path = decision_post["body"]["files"][0]["media_path"]
    decision_media = client.get(f"/media/{decision_post['id']}/{decision_media_path}")
    decision_media.raise_for_status()

    save_text("report-media-headers.txt", header_dump(report_media), token, id_map, id_counters)
    save_text("request-variant-media-headers.txt", header_dump(html_variant), token, id_map, id_counters)
    save_text("decision-post-media-headers.txt", header_dump(decision_media), token, id_map, id_counters)
    save_text(
        "flow-summary.txt",
        "\n".join(
            [
                f"inbox_stream_slug: {slug}",
                f"media_stream_slug: {media_slug}",
                f"question_id: {question_id}",
                f"answer_id: {answer_id}",
                f"note_id: {note_id}",
                f"report_post_id: {report_post['id']}",
                f"request_id: {req_id}",
                f"decision_post_id: {decision_post['id']}",
                f"closed_report_rejection_status: {rejected_closed_report.status_code}",
            ]
        )
        + "\n",
        token,
        id_map,
        id_counters,
    )


def generate_watch_transcript(root: Path, token: str, id_map: dict[str, str], id_counters: dict[str, int]) -> None:
    repo = write_repo(root)
    watched_card = card()
    trello = FakeTrello(watched_card)
    portal = FakePortal()
    runner_calls = []
    env = {
        "TRELLO_API_KEY": "trello-key",
        "TRELLO_TOKEN": "trello-token",
        "GALLERY_TOKEN": "portal-secret",
        "PATH": "/bin",
    }

    def runner(repo_arg: Path, short: str, run_env: dict[str, str]) -> trello_watch.RunResult:
        runner_calls.append(
            {
                "repo": "<fake-repo>",
                "short": short,
                "env_keys": sorted(run_env),
                "equivalent_command": f"twf run-card {short} --worktree",
            }
        )
        return trello_watch.RunResult(0, "fake twf run-card hVtTtwRa --worktree completed")

    watcher = trello_watch.Watcher(
        trello_watch.load_watch_config(repo, max_stage="aesthetics_reviewed"),
        trello,
        portal,
        runner=runner,
        env=env,
        clock=lambda: 1.0,
        redaction_secrets=["portal-secret"],
    )
    first = watcher.poll_once()
    watched_card["idList"] = MAX_ID
    trello.trigger_cards = []
    second = watcher.poll_once()
    third = watcher.poll_once()

    transcript = json.dumps(
        {
            "boundaries": {
                "network": "fake Trello and fake Portal only",
                "subprocess": "fake runner only",
            },
            "first_summary": first,
            "second_summary": second,
            "third_summary": third,
            "runner_calls": runner_calls,
            "portal_reports": portal.reports,
            "portal_messages": portal.messages,
            "trello_comments": trello.comments,
        },
        indent=2,
        sort_keys=True,
    )
    forbidden = [
        token,
        "trello-key",
        "trello-token",
        "portal-secret",
        "Authorization: Bearer",
        "?token=",
        "&token=",
    ]
    for value in forbidden:
        assert value not in transcript, value
    save_text("watch-transcript.json", transcript, token, id_map, id_counters)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    id_map: dict[str, str] = {}
    id_counters: dict[str, int] = {}
    env_names = [
        "GALLERY_DATA_DIR",
        "GALLERY_TELEGRAM_BOT_TOKEN",
        "GALLERY_TELEGRAM_CHAT_ID",
    ]
    old_env = {name: os.environ.get(name) for name in env_names}
    old_env_present = {name: name in os.environ for name in env_names}
    old_now_iso = db.now_iso
    from gallery import server

    old_notify_to_human_message = server._notify_to_human_message
    os.environ.pop("GALLERY_TELEGRAM_BOT_TOKEN", None)
    os.environ.pop("GALLERY_TELEGRAM_CHAT_ID", None)
    try:
        with tempfile.TemporaryDirectory(prefix="portal-phase23-evidence-", dir="/private/tmp") as data_dir:
            os.environ["GALLERY_DATA_DIR"] = data_dir
            db.reset_connection()
            db.now_iso = IsoClock()
            server._notify_to_human_message = lambda *_args, **_kwargs: None
            cfg = config.init_config(force=True)
            token = cfg["token"]

            from gallery.server import app

            with TestClient(app) as client:
                generate_stream_and_header_assets(client, token, id_map, id_counters)
            generate_watch_transcript(Path(data_dir), token, id_map, id_counters)

            for path in ASSETS.iterdir():
                if path.is_file():
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    assert token not in content, path
    finally:
        server._notify_to_human_message = old_notify_to_human_message
        db.now_iso = old_now_iso
        db.reset_connection()
        for name in env_names:
            if old_env_present[name]:
                os.environ[name] = old_env[name] or ""
            else:
                os.environ.pop(name, None)

    print(f"wrote portal phase-2/3 evidence assets to {ASSETS}")


if __name__ == "__main__":
    main()
