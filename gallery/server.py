"""Gallery FastAPI app: JSON API + server-rendered web UI + media serving."""

import json
import logging
import math
import mimetypes
import re
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import markdown as md_lib
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from . import config, db, notify

log = logging.getLogger("gallery.server")

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".avi"}
STREAM_KINDS = {"session", "pinned"}
POST_TYPES = {"report", "decision"}
POST_UPLOAD_SOFT_CAP_BYTES = 200 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024
MAX_TITLE_LENGTH = 300
MAX_AUTHOR_LENGTH = 200
MAX_BODY_JSON_BYTES = 1_000_000
STREAM_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?$")
SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

app = FastAPI(title="Gallery")

_here = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(_here / "static")), name="static")
templates = Jinja2Templates(directory=str(_here / "templates"))

COOKIE_NAME = "gallery_token"


def _ago(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        delta = datetime.now(timezone.utc) - dt
        mins = int(delta.total_seconds() // 60)
        if mins < 1:
            return "just now"
        if mins < 60:
            return f"{mins}m ago"
        hours = mins // 60
        if hours < 24:
            return f"{hours}h ago"
        return f"{hours // 24}d ago"
    except (ValueError, TypeError):
        return ""


templates.env.filters["ago"] = _ago


# --- auth helpers ---


def _server_token() -> str:
    return config.load_config()["token"]


def require_api_token(request: Request) -> None:
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    if not token or token != _server_token():
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")


def web_token_ok(request: Request) -> bool:
    expected = _server_token()
    qs_token = request.query_params.get("token")
    if qs_token and qs_token == expected:
        return True
    cookie_token = request.cookies.get(COOKIE_NAME)
    return bool(cookie_token and cookie_token == expected)


def _maybe_set_cookie(response, request: Request) -> None:
    qs_token = request.query_params.get("token")
    if qs_token and qs_token == _server_token():
        response.set_cookie(COOKIE_NAME, qs_token, httponly=True, samesite="lax", max_age=3600 * 24 * 365)


# --- health (unauthenticated) ---


@app.get("/api/health")
def health():
    return {"status": "ok", "open_count": db.open_count()}


# --- JSON API ---


def _media_type_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return "video" if ext in VIDEO_EXTS else "image"


def _safe_upload_name(filename: str | None, fallback: str) -> str:
    name = Path(filename or fallback).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return (name or fallback)[:120]


def _safe_media_filename(filename: str) -> bool:
    if not filename or filename in {".", ".."}:
        return False
    if "/" in filename or "\\" in filename:
        return False
    return not any(ord(ch) < 32 for ch in filename)


def _is_text_html(media_type: str | None) -> bool:
    return bool(media_type and media_type.split(";", 1)[0].strip().lower() == "text/html")


def _report_html_media_type(owner_id: str, filename: str, guessed_media_type: str | None) -> str | None:
    post = db.get_post(owner_id)
    if post is None or post.get("type") != "report":
        return None
    body = post.get("body")
    files = body.get("files") if isinstance(body, dict) else None
    if not isinstance(files, list):
        return None
    for file_info in files:
        if not isinstance(file_info, dict):
            continue
        if file_info.get("media_path") != filename:
            continue
        stored_media_type = file_info.get("media_type")
        if _is_text_html(stored_media_type):
            return "text/html"
        if _is_text_html(guessed_media_type):
            return guessed_media_type
        return None
    return None


def _before_media_path(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,16}", suffix):
        suffix = ".bin"
    return f"__before{suffix}"


async def _write_upload(upload: UploadFile, dest_path: Path) -> int:
    total = 0
    with dest_path.open("wb") as out:
        while True:
            chunk = await upload.read(UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            out.write(chunk)
    return total


def _validate_slug(slug: str) -> str:
    if not STREAM_SLUG_RE.fullmatch(slug):
        raise HTTPException(status_code=400, detail="invalid stream slug")
    return slug


def _bounded_text(value: object, name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{name} must be a string")
    value = value.strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{name} is required")
    if len(value) > max_length:
        raise HTTPException(status_code=400, detail=f"{name} is too long")
    _validate_json_response_safe(value)
    return value


def _parse_body_field(body: str | None) -> dict:
    if body is None or body == "":
        return {}
    if len(body.encode("utf-8")) > MAX_BODY_JSON_BYTES:
        raise HTTPException(status_code=400, detail="body JSON is too large")
    try:
        parsed = json.loads(body, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid body JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="body JSON must be an object")
    _validate_json_response_safe(parsed)
    return parsed


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _validate_json_response_safe(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _validate_json_response_safe(key)
            _validate_json_response_safe(child)
    elif isinstance(value, list):
        for child in value:
            _validate_json_response_safe(child)
    elif isinstance(value, float) and not math.isfinite(value):
        raise HTTPException(status_code=400, detail="body JSON contains a non-finite number")
    elif isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise HTTPException(status_code=400, detail="body JSON contains invalid unicode") from exc


def _coerce_uploads(files: list[UploadFile] | None) -> list[UploadFile]:
    return list(files or [])


async def _rewind_uploads(uploads: list[UploadFile]) -> None:
    for upload in uploads:
        await upload.seek(0)


async def _save_post_files(post_id: str, uploads: list[UploadFile]) -> tuple[list[dict], int, bool]:
    if not uploads:
        return [], 0, False
    dest_dir = config.media_dir() / post_id
    dest_dir.mkdir(parents=True, exist_ok=False)
    stored = []
    total_bytes = 0
    try:
        for i, upload in enumerate(uploads, start=1):
            original_name = upload.filename or f"file_{i}"
            safe_name = f"{i:02d}_{_safe_upload_name(original_name, f'file_{i}')}"
            dest_path = dest_dir / safe_name
            size = await _write_upload(upload, dest_path)
            total_bytes += size
            stored.append(
                {
                    "media_path": safe_name,
                    "media_type": upload.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
                    "size": size,
                    "original_name": Path(original_name).name,
                }
            )
    except Exception:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise
    return stored, total_bytes, True


def _add_stream_slug_to_post(post: dict, slug: str) -> dict:
    post = dict(post)
    post["stream"] = slug
    return post


@app.post("/api/requests")
async def create_request(
    request: Request,
    title: str = Form(...),
    project: str | None = Form(None),
    kind: str = Form(...),
    context: str | None = Form(None),
    manifest: str | None = Form(None),
    before: UploadFile | None = File(None),
    files: list[UploadFile] = File(...),
):
    require_api_token(request)

    if kind not in db.KINDS:
        raise HTTPException(status_code=400, detail=f"invalid kind: {kind}. Must be one of {db.KINDS}")
    if not files:
        raise HTTPException(status_code=400, detail="at least one file is required")

    manifest_map = {}
    if manifest:
        try:
            manifest_map = json.loads(manifest)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"invalid manifest JSON: {exc}") from exc

    request_uploads = list(files)
    all_uploads = ([before] if before is not None else []) + request_uploads
    req_id = None
    variants = []
    for _ in range(5):
        req_id = db.new_request_id()
        dest_dir = config.media_dir() / req_id
        try:
            dest_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue

        before_media_path = None
        before_media_type = None
        variants = []
        try:
            if before is not None and before.filename:
                before_media_path = _before_media_path(before.filename)
                await _write_upload(before, dest_dir / before_media_path)
                before_media_type = _media_type_for(before.filename)

            for i, upload in enumerate(request_uploads, start=1):
                orig_name = upload.filename or f"variant_{i}"
                safe_name = f"{i:02d}_{_safe_upload_name(orig_name, f'variant_{i}')}"
                dest_path = dest_dir / safe_name
                data = await upload.read()
                dest_path.write_bytes(data)
                info = manifest_map.get(orig_name, {})
                variants.append(
                    {
                        "media_path": safe_name,
                        "media_type": _media_type_for(orig_name),
                        "caption": info.get("caption"),
                        "meta": info.get("meta"),
                    }
                )

            db.create_request(
                req_id,
                title,
                project,
                kind,
                context,
                variants,
                before_media_path=before_media_path,
                before_media_type=before_media_type,
            )
            break
        except ValueError as exc:
            shutil.rmtree(dest_dir, ignore_errors=True)
            detail = str(exc)
            status = 409 if "closed" in detail else 400
            raise HTTPException(status_code=status, detail=detail) from exc
        except sqlite3.IntegrityError:
            shutil.rmtree(dest_dir, ignore_errors=True)
            await _rewind_uploads(all_uploads)
            continue
        except Exception:
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise
    else:
        raise HTTPException(status_code=500, detail="could not allocate unique request id")

    server_cfg = config.load_config()
    url = f"{server_cfg['url']}/r/{req_id}?token={server_cfg['token']}"
    threading.Thread(
        target=notify.send_doorbell,
        args=(server_cfg, title, len(variants), url),
        daemon=True,
    ).start()

    return {"id": req_id, "url": f"{server_cfg['url']}/r/{req_id}", "variant_count": len(variants)}


@app.get("/api/requests")
def list_requests(request: Request, status: str | None = None, project: str | None = None):
    require_api_token(request)
    return db.list_requests(status=status, project=project)


@app.get("/api/requests/{req_id}")
def get_request(request: Request, req_id: str):
    require_api_token(request)
    r = db.get_request(req_id)
    if r is None:
        raise HTTPException(status_code=404, detail="request not found")
    return r


@app.post("/api/streams")
async def create_stream(request: Request):
    require_api_token(request)
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    slug = _validate_slug(_bounded_text(body.get("slug"), "slug", 128))
    kind = _bounded_text(body.get("kind"), "kind", 32)
    if kind not in STREAM_KINDS:
        raise HTTPException(status_code=400, detail=f"invalid stream kind: {kind}")
    title = _bounded_text(body.get("title"), "title", MAX_TITLE_LENGTH)
    try:
        return db.create_stream(slug, kind, title)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="stream already exists") from exc


@app.post("/api/streams/{slug}/close")
def close_stream(request: Request, slug: str):
    require_api_token(request)
    _validate_slug(slug)
    try:
        return db.close_stream(slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/streams/{slug}")
def get_stream(request: Request, slug: str):
    require_api_token(request)
    _validate_slug(slug)
    stream = db.get_stream_with_posts(slug)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")
    stream["posts"] = [_add_stream_slug_to_post(post, stream["slug"]) for post in stream["posts"]]
    return stream


@app.post("/api/streams/{slug}/posts")
async def create_stream_post(
    request: Request,
    slug: str,
    type: str = Form(...),
    title: str = Form(...),
    author: str = Form(...),
    body: str | None = Form(None),
    files: list[UploadFile] | None = File(None),
):
    require_api_token(request)
    _validate_slug(slug)
    post_type = _bounded_text(type, "type", 32)
    if post_type not in POST_TYPES:
        raise HTTPException(status_code=400, detail=f"invalid post type: {post_type}")
    title = _bounded_text(title, "title", MAX_TITLE_LENGTH)
    author = _bounded_text(author, "author", MAX_AUTHOR_LENGTH)
    body_obj = _parse_body_field(body)

    existing_stream = db.get_stream(slug)
    if existing_stream is not None and existing_stream["closed_at"] is not None:
        raise HTTPException(status_code=409, detail=f"stream is closed: {slug}")

    if post_type == "decision":
        request_id = body_obj.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise HTTPException(status_code=400, detail="decision posts require body.request_id")
        if db.get_request(request_id) is None:
            raise HTTPException(status_code=404, detail="request not found")

    uploads = _coerce_uploads(files)
    post = None
    total_bytes = 0
    for _ in range(5):
        post_id = db.new_post_id()
        media_dir_created = False
        try:
            stored_files, total_bytes, media_dir_created = await _save_post_files(post_id, uploads)
            post_body = body_obj
            if post_type == "report":
                post_body = {**body_obj, "files": stored_files}
            elif stored_files:
                post_body = {**body_obj, "files": stored_files}
            post = db.create_post_for_stream(
                slug,
                post_type,
                title,
                author,
                post_body,
                post_id=post_id,
            )
            break
        except FileExistsError:
            continue
        except ValueError as exc:
            if media_dir_created:
                shutil.rmtree(config.media_dir() / post_id, ignore_errors=True)
            detail = str(exc)
            status = 409 if "closed" in detail else 404
            raise HTTPException(status_code=status, detail=detail) from exc
        except sqlite3.IntegrityError:
            if media_dir_created:
                shutil.rmtree(config.media_dir() / post_id, ignore_errors=True)
            await _rewind_uploads(uploads)
            continue
        except Exception:
            if media_dir_created:
                shutil.rmtree(config.media_dir() / post_id, ignore_errors=True)
            raise
    if post is None:
        raise HTTPException(status_code=500, detail="could not allocate unique post id")

    response = {"post": _add_stream_slug_to_post(post, slug)}
    if total_bytes > POST_UPLOAD_SOFT_CAP_BYTES:
        response["warning"] = f"post upload exceeded {POST_UPLOAD_SOFT_CAP_BYTES} byte soft cap"
    return response


@app.get("/api/streams/{slug}/posts/{post_id}")
def get_stream_post(request: Request, slug: str, post_id: str):
    require_api_token(request)
    _validate_slug(slug)
    post = db.get_stream_post(slug, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="post not found")
    return _add_stream_slug_to_post(post, slug)


def _apply_verdict(req_id: str, body: dict) -> dict:
    r = db.get_request(req_id)
    if r is None:
        raise HTTPException(status_code=404, detail="request not found")

    selected = body.get("selected", [])
    ratings = body.get("ratings")
    comment = body.get("comment")

    if not isinstance(selected, list) or not all(isinstance(i, int) for i in selected):
        raise HTTPException(status_code=400, detail="selected must be a list of integers")

    valid_indices = db.variant_indices(req_id)
    bad = [i for i in selected if i not in valid_indices]
    if bad:
        raise HTTPException(status_code=400, detail=f"selected indices not found on this request: {bad}")

    try:
        return db.record_verdict(req_id, selected, ratings, comment)
    except ValueError as exc:
        detail = str(exc)
        status = 409 if "closed" in detail else 400
        raise HTTPException(status_code=status, detail=detail) from exc


@app.post("/api/requests/{req_id}/verdict")
async def post_verdict(request: Request, req_id: str):
    require_api_token(request)
    body = await request.json()
    return _apply_verdict(req_id, body)


# --- media serving ---


@app.get("/media/{req_id}/{filename}")
def get_media(request: Request, req_id: str, filename: str):
    if not web_token_ok(request):
        raise HTTPException(status_code=401, detail="missing or invalid token")
    if (
        not SAFE_SEGMENT_RE.fullmatch(req_id)
        or req_id in {".", ".."}
        or not _safe_media_filename(filename)
    ):
        raise HTTPException(status_code=404, detail="media not found")
    media_root = config.media_dir().resolve()
    media_dir = (media_root / req_id).resolve()
    path = (media_dir / filename).resolve()
    try:
        path.relative_to(media_dir)
        media_dir.relative_to(media_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="media not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="media not found")
    media_type, _ = mimetypes.guess_type(str(path))
    headers = {"X-Content-Type-Options": "nosniff"}
    report_html_type = _report_html_media_type(req_id, filename, media_type)
    browser_safe_media = bool(
        media_type
        and (
            media_type.startswith("video/")
            or (media_type.startswith("image/") and media_type != "image/svg+xml")
        )
    )
    if report_html_type is not None:
        headers["Content-Security-Policy"] = "sandbox allow-same-origin"
        return FileResponse(path, media_type=report_html_type, headers=headers)
    if browser_safe_media:
        return FileResponse(path, media_type=media_type, headers=headers)
    return FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
        headers=headers,
        filename=path.name,
        content_disposition_type="attachment",
    )


# --- web UI ---


def _media_url(owner_id: str, filename: str) -> str:
    return f"/media/{quote(owner_id, safe='')}/{quote(filename, safe='')}"


def _select_report_file(post: dict) -> dict | None:
    body = post.get("body")
    files = body.get("files") if isinstance(body, dict) else None
    if not isinstance(files, list):
        return None

    candidates = []
    for file_info in files:
        if not isinstance(file_info, dict):
            continue
        filename = file_info.get("media_path")
        if not isinstance(filename, str) or not _safe_media_filename(filename):
            continue
        media_type = file_info.get("media_type")
        if not isinstance(media_type, str):
            media_type = mimetypes.guess_type(filename)[0] or ""
        original_name = file_info.get("original_name")
        label = original_name if isinstance(original_name, str) and original_name else filename
        is_html = media_type == "text/html" or Path(filename).suffix.lower() in {".html", ".htm"}
        candidates.append(
            {
                "filename": filename,
                "label": label,
                "media_type": media_type,
                "url": _media_url(str(post.get("id", "")), filename),
                "is_html": is_html,
            }
        )

    if not candidates:
        return None
    return next((candidate for candidate in candidates if candidate["is_html"]), candidates[0])


def _decision_request_id(post: dict) -> str | None:
    body = post.get("body")
    request_id = body.get("request_id") if isinstance(body, dict) else None
    if not isinstance(request_id, str) or not request_id:
        return None
    return request_id


def _request_summaries_for_posts(posts: list[dict]) -> dict[str, dict]:
    request_ids = []
    seen = set()
    for post in posts:
        if post.get("type") != "decision":
            continue
        request_id = _decision_request_id(post)
        if request_id and request_id not in seen:
            seen.add(request_id)
            request_ids.append(request_id)
    if not request_ids:
        return {}

    placeholders = ", ".join("?" for _ in request_ids)
    conn = db.connect()
    with db._lock:
        rows = conn.execute(
            f"SELECT id, title, status FROM requests WHERE id IN ({placeholders})",
            request_ids,
        ).fetchall()
    return {row["id"]: dict(row) for row in rows}


def _decision_post_context(post: dict, request_summaries: dict[str, dict]) -> dict | None:
    request_id = _decision_request_id(post)
    if request_id is None:
        return None
    request_row = request_summaries.get(request_id)
    if request_row is None:
        return None
    status = "decided" if request_row.get("status") == "decided" else "pending"
    return {
        "request_id": request_id,
        "title": request_row.get("title") or request_id,
        "status": status,
        "href": f"/r/{quote(request_id, safe='')}",
    }


def _stream_post_context(post: dict, request_summaries: dict[str, dict]) -> dict:
    post_type = post.get("type")
    item = {
        "id": post.get("id"),
        "type": post_type,
        "title": post.get("title") or "Untitled post",
        "author": post.get("author") or "",
        "created_at": post.get("created_at"),
        "report": None,
        "decision": None,
    }
    if post_type == "report":
        item["report"] = _select_report_file(post)
    elif post_type == "decision":
        item["decision"] = _decision_post_context(post, request_summaries)
    return item


def _request_stream_closed(request_row: dict) -> bool:
    stream_id = request_row.get("stream_id")
    if not stream_id:
        return False
    conn = db.connect()
    with db._lock:
        row = conn.execute("SELECT closed_at FROM streams WHERE id = ?", (stream_id,)).fetchone()
    return bool(row and row["closed_at"] is not None)


def _before_media_context(request_row: dict) -> dict | None:
    media_path = request_row.get("before_media_path")
    if not isinstance(media_path, str) or not media_path or not _safe_media_filename(media_path):
        return None
    media_type = request_row.get("before_media_type")
    if media_type not in {"image", "video"}:
        media_type = _media_type_for(media_path)
    return {
        "url": _media_url(str(request_row["id"]), media_path),
        "media_type": media_type,
        "default_view": "toggle" if request_row.get("kind") == "before-after" else "side-by-side",
    }


def _list_stream_summaries() -> list[dict]:
    conn = db.connect()
    with db._lock:
        rows = conn.execute(
            """
            SELECT
                s.slug,
                s.kind,
                s.title,
                s.created_at,
                s.closed_at,
                COUNT(p.id) AS post_count,
                COALESCE(MAX(p.created_at), s.created_at) AS latest_activity
            FROM streams s
            LEFT JOIN posts p ON p.stream_id = s.id
            GROUP BY s.id
            ORDER BY latest_activity DESC, s.created_at DESC
            """
        ).fetchall()
    streams = []
    for row in rows:
        stream = dict(row)
        stream["post_count"] = int(stream["post_count"])
        stream["archived"] = stream["closed_at"] is not None
        streams.append(stream)
    return streams


@app.get("/", response_class=HTMLResponse)
def web_index(request: Request, q: str | None = None):
    if not web_token_ok(request):
        raise HTTPException(status_code=401, detail="missing or invalid token")
    open_requests = db.list_requests(status="open")
    decided = db.list_requests(status="decided", q=q)
    streams = _list_stream_summaries()
    response = templates.TemplateResponse(
        request,
        "index.html",
        {"open_requests": open_requests, "decided": decided, "q": q or "", "streams": streams},
    )
    _maybe_set_cookie(response, request)
    return response


@app.get("/s/{slug}", response_class=HTMLResponse)
def web_stream_detail(request: Request, slug: str):
    if not web_token_ok(request):
        raise HTTPException(status_code=401, detail="missing or invalid token")
    _validate_slug(slug)
    stream = db.get_stream_with_posts(slug)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")
    posts = sorted(stream["posts"], key=lambda post: post.get("created_at") or "", reverse=True)
    request_summaries = _request_summaries_for_posts(posts)
    response = templates.TemplateResponse(
        request,
        "stream.html",
        {"stream": stream, "posts": [_stream_post_context(post, request_summaries) for post in posts]},
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    _maybe_set_cookie(response, request)
    return response


@app.get("/r/{req_id}", response_class=HTMLResponse)
def web_request_detail(request: Request, req_id: str):
    if not web_token_ok(request):
        raise HTTPException(status_code=401, detail="missing or invalid token")
    r = db.get_request(req_id)
    if r is None:
        raise HTTPException(status_code=404, detail="request not found")

    context_html = md_lib.markdown(r["context_md"]) if r.get("context_md") else ""
    stream_read_only = _request_stream_closed(r)
    before_media = _before_media_context(r)

    response = templates.TemplateResponse(
        request,
        "request.html",
        {
            "r": r,
            "context_html": context_html,
            "stream_read_only": stream_read_only,
            "before_media": before_media,
        },
    )
    _maybe_set_cookie(response, request)
    return response


@app.post("/r/{req_id}/decide")
async def web_decide(request: Request, req_id: str):
    """Cookie-authenticated decide endpoint used by the web UI's JS (no bearer header available in-browser)."""
    if not web_token_ok(request):
        raise HTTPException(status_code=401, detail="missing or invalid token")
    body = await request.json()
    return _apply_verdict(req_id, body)
