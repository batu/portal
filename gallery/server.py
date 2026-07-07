"""Gallery FastAPI app: JSON API + server-rendered web UI + media serving."""

import json
import logging
import mimetypes
import threading
from datetime import datetime, timezone
from pathlib import Path

import markdown as md_lib
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from . import config, db, notify

log = logging.getLogger("gallery.server")

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".avi"}

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


@app.post("/api/requests")
async def create_request(
    request: Request,
    title: str = Form(...),
    project: str | None = Form(None),
    kind: str = Form(...),
    context: str | None = Form(None),
    manifest: str | None = Form(None),
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

    req_id = db.new_request_id()
    dest_dir = config.media_dir() / req_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    variants = []
    for i, upload in enumerate(files, start=1):
        orig_name = upload.filename or f"variant_{i}"
        safe_name = f"{i:02d}_{Path(orig_name).name}"
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

    db.create_request(req_id, title, project, kind, context, variants)

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

    return db.record_verdict(req_id, selected, ratings, comment)


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
    path = config.media_dir() / req_id / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="media not found")
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(path, media_type=media_type)


# --- web UI ---


@app.get("/", response_class=HTMLResponse)
def web_index(request: Request, q: str | None = None):
    if not web_token_ok(request):
        raise HTTPException(status_code=401, detail="missing or invalid token")
    open_requests = db.list_requests(status="open")
    decided = db.list_requests(status="decided", q=q)
    response = templates.TemplateResponse(
        request,
        "index.html",
        {"open_requests": open_requests, "decided": decided, "q": q or ""},
    )
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

    response = templates.TemplateResponse(
        request,
        "request.html",
        {"r": r, "context_html": context_html},
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
