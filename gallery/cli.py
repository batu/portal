"""gallery — CLI for posting decision requests and reading verdicts back."""

import argparse
import glob
import json
import re
import sys
import time
from pathlib import Path

from . import client, config

STREAM_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?$")


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


def _legacy_stream_slug(project: str | None) -> str:
    if not project or not project.strip():
        return "inbox"
    slug = re.sub(r"[^a-z0-9]+", "-", project.strip().lower()).strip("-")
    return f"proj-{slug or 'project'}"


def _stream_decision_metadata(stream: str, request_id: str, status: str, error: str | None = None) -> dict:
    metadata = {
        "stream": stream,
        "type": "decision",
        "body": {"request_id": request_id},
        "status": status,
    }
    if error is not None:
        metadata["error"] = error
    return metadata


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
    }
    try:
        result = client.post_multipart(base_url, token, "/api/requests", fields, request_files)
    except client.GalleryClientError as exc:
        _exit_client_error(exc)

    if args.stream is not None:
        request_id = result.get("id")
        if not request_id:
            print("error: request response missing id", file=sys.stderr)
            sys.exit(1)
        if args.stream == _legacy_stream_slug(args.project):
            result = {**result, "stream_post": _stream_decision_metadata(args.stream, request_id, "already-attached")}
        else:
            try:
                stream_post = client.create_stream_post(
                    base_url,
                    token,
                    args.stream,
                    "decision",
                    args.title,
                    "portal",
                    body={"request_id": request_id},
                    files=[],
                )
            except client.GalleryClientError as exc:
                result = {
                    **result,
                    "stream_post": _stream_decision_metadata(args.stream, request_id, "attach-failed", str(exc)),
                }
                print(json.dumps(result))
                suffix = f" (request created: {request_id})"
                print(f"error: {exc}{suffix}", file=sys.stderr)
                sys.exit(1)
            result = {**result, "stream_post": stream_post}
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


def cmd_report(args):
    base_url, token = config.client_config()
    files = _resolve_files([args.file_html, *args.assets])
    try:
        result = client.create_stream_post(
            base_url,
            token,
            args.stream,
            "report",
            args.title,
            "portal",
            body={},
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
        if time.time() >= deadline:
            print(f"timed out after {args.timeout}s waiting for a decision", file=sys.stderr)
            sys.exit(2)
        time.sleep(args.interval)


def cmd_status(args):
    base_url, token = config.client_config()
    try:
        r = client.get_json(base_url, token, f"/api/requests/{args.id}")
    except client.GalleryClientError as exc:
        _exit_client_error(exc)
    print(json.dumps(r, indent=2))


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
        choices=["pick-one", "pick-many", "rank", "approve", "comment", "before-after"],
    )
    p.add_argument("--project", default=None)
    p.add_argument("--stream", default=None, type=_stream_slug, help="Also attach this decision request to a Portal stream")
    p.add_argument("--before", default=None, help="Optional before image for before/after decisions")
    p.add_argument("--context", default=None, help="Optional markdown context blurb")
    p.add_argument("--manifest", default=None, help="Path to a JSON file mapping filename -> {caption, meta}")
    p.add_argument("files", nargs="+", help="File paths or globs, in display order")

    p = sub.add_parser("stream", help="Create or close Portal streams")
    stream_sub = p.add_subparsers(dest="stream_command", required=True)

    sp = stream_sub.add_parser("new", help="Create a Portal stream")
    sp.add_argument("slug", type=_stream_slug)
    sp.add_argument("--kind", default="session", choices=["session", "pinned"])
    sp.add_argument("--title", default=None)

    sp = stream_sub.add_parser("close", help="Close a Portal stream")
    sp.add_argument("slug", type=_stream_slug)

    p = sub.add_parser("report", help="Post an HTML report to a Portal stream")
    p.add_argument("--stream", required=True, type=_stream_slug)
    p.add_argument("--title", required=True)
    p.add_argument("file_html")
    p.add_argument("assets", nargs="*")

    p = sub.add_parser("wait", help="Block until a request is decided, then print the verdict")
    p.add_argument("id")
    p.add_argument("--timeout", type=int, default=3600)
    p.add_argument("--interval", type=int, default=5)

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
        "report": cmd_report,
        "wait": cmd_wait,
        "status": cmd_status,
        "list": cmd_list,
        "serve": cmd_serve,
    }[args.command](args)


if __name__ == "__main__":
    main()
