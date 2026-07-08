"""Generate Portal phase-1 rendered HTML/header evidence artifacts."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from gallery import config, db

EVIDENCE_DIR = Path(__file__).resolve().parent
ASSETS = EVIDENCE_DIR / "assets"
GENERATED_ID_RE = re.compile(r"\b(req|p|s)_[0-9a-fA-F]+\b")


def tiny_png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000100ffff03000006000557bfabd4000000"
        "0049454e44ae426082"
    )


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    id_map: dict[str, str] = {}
    id_counters: dict[str, int] = {}
    old_data_dir = os.environ.get("GALLERY_DATA_DIR")
    os.environ.pop("GALLERY_TELEGRAM_BOT_TOKEN", None)
    os.environ.pop("GALLERY_TELEGRAM_CHAT_ID", None)
    try:
        with tempfile.TemporaryDirectory(
            prefix="portal-phase1-evidence-data-",
            dir="/private/tmp",
        ) as data_dir:
            os.environ["GALLERY_DATA_DIR"] = data_dir
            db.reset_connection()
            cfg = config.init_config(force=True)
            token = cfg["token"]

            from gallery.server import app, notify

            notify.send_doorbell = lambda *_args, **_kwargs: None

            project = "portal/phase1-e2e"
            slug = "proj-portal-phase1-e2e"

            with TestClient(app) as client:
                report = client.post(
                    f"/api/streams/{slug}/posts",
                    headers=auth_headers(token),
                    data={
                        "type": "report",
                        "title": "Portal phase 1 report",
                        "author": "codex",
                        "body": json.dumps({"summary": "report pushes auto-create streams"}),
                    },
                    files=[
                        (
                            "files",
                            (
                                "portal-report.html",
                                b"<html><body><h1>Portal Report Rendered</h1></body></html>",
                                "text/html",
                            ),
                        )
                    ],
                )
                report.raise_for_status()
                report_post = report.json()["post"]
                report_media_path = report_post["body"]["files"][0]["media_path"]
                report_media_url = f"/media/{report_post['id']}/{report_media_path}"

                cookie_seed = client.get(f"/s/{slug}?token={token}")
                cookie_seed.raise_for_status()
                report_media = client.get(report_media_url)
                report_media.raise_for_status()

                request = client.post(
                    "/api/requests",
                    headers=auth_headers(token),
                    data={
                        "title": "Portal phase 1 before after",
                        "kind": "before-after",
                        "project": project,
                        "context": "Choose the after state that best matches the report.",
                    },
                    files=[
                        ("before", ("before.png", tiny_png_bytes(), "image/png")),
                        ("files", ("after-1.png", tiny_png_bytes(), "image/png")),
                        (
                            "files",
                            (
                                "after-2.html",
                                b"<html><body><h1>HTML variant must download</h1></body></html>",
                                "text/html",
                            ),
                        ),
                    ],
                )
                request.raise_for_status()
                req_id = request.json()["id"]
                request_detail = client.get(
                    f"/api/requests/{req_id}",
                    headers=auth_headers(token),
                )
                request_detail.raise_for_status()
                html_variant_path = request_detail.json()["variants"][1]["media_path"]

                request_page = client.get(f"/r/{req_id}")
                request_page.raise_for_status()
                save_text("request-page.html", request_page.text, token, id_map, id_counters)

                html_variant_media = client.get(f"/media/{req_id}/{html_variant_path}")
                html_variant_media.raise_for_status()

                decision_file_post = client.post(
                    f"/api/streams/{slug}/posts",
                    headers=auth_headers(token),
                    data={
                        "type": "decision",
                        "title": "Decision post with HTML file",
                        "author": "codex",
                        "body": json.dumps(
                            {
                                "request_id": req_id,
                                "note": "files on decision posts are never inline",
                            }
                        ),
                    },
                    files=[
                        (
                            "files",
                            (
                                "decision.html",
                                b"<html><body><h1>Decision post attachment</h1></body></html>",
                                "text/html",
                            ),
                        )
                    ],
                )
                decision_file_post.raise_for_status()
                decision_post = decision_file_post.json()["post"]
                decision_media_path = decision_post["body"]["files"][0]["media_path"]
                decision_media = client.get(f"/media/{decision_post['id']}/{decision_media_path}")
                decision_media.raise_for_status()

                verdict = client.post(
                    f"/r/{req_id}/decide",
                    json={"selected": [1], "comment": "Use the first after state."},
                )
                verdict.raise_for_status()

                stream_page = client.get(f"/s/{slug}")
                stream_page.raise_for_status()
                save_text("stream-page.html", stream_page.text, token, id_map, id_counters)

                close = client.post(f"/api/streams/{slug}/close", headers=auth_headers(token))
                close.raise_for_status()
                archived_stream_page = client.get(f"/s/{slug}")
                archived_stream_page.raise_for_status()
                archived_request_page = client.get(f"/r/{req_id}")
                archived_request_page.raise_for_status()
                rejected_revision = client.post(
                    f"/r/{req_id}/decide",
                    json={"selected": [2], "comment": "late change"},
                )
                assert rejected_revision.status_code == 409

                save_text(
                    "archived-stream-page.html",
                    archived_stream_page.text,
                    token,
                    id_map,
                    id_counters,
                )
                save_text(
                    "archived-request-page.html",
                    archived_request_page.text,
                    token,
                    id_map,
                    id_counters,
                )
                save_text("report-media.html", report_media.text, token, id_map, id_counters)
                save_text(
                    "report-media-headers.txt",
                    header_dump(report_media),
                    token,
                    id_map,
                    id_counters,
                )
                save_text(
                    "request-variant-media-headers.txt",
                    header_dump(html_variant_media),
                    token,
                    id_map,
                    id_counters,
                )
                save_text(
                    "decision-post-media-headers.txt",
                    header_dump(decision_media),
                    token,
                    id_map,
                    id_counters,
                )
                save_text(
                    "flow-summary.txt",
                    "\n".join(
                        [
                            f"stream_slug: {slug}",
                            f"report_post_id: {report_post['id']}",
                            f"request_id: {req_id}",
                            f"decision_post_id: {decision_post['id']}",
                            f"post_close_verdict_revision_status: {rejected_revision.status_code}",
                            f"post_close_verdict_revision_detail: {rejected_revision.json()['detail']}",
                        ]
                    )
                    + "\n",
                    token,
                    id_map,
                    id_counters,
                )

            for path in ASSETS.iterdir():
                if path.is_file():
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    assert token not in content, path
    finally:
        db.reset_connection()
        if old_data_dir is None:
            os.environ.pop("GALLERY_DATA_DIR", None)
        else:
            os.environ["GALLERY_DATA_DIR"] = old_data_dir

    print(f"wrote portal phase-1 evidence assets to {ASSETS}")


if __name__ == "__main__":
    main()
