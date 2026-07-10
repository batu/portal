"""gallery — CLI for posting decision requests and reading verdicts back."""

import argparse
import glob
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from . import client, config, trello_watch

STREAM_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?$")
STREAM_SLUG_MAX_LENGTH = 128
PROJECT_STREAM_PREFIX = "proj-"


def _resolve_files(patterns: list[str]) -> list[Path]:
    paths = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern)) or [pattern]
        for m in matches:
            paths.append(_resolve_file(m))
    if not paths:
        print("error: no files given", file=sys.stderr)
        sys.exit(1)
    return paths


def _resolve_file(path: str) -> Path:
    p = Path(path)
    if not p.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    return p


def _exit_client_error(exc: client.GalleryClientError) -> None:
    print(f"error: {exc}", file=sys.stderr)
    sys.exit(1)


def _stream_slug(value: str) -> str:
    if not STREAM_SLUG_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("invalid stream slug")
    return value


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _legacy_stream_slug(project: str | None) -> str:
    if not project or not project.strip():
        return "inbox"
    slug = re.sub(r"[^a-z0-9]+", "-", project.strip().lower()).strip("-")
    max_project_slug_length = STREAM_SLUG_MAX_LENGTH - len(PROJECT_STREAM_PREFIX)
    slug = slug or "project"
    if len(slug) > max_project_slug_length:
        digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:8]
        suffix = f"-{digest}"
        stem = slug[: max_project_slug_length - len(suffix)].strip("-") or "project"
        slug = f"{stem}{suffix}"
    return f"{PROJECT_STREAM_PREFIX}{slug}"


def _preflight_stream(base_url: str, token: str, slug: str) -> None:
    try:
        stream = client.get_stream(base_url, token, slug)
    except client.GalleryClientError as exc:
        if exc.status == 404:
            return
        _exit_client_error(exc)
    if stream.get("closed_at") is not None:
        print(f"error: stream is closed: {slug}", file=sys.stderr)
        sys.exit(1)


def _sleep_if_time_remains(deadline: float, interval: int) -> bool:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return False
    time.sleep(min(interval, remaining))
    return True


def cmd_init(args):
    cfg = config.init_config(force=args.force)
    print(f"Gallery data dir: {config.data_dir()}")
    print(f"Config: {config.config_path()}")
    print(f"Phone URL (first visit sets a cookie): {cfg['url']}?token={cfg['token']}")
    if not cfg.get("telegram_bot_token") or not cfg.get("telegram_chat_id"):
        print(
            "Doorbell notifications are OFF. Set telegram_bot_token and telegram_chat_id "
            "in config.json (or GALLERY_TELEGRAM_BOT_TOKEN / GALLERY_TELEGRAM_CHAT_ID) to enable.",
            file=sys.stderr,
        )


def cmd_post(args):
    base_url, token = config.client_config()
    if args.stream is not None:
        _preflight_stream(base_url, token, args.stream)

    files = _resolve_files(args.files)
    request_files = files
    if args.before:
        before = _resolve_file(args.before)
        if before.resolve() in {path.resolve() for path in files}:
            print("error: before image must not also be a candidate file", file=sys.stderr)
            sys.exit(1)
        request_files = [("before", before), *files]

    manifest = None
    if args.manifest:
        manifest = Path(args.manifest).read_text()

    fields = {
        "title": args.title,
        "project": args.project,
        "kind": args.kind,
        "context": args.context,
        "manifest": manifest,
        "step": args.step,
        "purpose": args.purpose,
        "ask": args.ask,
        "stream": args.stream,
    }
    try:
        result = client.post_multipart(base_url, token, "/api/requests", fields, request_files)
    except client.GalleryClientError as exc:
        _exit_client_error(exc)

    print(json.dumps(result))


def cmd_stream(args):
    base_url, token = config.client_config()
    try:
        if args.stream_command == "new":
            result = client.create_stream(base_url, token, args.slug, args.kind, args.title or args.slug)
        elif args.stream_command == "close":
            result = client.close_stream(base_url, token, args.slug)
        else:
            raise AssertionError(f"unhandled stream command: {args.stream_command}")
    except client.GalleryClientError as exc:
        _exit_client_error(exc)
    print(json.dumps(result))


def _load_journey_doc(path: str) -> dict:
    text = _resolve_file(path).read_text()
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"error: invalid journey doc JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(doc, dict) or not isinstance(doc.get("steps"), list):
        print("error: journey doc must be a JSON object with a 'steps' list", file=sys.stderr)
        sys.exit(1)
    return {"steps": doc["steps"]}


def cmd_journey(args):
    base_url, token = config.client_config()
    try:
        if args.journey_command == "post":
            doc = _load_journey_doc(args.doc)
            result = client.upsert_journey(base_url, token, args.slug, args.title, doc)
        elif args.journey_command == "get":
            result = client.get_journey(base_url, token, args.slug)
        elif args.journey_command == "list":
            result = client.list_journeys(base_url, token)
        else:
            raise AssertionError(f"unhandled journey command: {args.journey_command}")
    except client.GalleryClientError as exc:
        _exit_client_error(exc)
    print(json.dumps(result))


def cmd_close(args):
    base_url, token = config.client_config()
    try:
        result = client.close_request(base_url, token, args.id, args.reason)
    except client.GalleryClientError as exc:
        _exit_client_error(exc)
    print(json.dumps(result))


def cmd_supersede(args):
    base_url, token = config.client_config()
    try:
        result = client.supersede_request(base_url, token, args.id, args.successor)
    except client.GalleryClientError as exc:
        _exit_client_error(exc)
    print(json.dumps(result))


def cmd_report(args):
    base_url, token = config.client_config()
    files = _resolve_files([args.file_html, *args.assets])
    body = {
        k: v
        for k, v in {"step": args.step, "purpose": args.purpose, "ask": args.ask}.items()
        if v is not None
    }
    try:
        result = client.create_stream_post(
            base_url,
            token,
            args.stream,
            "report",
            args.title,
            "portal",
            body=body,
            files=files,
        )
    except client.GalleryClientError as exc:
        _exit_client_error(exc)
    print(json.dumps(result))


def cmd_wait(args):
    base_url, token = config.client_config()
    deadline = time.time() + args.timeout
    while True:
        try:
            r = client.get_json(base_url, token, f"/api/requests/{args.id}")
        except client.GalleryClientError as exc:
            _exit_client_error(exc)
        if r["status"] == "decided":
            print(json.dumps(r["verdict"]))
            return
        if r["status"] == "superseded":
            print(f"request superseded; live version: {r.get('superseded_by')}", file=sys.stderr)
            sys.exit(3)
        if r["status"] == "closed":
            print(f"request closed: {r.get('close_reason')}", file=sys.stderr)
            sys.exit(3)
        if time.time() >= deadline:
            print(f"timed out after {args.timeout}s waiting for a decision", file=sys.stderr)
            sys.exit(2)
        time.sleep(args.interval)


def cmd_ask(args):
    base_url, token = config.client_config()
    started_at = time.monotonic()
    deadline = started_at + args.timeout
    try:
        ask_message = client.create_stream_message(base_url, token, args.stream, "to_human", args.question)
        while True:
            replies = client.list_stream_messages(
                base_url,
                token,
                args.stream,
                since=ask_message["created_at"],
                direction="to_agent",
                unconsumed=True,
            )
            if replies:
                reply = replies[0]
                client.consume_message(base_url, token, reply["id"])
                print(
                    json.dumps(
                        {
                            "reply": reply["text"],
                            "message_id": reply["id"],
                            "elapsed_s": time.monotonic() - started_at,
                        }
                    )
                )
                return
            if not _sleep_if_time_remains(deadline, args.interval):
                print(json.dumps({"timeout": True}))
                sys.exit(2)
    except client.GalleryClientError as exc:
        _exit_client_error(exc)


def cmd_pull(args):
    base_url, token = config.client_config()
    deadline = time.monotonic() + args.timeout
    try:
        while True:
            messages = client.list_stream_messages(
                base_url,
                token,
                args.stream,
                direction="to_agent",
                unconsumed=True,
            )
            if messages:
                message = messages[0]
                client.consume_message(base_url, token, message["id"])
                print(json.dumps({"text": message["text"], "message_id": message["id"]}))
                return
            if not _sleep_if_time_remains(deadline, args.interval):
                print(json.dumps({"empty": True}))
                sys.exit(3)
    except client.GalleryClientError as exc:
        _exit_client_error(exc)


def cmd_trello_watch(args):
    try:
        with trello_watch.catchable_sigterm():
            watcher = trello_watch.build_watcher(
                Path(args.repo),
                trigger_list=args.trigger_list,
                max_stage=args.max_stage,
            )
            while True:
                summary = watcher.poll_once()
                print(json.dumps(summary), flush=True)
                if args.once:
                    if _trello_watch_retryable_summary(summary):
                        sys.exit(75)
                    return
                time.sleep(args.interval)
    except (trello_watch.WatchError, client.GalleryClientError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args):
    base_url, token = config.client_config()
    try:
        r = client.get_json(base_url, token, f"/api/requests/{args.id}")
    except client.GalleryClientError as exc:
        _exit_client_error(exc)
    print(json.dumps(r, indent=2))


def _trello_watch_retryable_summary(summary: dict) -> bool:
    return bool(summary.get("transient_error")) or any(
        isinstance(card, dict) and card.get("retryable") for card in summary.get("cards", [])
    )


def cmd_list(args):
    base_url, token = config.client_config()
    path = "/api/requests"
    params = []
    if args.open:
        params.append("status=open")
    if args.project:
        params.append(f"project={args.project}")
    if params:
        path += "?" + "&".join(params)
    try:
        rows = client.get_json(base_url, token, path)
    except client.GalleryClientError as exc:
        _exit_client_error(exc)

    if args.json:
        print(json.dumps(rows, indent=2))
        return

    if not rows:
        print("No requests.")
        return
    for r in rows:
        print(f"{r['id']}  [{r['status']:7}]  {r['kind']:9}  {r['variant_count']}v  {r['project'] or '-':20}  {r['title']}")


def cmd_serve(_args):
    import uvicorn

    cfg = config.load_config()
    uvicorn.run("gallery.server:app", host=cfg["host"], port=cfg["port"])


ASK_EPILOG = """\
client-side polling: posts a to_human question, then polls plain GET messages
for the first unconsumed to_agent reply after the ask timestamp.

Exit/stdout contract:
  success 0: {"reply": "...", "message_id": "...", "elapsed_s": 1.23}
  client/API error 1: stderr only, no branch JSON
  timeout 2: {"timeout": true}
  argparse usage error 2: stderr only, no branch JSON
"""


PULL_EPILOG = """\
client-side polling: fetches the oldest unconsumed to_agent message and consumes
it before printing. Default --timeout 0 performs one non-blocking check.

Exit/stdout contract:
  success 0: {"text": "...", "message_id": "..."}
  client/API error 1: stderr only, no branch JSON
  empty 3: {"empty": true}
  argparse usage error 2: stderr only, no branch JSON
"""


TRELLO_WATCH_EPILOG = """\
foreground polling: each poll prints one JSON summary line. Use --once for a
single machine-checkable pass.

Summary shape:
  {"picked_up": 0, "advanced": 0, "stopped": 0, "errored": 0, "skipped": 0,
   "cards": [{"card_id": "...", "short_link": "...", "stream_slug": "...",
              "status": "...", "action": "...", "reason": "..."}]}

Exit/stdout contract:
  success 0: one JSON summary line
  retryable one-shot failure 75: JSON summary includes "transient_error"
  client/config/API error 1: stderr only, no branch JSON
  argparse usage error 2: stderr only, no branch JSON
"""


def main():
    parser = argparse.ArgumentParser(prog="portal", description="Portal review hub for agent outputs and decisions")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Create ~/.gallery/ and generate a bearer token").add_argument(
        "--force", action="store_true", help="Regenerate config even if one already exists"
    )

    p = sub.add_parser("post", help="Post a new decision request")
    p.add_argument("--title", required=True)
    p.add_argument(
        "--kind",
        required=True,
        choices=["pick-one", "pick-many", "rank", "approve", "comment", "before-after", "view"],
        help="Decision kind; 'view' posts an interactive HTML view (first .html file is the entry) whose verdict is opaque JSON",
    )
    p.add_argument("--project", default=None)
    p.add_argument("--stream", default=None, type=_stream_slug, help="Set this Portal stream as the request's owning stream (created if missing); closing it makes the request read-only")
    p.add_argument("--before", default=None, help="Optional before image for before/after decisions")
    p.add_argument("--context", default=None, help="Optional markdown context blurb")
    p.add_argument("--manifest", default=None, help="Path to a JSON file mapping filename -> {caption, meta}")
    p.add_argument("--step", default=None, help="Optional: which step the human is looking at (e.g. 'frame picking')")
    p.add_argument("--purpose", default=None, help="Optional: one-line purpose of this request")
    p.add_argument("--ask", default=None, help="Optional: what the human is being asked to do")
    p.add_argument("files", nargs="+", help="File paths or globs, in display order")

    p = sub.add_parser("stream", help="Create or close Portal streams")
    stream_sub = p.add_subparsers(dest="stream_command", required=True)

    sp = stream_sub.add_parser("new", help="Create a Portal stream")
    sp.add_argument("slug", type=_stream_slug)
    sp.add_argument("--kind", default="session", choices=["session", "pinned"])
    sp.add_argument("--title", default=None)

    sp = stream_sub.add_parser("close", help="Close a Portal stream")
    sp.add_argument("slug", type=_stream_slug)

    p = sub.add_parser("journey", help="Post/read native game journeys (the /g/<slug> story pages)")
    journey_sub = p.add_subparsers(dest="journey_command", required=True)

    jp = journey_sub.add_parser("post", help="Post or re-post (update-in-place) a journey doc at a stable slug")
    jp.add_argument("--slug", required=True, type=_stream_slug, help="Stable slug; the page lives at /g/<slug>")
    jp.add_argument("--title", required=True)
    jp.add_argument("--doc", required=True, help='Path to a JSON file: {"steps": [ {title, summary?, media?, request_id?} ]}')

    jp = journey_sub.add_parser("get", help="Fetch a journey by slug")
    jp.add_argument("--slug", required=True, type=_stream_slug)

    journey_sub.add_parser("list", help="List journeys")

    p = sub.add_parser("close", help="Close a request with a reason (no fabricated verdict)")
    p.add_argument("id")
    p.add_argument("--reason", required=True, help="Why the request is being closed")

    p = sub.add_parser("supersede", help="Mark a request superseded by a live successor request")
    p.add_argument("id")
    p.add_argument("--successor", required=True, help="Request id of the live successor")

    p = sub.add_parser("report", help="Post an HTML report to a Portal stream")
    p.add_argument("--stream", required=True, type=_stream_slug)
    p.add_argument("--title", required=True)
    p.add_argument("--step", default=None, help="Optional: which step this report covers")
    p.add_argument("--purpose", default=None, help="Optional: one-line purpose of this report")
    p.add_argument("--ask", default=None, help="Optional: what the human is being asked to do")
    p.add_argument("file_html")
    p.add_argument("assets", nargs="*")

    p = sub.add_parser("wait", help="Block until a request is decided, then print the verdict")
    p.add_argument("id")
    p.add_argument("--timeout", type=int, default=3600)
    p.add_argument("--interval", type=int, default=5)

    p = sub.add_parser(
        "ask",
        help="Ask a human and block for a reply",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=ASK_EPILOG,
    )
    p.add_argument("--stream", required=True, type=_stream_slug)
    p.add_argument("question")
    p.add_argument("--timeout", type=_non_negative_int, default=1800)
    p.add_argument("--interval", type=_positive_int, default=15)

    p = sub.add_parser(
        "pull",
        help="Fetch and consume the next queued steering note",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=PULL_EPILOG,
    )
    p.add_argument("--stream", required=True, type=_stream_slug)
    p.add_argument("--timeout", type=_non_negative_int, default=0)
    p.add_argument("--interval", type=_positive_int, default=15)

    p = sub.add_parser(
        "trello-watch",
        help="Poll Trello cards and run one twf stage per pass",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=TRELLO_WATCH_EPILOG,
    )
    p.add_argument("--repo", required=True, help="twf project repo whose agents/config.json supplies Trello lists")
    p.add_argument(
        "--list",
        dest="trigger_list",
        default=None,
        help="Trigger Trello list id or configured list name (default: todo)",
    )
    p.add_argument("--interval", type=_positive_int, default=trello_watch.DEFAULT_INTERVAL_SECONDS)
    p.add_argument("--once", action="store_true", help="Run one poll pass and exit")
    p.add_argument("--max-stage", default=trello_watch.DEFAULT_MAX_STAGE, help="Last configured stage the watcher may reach")

    p = sub.add_parser("status", help="Print a request's current state")
    p.add_argument("id")

    p = sub.add_parser("list", help="List requests")
    p.add_argument("--open", action="store_true", help="Only open requests")
    p.add_argument("--project", default=None)
    p.add_argument("--json", action="store_true")

    sub.add_parser("serve", help="Run the server in the foreground (used by launchd)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    {
        "init": cmd_init,
        "post": cmd_post,
        "stream": cmd_stream,
        "journey": cmd_journey,
        "close": cmd_close,
        "supersede": cmd_supersede,
        "report": cmd_report,
        "wait": cmd_wait,
        "ask": cmd_ask,
        "pull": cmd_pull,
        "trello-watch": cmd_trello_watch,
        "status": cmd_status,
        "list": cmd_list,
        "serve": cmd_serve,
    }[args.command](args)


if __name__ == "__main__":
    main()
