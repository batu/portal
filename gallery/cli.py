"""gallery — CLI for posting decision requests and reading verdicts back."""

import argparse
import glob
import json
import sys
import time
from pathlib import Path

from . import client, config


def _resolve_files(patterns: list[str]) -> list[Path]:
    paths = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern)) or [pattern]
        for m in matches:
            p = Path(m)
            if not p.is_file():
                print(f"error: file not found: {m}", file=sys.stderr)
                sys.exit(1)
            paths.append(p)
    if not paths:
        print("error: no files given", file=sys.stderr)
        sys.exit(1)
    return paths


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
    files = _resolve_files(args.files)

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
        result = client.post_multipart(base_url, token, "/api/requests", fields, files)
    except client.GalleryClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result))


def cmd_wait(args):
    base_url, token = config.client_config()
    deadline = time.time() + args.timeout
    while True:
        try:
            r = client.get_json(base_url, token, f"/api/requests/{args.id}")
        except client.GalleryClientError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
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
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
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
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

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
    parser = argparse.ArgumentParser(prog="gallery", description="Persistent pick-by-number review hub")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Create ~/.gallery/ and generate a bearer token").add_argument(
        "--force", action="store_true", help="Regenerate config even if one already exists"
    )

    p = sub.add_parser("post", help="Post a new decision request")
    p.add_argument("--title", required=True)
    p.add_argument("--kind", required=True, choices=["pick-one", "pick-many", "rank", "approve", "comment"])
    p.add_argument("--project", default=None)
    p.add_argument("--context", default=None, help="Optional markdown context blurb")
    p.add_argument("--manifest", default=None, help="Path to a JSON file mapping filename -> {caption, meta}")
    p.add_argument("files", nargs="+", help="File paths or globs, in display order")

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
        "wait": cmd_wait,
        "status": cmd_status,
        "list": cmd_list,
        "serve": cmd_serve,
    }[args.command](args)


if __name__ == "__main__":
    main()
