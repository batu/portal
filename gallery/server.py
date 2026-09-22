"""Gallery FastAPI app: JSON API + server-rendered web UI + media serving."""

import asyncio
import hashlib
import hmac
import html as html_lib
import json
import logging
import math
import mimetypes
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit

import markdown as md_lib
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import agents, config, db, money, notify, remote_config

log = logging.getLogger("gallery.server")

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".avi"}
GAME_PREVIEW_EXTS = {".jpg", ".jpeg"}
HTML_EXTS = {".html", ".htm"}
# Interactive view HTML is uploaded producer code. An opaque sandbox keeps its
# scripts away from Portal cookies and same-origin authority; a request-scoped
# capability grants only verdict submission for that one view.
VIEW_HTML_CSP = "sandbox allow-scripts allow-forms"
VIEW_CAPABILITY_PARAM = "view_token"
VIEW_CAPABILITY_PURPOSE = b"portal-view-verdict-v1\0"
STREAM_KINDS = {"session", "pinned"}
POST_TYPES = {"report", "decision"}
POST_UPLOAD_SOFT_CAP_BYTES = 200 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024
MAX_TITLE_LENGTH = 300
MAX_AUTHOR_LENGTH = 200
MAX_MESSAGE_TEXT_LENGTH = 20_000
AGENT_CONVERSATION_STREAM_SLUG = "agent-conversations"
MAX_BODY_JSON_BYTES = 1_000_000
MAX_JOURNEY_STEPS = 100
MAX_STEP_MEDIA = 30
GAME_VERSION_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?$")
GAME_ARTIFACT_FIELD = "artifact_path"
GAME_VIDEO_FIELD = "video_path"
GAME_PREVIEW_FIELD = "preview_path"
GAME_WEB_FIELD = "web_preview_path"
# Text files whose absolute asset URLs are repointed at the build directory.
GAME_WEB_REWRITE_EXTS = {".html", ".js", ".css", ".json"}
GAME_WEB_DIR = "web"
GAME_WEB_ENTRY = "index.html"
MAX_GAME_WEB_FILES = 2000
MAX_GAME_WEB_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
GAME_WEB_EXTS = {
    ".html", ".htm", ".js", ".mjs", ".css", ".json", ".wasm", ".map", ".txt",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico", ".avif",
    ".mp3", ".ogg", ".wav", ".m4a", ".mp4", ".webm",
    ".woff", ".woff2", ".ttf", ".otf",
}
# The web bundle is untrusted third-party build output. It is framed with
# sandbox="allow-scripts" and no allow-same-origin (opaque origin: no Portal
# cookies, no parent DOM), and these headers keep a direct hit on the URL inert.
GAME_WEB_CSP = "sandbox allow-scripts"
STREAM_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?$")
SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
CLIENT_SUBMISSION_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")

# Request context is stored, agent-controlled Markdown that renders into an
# HTML `|safe` sink. Markdown preserves raw HTML, so its output is run through
# a strict allowlist sanitizer before it reaches the template. Only these
# formatting tags survive; everything else (script/style/svg/iframe/unknown
# tags), every non-allowlisted attribute (event handlers, style, class…), and
# any href/src whose scheme is not http(s)/mailto is dropped.
_CONTEXT_ALLOWED_TAGS = {
    "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "em", "b", "i", "u", "s", "del", "ins", "sup", "sub",
    "code", "pre", "blockquote", "ul", "ol", "li", "dl", "dt", "dd",
    "a", "img",
}
_CONTEXT_ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
}
# Void (self-closing) tags that must not emit a closing tag.
_CONTEXT_VOID_TAGS = {"br", "hr", "img"}
# Elements whose text content is discarded, not just their surrounding tags.
_CONTEXT_DROP_CONTENT_TAGS = {"script", "style"}
_CONTEXT_URL_ATTRS = {"href", "src"}
_CONTEXT_SAFE_URL_SCHEMES = {"http", "https", "mailto"}
_CONTEXT_SCHEME_RE = re.compile(r"^([a-z][a-z0-9+.-]*):")


def _context_url_is_safe(value: str) -> bool:
    """Reject javascript:/data:/vbscript: (and any non-allowlisted) URL schemes.

    Browsers strip whitespace and control characters while resolving a URL's
    scheme, so those are removed before the check to defeat obfuscation such as
    ``java\tscript:`` or ``java&#0;script:``.
    """
    cleaned = re.sub(r"[\x00-\x20]+", "", value).lower()
    if not cleaned or cleaned.startswith(("#", "/", "?")):
        return True
    match = _CONTEXT_SCHEME_RE.match(cleaned)
    if match is None:
        return True  # no scheme -> relative path, safe
    return match.group(1) in _CONTEXT_SAFE_URL_SCHEMES


class _ContextSanitizer(HTMLParser):
    """Allowlist HTML sanitizer for rendered request context."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._open_tags: list[str] = []
        self._open_tag_counts: dict[str, int] = {}
        self._skip_depth = 0
        self._finished = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _CONTEXT_DROP_CONTENT_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth or tag not in _CONTEXT_ALLOWED_TAGS:
            return
        self._parts.append(self._render_open(tag, attrs))
        if tag not in _CONTEXT_VOID_TAGS:
            self._open_tags.append(tag)
            self._open_tag_counts[tag] = self._open_tag_counts.get(tag, 0) + 1

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        if tag in _CONTEXT_DROP_CONTENT_TAGS or self._skip_depth:
            return
        if tag not in _CONTEXT_ALLOWED_TAGS:
            return
        self._parts.append(self._render_open(tag, attrs))
        if tag not in _CONTEXT_VOID_TAGS:
            self._parts.append(f"</{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in _CONTEXT_DROP_CONTENT_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth or tag not in _CONTEXT_ALLOWED_TAGS:
            return
        if tag in _CONTEXT_VOID_TAGS or self._open_tag_counts.get(tag, 0) == 0:
            return
        # Close any elements nested inside the requested end tag first. This
        # turns malformed input such as ``<p><a>text</p>`` into a balanced
        # fragment rather than allowing the browser's active-formatting repair
        # rules to extend the attacker-controlled link past the context block.
        while self._open_tags:
            open_tag = self._close_last_open_tag()
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._parts.append(html_lib.escape(data, quote=False))

    def _render_open(self, tag: str, attrs: list) -> str:
        allowed = _CONTEXT_ALLOWED_ATTRS.get(tag, frozenset())
        rendered = []
        for name, value in attrs:
            name = name.lower()
            if name not in allowed:
                continue  # drops on*, style, class, id, …
            value = value or ""
            if name in _CONTEXT_URL_ATTRS and not _context_url_is_safe(value):
                continue
            rendered.append(f' {name}="{html_lib.escape(value, quote=True)}"')
        return f"<{tag}{''.join(rendered)}>"

    def _close_last_open_tag(self) -> str:
        tag = self._open_tags.pop()
        remaining = self._open_tag_counts[tag] - 1
        if remaining:
            self._open_tag_counts[tag] = remaining
        else:
            del self._open_tag_counts[tag]
        self._parts.append(f"</{tag}>")
        return tag

    def get_html(self) -> str:
        if not self._finished:
            while self._open_tags:
                self._close_last_open_tag()
            self._finished = True
        return "".join(self._parts)


def _sanitize_context_html(html_text: str) -> str:
    parser = _ContextSanitizer()
    parser.feed(html_text)
    parser.close()
    return parser.get_html()


app = FastAPI(title="Gallery")

_here = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(_here / "static")), name="static")
templates = Jinja2Templates(directory=str(_here / "templates"))

_static_version_cache: dict[str, tuple[float, str]] = {}


def static_url(name: str) -> str:
    """Content-hashed static asset URL — replaces hand-bumped ?v=N versions.

    Hash is keyed on file mtime, so an edited file busts browser caches on the
    next page render with no code change. Missing files fall back to a bare
    URL rather than erroring a page render."""
    path = _here / "static" / name
    try:
        mtime = path.stat().st_mtime
        cached = _static_version_cache.get(name)
        if cached is None or cached[0] != mtime:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:8]
            _static_version_cache[name] = (mtime, digest)
        return f"/static/{name}?v={_static_version_cache[name][1]}"
    except OSError:
        return f"/static/{name}"


templates.env.globals["static_url"] = static_url


def ftd_editor_enabled() -> bool:
    try:
        value = config.load_config().get("ftd_editor")
    except (FileNotFoundError, ValueError):
        return False
    return isinstance(value, dict) and bool(value.get("backend_url")) and bool(value.get("ui_root"))


templates.env.globals["ftd_editor_enabled"] = ftd_editor_enabled

COOKIE_NAME = "gallery_token"
# Remote-config form fields are namespaced so a stray form field can never be
# mistaken for a Remote Config parameter name.
_RC_FIELD_PREFIX = "rc__"
_ftd_editor_process: subprocess.Popen | None = None


def _ftd_editor_command() -> tuple[str, ...] | None:
    value = config.load_config().get("ftd_editor")
    if not isinstance(value, dict):
        return None
    command = value.get("command")
    if not isinstance(command, list) or not command:
        return None
    if not all(isinstance(part, str) and part for part in command):
        raise RuntimeError("ftd_editor.command must be a non-empty string list")
    executable = Path(command[0])
    if not executable.is_absolute() or not executable.is_file():
        raise RuntimeError("ftd_editor.command executable must be an absolute file")
    return tuple(command)


@app.on_event("startup")
def start_ftd_editor() -> None:
    global _ftd_editor_process
    command = _ftd_editor_command()
    if command is None:
        return
    _ftd_editor_process = subprocess.Popen(command, start_new_session=True)


@app.on_event("shutdown")
def stop_ftd_editor() -> None:
    global _ftd_editor_process
    process = _ftd_editor_process
    _ftd_editor_process = None
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


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


def _filesize(value: object) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


templates.env.filters["filesize"] = _filesize


# --- auth helpers ---


def _server_token() -> str:
    return config.load_config()["token"]


def require_api_token(request: Request) -> dict:
    server_cfg = config.load_config()
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    if not token or token != server_cfg["token"]:
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")
    return server_cfg


def web_token_ok(request: Request) -> bool:
    # Sandboxed producer documents have an opaque origin. Even if a browser
    # attaches Portal's cookie to an explicit credentials=include request, that
    # uploaded script must not inherit the human operator's authority.
    if request.headers.get("origin") == "null":
        return False
    expected = _server_token()
    qs_token = request.query_params.get("token")
    if qs_token and qs_token == expected:
        return True
    cookie_token = request.cookies.get(COOKIE_NAME)
    return bool(cookie_token and cookie_token == expected)


def web_view_ok(request: Request) -> bool:
    """Artifact browsing only. Never use this guard on writes or admin routes."""
    return config.load_config().get("public_viewing") is True or web_token_ok(request)


def _view_entry_url(request: Request, req_id: str, filename: str) -> str:
    # Only operators receive the existing request-scoped write capability.
    # Anonymous views use ordinary public media, without a verdict bridge.
    if web_token_ok(request):
        return _view_media_url(req_id, filename)
    return _media_url(req_id, filename)


templates.env.globals["operator_authenticated"] = web_token_ok


def _view_capability(req_id: str) -> str:
    return hmac.new(
        _server_token().encode("utf-8"),
        VIEW_CAPABILITY_PURPOSE + req_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _view_capability_ok(req_id: str, capability: str | None) -> bool:
    return bool(
        capability
        and SAFE_SEGMENT_RE.fullmatch(req_id)
        and re.fullmatch(r"[0-9a-f]{64}", capability)
        and secrets.compare_digest(capability, _view_capability(req_id))
    )


def _view_verdict_capability_ok(req_id: str, capability: str | None) -> bool:
    if not _view_capability_ok(req_id, capability):
        return False
    request_row = db.get_request(req_id)
    return bool(request_row and request_row.get("kind") == "view")


def _view_cors_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "null",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "content-type",
        "Cache-Control": "no-store",
        "Vary": "Origin",
    }


def _maybe_set_cookie(response, request: Request) -> None:
    # Operator and anonymous representations must not share a cached response.
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    qs_token = request.query_params.get("token")
    if qs_token and qs_token == _server_token():
        response.set_cookie(COOKIE_NAME, qs_token, httponly=True, samesite="lax", max_age=3600 * 24 * 365)


def _safe_next_path(value: str | None) -> str:
    if isinstance(value, str) and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


def _login_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse(url=f"/login?next={quote(request.url.path, safe='/')}", status_code=303)


# --- authenticated FTD editor gateway ---


def _ftd_editor_config() -> tuple[str, Path]:
    value = config.load_config().get("ftd_editor")
    if not isinstance(value, dict):
        raise HTTPException(status_code=503, detail="FTD editor is not configured")
    backend_url = value.get("backend_url")
    ui_root = value.get("ui_root")
    if not isinstance(backend_url, str) or not isinstance(ui_root, str):
        raise HTTPException(status_code=503, detail="FTD editor configuration is incomplete")
    parsed = urlsplit(backend_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(status_code=503, detail="FTD editor backend must be loopback HTTP")
    root = Path(ui_root).expanduser().resolve()
    if not root.is_absolute():
        raise HTTPException(status_code=503, detail="FTD editor UI root must be absolute")
    return backend_url.rstrip("/"), root


def _ftd_static_file(ui_root: Path, relative: str) -> Path:
    candidate = (ui_root / relative).resolve(strict=False)
    if candidate != ui_root and ui_root not in candidate.parents:
        raise HTTPException(status_code=404, detail="editor asset not found")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="editor asset not found")
    return candidate


def _proxy_ftd_editor(
    backend_url: str,
    method: str,
    path: str,
    query: str,
    body: bytes,
    headers: dict[str, str],
) -> tuple[int, dict[str, str], bytes]:
    target = f"{backend_url}/{path.lstrip('/')}"
    if query:
        target = f"{target}?{query}"
    parsed = urlsplit(backend_url)
    forwarded = {
        "Host": parsed.netloc,
        "Origin": backend_url,
        **headers,
    }
    request = urllib.request.Request(
        target,
        data=body if method != "GET" else None,
        headers=forwarded,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=330) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers.items()), error.read()
    except urllib.error.URLError as error:
        raise HTTPException(status_code=503, detail="FTD editor backend is unavailable") from error


def _open_ftd_editor_stream(
    backend_url: str,
    method: str,
    path: str,
    query: str,
    body: bytes,
    headers: dict[str, str],
):
    target = f"{backend_url}/{path.lstrip('/')}"
    if query:
        target = f"{target}?{query}"
    parsed = urlsplit(backend_url)
    request = urllib.request.Request(
        target,
        data=body if method != "GET" else None,
        headers={"Host": parsed.netloc, "Origin": backend_url, **headers},
        method=method,
    )
    try:
        response = urllib.request.urlopen(request, timeout=330)
    except urllib.error.HTTPError as error:
        response = error
    except urllib.error.URLError as error:
        raise HTTPException(status_code=503, detail="FTD editor backend is unavailable") from error
    return response, dict(response.headers.items())


def _iter_ftd_editor_stream(response):
    try:
        yield from response
    finally:
        response.close()


def _is_ftd_editor_sse_path(editor_path: str) -> bool:
    return editor_path.startswith("api/sessions/") and editor_path.endswith("/generate")


async def _stream_ftd_editor_response(
    request: Request,
    backend_url: str,
    editor_path: str,
    forwarded: dict[str, str],
) -> StreamingResponse:
    upstream, response_headers = await run_in_threadpool(
        _open_ftd_editor_stream,
        backend_url,
        request.method,
        editor_path,
        request.url.query,
        await request.body(),
        forwarded,
    )
    return StreamingResponse(
        _iter_ftd_editor_stream(upstream),
        status_code=upstream.status,
        media_type=response_headers.get("Content-Type"),
        headers={
            "Cache-Control": response_headers.get("Cache-Control", "no-cache"),
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/tools/ftd-editor")
def ftd_editor_slash(request: Request):
    if not web_token_ok(request):
        return _login_redirect(request)
    return RedirectResponse(url="/tools/ftd-editor/", status_code=307)


@app.get("/tools/ftd-editor/")
def ftd_editor_index(request: Request):
    if not web_token_ok(request):
        return _login_redirect(request)
    _, ui_root = _ftd_editor_config()
    response = FileResponse(_ftd_static_file(ui_root, "index.html"))
    # The index references hashed asset filenames; if a browser caches it, the
    # whole old app survives redeploys (observed twice on 2026-07-29).
    response.headers["Cache-Control"] = "no-cache"
    _maybe_set_cookie(response, request)
    # The editor UI issues calls to /api/* which require the referer header to
    # match /tools/ftd-editor/. _maybe_set_cookie sets no-referrer; override here.
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.get("/tools/ftd-editor/assets/{asset_path:path}")
def ftd_editor_asset(request: Request, asset_path: str):
    if not web_token_ok(request):
        return _login_redirect(request)
    _, ui_root = _ftd_editor_config()
    return FileResponse(_ftd_static_file(ui_root, f"assets/{asset_path}"))


@app.api_route(
    "/tools/ftd-editor/{editor_path:path}",
    methods=["GET", "POST", "PUT"],
)
async def ftd_editor_proxy(request: Request, editor_path: str):
    if not web_token_ok(request):
        return _login_redirect(request)
    if not (editor_path == "bootstrap" or editor_path.startswith("api/")):
        raise HTTPException(status_code=404, detail="editor route not found")
    backend_url, _ = _ftd_editor_config()
    forwarded = {}
    for name in ("content-type", "x-ftd-launch-credential"):
        value = request.headers.get(name)
        if value:
            forwarded[name] = value
    if _is_ftd_editor_sse_path(editor_path):
        return await _stream_ftd_editor_response(request, backend_url, editor_path, forwarded)
    status, response_headers, payload = await run_in_threadpool(
        _proxy_ftd_editor,
        backend_url,
        request.method,
        editor_path,
        request.url.query,
        await request.body(),
        forwarded,
    )
    safe_headers = {
        name: value
        for name, value in response_headers.items()
        if name.lower() in {
            "content-disposition",
            "x-content-type-options",
            "x-ftd-session-id",
            "x-ftd-session-revision",
            "x-ftd-image-source",
            "x-ftd-image-sha256",
        }
    }
    return Response(
        payload,
        status_code=status,
        media_type=response_headers.get("Content-Type"),
        headers=safe_headers,
    )


@app.get("/login", response_class=HTMLResponse)
def web_login(request: Request, next: str | None = None):
    if web_token_ok(request):
        return RedirectResponse(url=_safe_next_path(next), status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None, "next_path": _safe_next_path(next)})


@app.post("/login")
async def web_login_submit(request: Request, password: str = Form(""), next: str = Form("/")):
    # Humans may use the short config `passphrase`; the machine token also works.
    # The cookie always carries the token, so web_token_ok stays single-source.
    passphrase = config.load_config().get("passphrase") or ""
    ok = secrets.compare_digest(password, _server_token()) or (
        bool(passphrase) and secrets.compare_digest(password, passphrase)
    )
    if ok:
        response = RedirectResponse(url=_safe_next_path(next), status_code=303)
        response.set_cookie(COOKIE_NAME, _server_token(), httponly=True, samesite="lax", max_age=3600 * 24 * 365)
        return response
    await asyncio.sleep(0.3)  # blunt brute-force damper; the passphrase is short
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Wrong passphrase.", "next_path": _safe_next_path(next)},
        status_code=401,
    )


# --- money (authenticated) ---


@app.get("/money", response_class=HTMLResponse)
def web_money(request: Request, start: str | None = None, end: str | None = None, game: str = "all"):
    if not web_token_ok(request):
        return _login_redirect(request)
    filter_error = None
    try:
        start, end, game = money.filters(start, end, game)
    except ValueError as exc:
        filter_error = str(exc)
    reports = money.load_reports(start, end) if not filter_error else []
    response = templates.TemplateResponse(request, "money.html", {
        "start": start, "end": end, "game": game, "games": money.GAMES,
        "reports": reports, "money": money.summarize(reports, game), "filter_error": filter_error,
    }, status_code=400 if filter_error else 200)
    response.headers["Cache-Control"] = "no-store"
    _maybe_set_cookie(response, request)
    return response


# --- health (unauthenticated) ---


@app.get("/api/health")
def health():
    return {"status": "ok", "open_count": db.open_count()}


async def _write_game_upload(upload: UploadFile, destination: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = await _stream_upload(
        upload,
        destination,
        mode="xb",
        size_limit=POST_UPLOAD_SOFT_CAP_BYTES,
        digest=digest,
    )
    return size, digest.hexdigest()


def _extract_game_web_bundle(zip_path: Path, release_dir: Path) -> str:
    """Extract an untrusted Vite dist/ zip into <release_dir>/web/.

    Returns the entry file path relative to the release dir. Every rejection is
    a 400 so the publisher learns which rule the bundle broke.
    """
    dest = (release_dir / GAME_WEB_DIR).resolve()
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="web bundle must be a zip file") from exc
    with archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if not members:
            raise HTTPException(status_code=400, detail="web bundle is empty")
        if len(members) > MAX_GAME_WEB_FILES:
            raise HTTPException(status_code=400, detail=f"web bundle exceeds {MAX_GAME_WEB_FILES} files")
        # Read sizes from the central directory before extracting: a zip bomb
        # never gets written to disk.
        if sum(info.file_size for info in members) > MAX_GAME_WEB_UNCOMPRESSED_BYTES:
            cap_mb = MAX_GAME_WEB_UNCOMPRESSED_BYTES // (1024 * 1024)
            raise HTTPException(status_code=400, detail=f"web bundle uncompressed size exceeds {cap_mb} MB")
        targets = []
        for info in members:
            name = info.filename
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise HTTPException(status_code=400, detail=f"web bundle contains a symlink: {name}")
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts or (len(name) > 1 and name[1] == ":"):
                raise HTTPException(status_code=400, detail=f"web bundle contains an unsafe path: {name}")
            if PurePosixPath(name).suffix.lower() not in GAME_WEB_EXTS:
                raise HTTPException(status_code=400, detail=f"web bundle contains an unsupported file: {name}")
            target = (dest / name).resolve()
            try:
                target.relative_to(dest)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"web bundle escapes its release directory: {name}") from exc
            targets.append((info, target))

        names = [info.filename for info in members]
        prefix = ""
        if GAME_WEB_ENTRY not in names:
            roots = {PurePosixPath(name).parts[0] for name in names if len(PurePosixPath(name).parts) > 1}
            if len(roots) == 1 and f"{next(iter(roots))}/{GAME_WEB_ENTRY}" in names:
                prefix = next(iter(roots))
            else:
                raise HTTPException(status_code=400, detail="web bundle must contain index.html at its root")

        for info, target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "xb") as handle:
                shutil.copyfileobj(source, handle, UPLOAD_CHUNK_SIZE)
    entry = f"{prefix}/{GAME_WEB_ENTRY}" if prefix else GAME_WEB_ENTRY
    return f"{GAME_WEB_DIR}/{entry}"


def _rewrite_web_bundle_absolute_paths(web_root: Path, url_prefix: str) -> int:
    """Repoint root-absolute asset URLs at the build's own directory.

    A game's web build is authored to run at the root of its own origin (in a
    Capacitor shell it is), so it references `/assets/...`, `/fonts/...` and
    friends absolutely. Served from `/games/<slug>/builds/<version>/play/`, every
    one of those requests goes to the SITE root instead and 404s — and because
    the preview iframe is sandboxed without `allow-same-origin`, the failures
    surface as opaque CORS errors. The page then renders as a blank background.

    Rewriting here (rather than asking each game to build with a relative base)
    keeps the fix in one place and costs the games nothing. Only leading-slash
    references to directories that actually exist in this bundle are touched, and
    only when preceded by a quote, `(` or `=`, so absolute URLs belonging to
    other origins are left alone.
    """
    directories = sorted(
        entry.name for entry in web_root.iterdir() if entry.is_dir() and entry.name
    )
    if not directories:
        return 0
    pattern = re.compile(
        r"""(?P<lead>["'(`=])/(?P<dir>""" + "|".join(re.escape(name) for name in directories) + r""")/"""
    )
    rewritten = 0
    for path in web_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in GAME_WEB_REWRITE_EXTS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        updated = pattern.sub(
            lambda match: f"{match.group('lead')}{url_prefix}/{match.group('dir')}/", text
        )
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            rewritten += 1
    return rewritten


def _validate_game_release_ref(slug: str, version: str) -> None:
    if not STREAM_SLUG_RE.fullmatch(slug):
        raise HTTPException(status_code=400, detail="invalid game slug")
    if not GAME_VERSION_RE.fullmatch(version):
        raise HTTPException(status_code=400, detail="invalid build version")


@app.post("/api/games/{slug}/builds")
async def publish_game_build(
    request: Request,
    slug: str,
    title: str = Form(...),
    version: str = Form(...),
    changelog: str = Form(...),
    description: str = Form(""),
    artifact: UploadFile = File(...),
    video: UploadFile = File(...),
    poster: UploadFile = File(...),
    web: UploadFile | None = File(None),
):
    require_api_token(request)
    _validate_game_release_ref(slug, version)
    if not title.strip() or len(title) > MAX_TITLE_LENGTH:
        raise HTTPException(status_code=400, detail="game title is required")
    if not changelog.strip():
        raise HTTPException(status_code=400, detail="changelog is required")
    if db.get_game_build(slug, version) is not None:
        raise HTTPException(status_code=409, detail="build version already exists")
    artifact_name = _safe_upload_name(artifact.filename, "build.zip")
    video_name = _safe_upload_name(video.filename, "build.mp4")
    poster_name = _safe_upload_name(poster.filename, "preview.jpg")
    if Path(video_name).suffix.lower() not in VIDEO_EXTS:
        raise HTTPException(status_code=400, detail="video must be a supported video file")
    if Path(poster_name).suffix.lower() not in GAME_PREVIEW_EXTS:
        raise HTTPException(status_code=400, detail="poster must be a JPEG image")
    release_dir = config.games_dir() / slug / version
    try:
        release_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="build storage already exists") from exc
    try:
        artifact_size, artifact_sha256 = await _write_game_upload(artifact, release_dir / artifact_name)
        await _write_game_upload(video, release_dir / video_name)
        await _write_game_upload(poster, release_dir / poster_name)
        web_preview_path = ""
        if web is not None and web.filename:
            bundle_zip = release_dir / "_web.zip"
            await _write_game_upload(web, bundle_zip)
            web_preview_path = await run_in_threadpool(_extract_game_web_bundle, bundle_zip, release_dir)
            bundle_zip.unlink()
            play_prefix = f"/games/{slug}/builds/{quote(version, safe='')}/play"
            await run_in_threadpool(
                _rewrite_web_bundle_absolute_paths, release_dir / GAME_WEB_DIR, play_prefix
            )
        build = db.create_game_build(
            slug,
            title=title.strip(),
            description=description.strip(),
            version=version,
            changelog_md=changelog.strip(),
            artifact_path=artifact_name,
            artifact_size=artifact_size,
            artifact_sha256=artifact_sha256,
            video_path=video_name,
            preview_path=poster_name,
            web_preview_path=web_preview_path,
        )
    except Exception:
        shutil.rmtree(release_dir, ignore_errors=True)
        raise
    encoded_version = quote(version, safe="")
    return {
        **build,
        "game_url": f"/games/{slug}",
        "download_url": f"/games/{slug}/builds/{encoded_version}/public-download",
        "preview_url": f"/games/{slug}/builds/{encoded_version}/play/" if web_preview_path else None,
    }


@app.post("/api/games/{slug}/builds/{version}/changelog")
async def update_game_build_changelog(request: Request, slug: str, version: str):
    require_api_token(request)
    _validate_game_release_ref(slug, version)
    body = await _json_object_body(request)
    changelog = _bounded_text(body.get("changelog"), "changelog", MAX_MESSAGE_TEXT_LENGTH)
    build = db.update_game_build_changelog(slug, version, changelog)
    if build is None:
        raise HTTPException(status_code=404, detail="game build not found")
    return build


@app.delete("/api/games/{slug}/builds/{version}")
def remove_game_build(request: Request, slug: str, version: str):
    require_api_token(request)
    _validate_game_release_ref(slug, version)
    if db.get_game_build(slug, version) is None:
        raise HTTPException(status_code=404, detail="game build not found")
    release_dir = config.games_dir() / slug / version
    trash_dir = config.game_trash_dir() / slug / f"{version}-{secrets.token_hex(4)}"
    trash_dir.parent.mkdir(parents=True, exist_ok=True)
    if release_dir.exists():
        shutil.move(str(release_dir), str(trash_dir))
    try:
        removed = db.delete_game_build(slug, version)
    except Exception:
        if trash_dir.exists():
            release_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(trash_dir), str(release_dir))
        raise
    return {"removed": removed, "recoverable_path": str(trash_dir.relative_to(config.data_dir()))}


def _transcode_gifs_to_loop_mp4(dest_dir: Path, media_paths: list[str]) -> None:
    """Best-effort GIF -> muted looping MP4 siblings (<name>.loop.mp4), ~10x
    smaller than the GIF. Runs in a background thread after the request is
    created; pages fall back to the GIF until the sibling exists."""
    for name in media_paths:
        if not name.lower().endswith(".gif"):
            continue
        src = dest_dir / name
        out = dest_dir / f"{name}.loop.mp4"
        if not src.is_file() or out.exists():
            continue
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                    "-movflags", "+faststart", "-pix_fmt", "yuv420p",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-an", str(out),
                ],
                check=True,
                timeout=120,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:  # noqa: BLE001 - transcode is an optimization, never a failure
            log.warning("gif->mp4 transcode failed for %s: %s", name, exc)
            out.unlink(missing_ok=True)


def _augment_variant_loops(r: dict) -> None:
    """Annotate image/gif variants whose loop MP4 sibling exists, so templates
    can render a <video> loop instead of the heavy GIF."""
    media_root = config.media_dir() / r["id"]
    for v in r.get("variants", []):
        if v.get("media_type") == "image" and str(v.get("media_path", "")).lower().endswith(".gif"):
            if (media_root / f"{v['media_path']}.loop.mp4").is_file():
                v["loop_mp4"] = f"{v['media_path']}.loop.mp4"


# --- JSON API ---


def _media_type_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in HTML_EXTS:
        return "html"
    return "video" if ext in VIDEO_EXTS else "image"


def _safe_upload_name(filename: str | None, fallback: str) -> str:
    name = Path(filename or fallback).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return (name or fallback)[:120]


def _prefixed_media_name(
    index: int, filename: str | None, fallback: str, used: set[str] | None = None
) -> str:
    """Stored variant filename for the 1-based `index`th upload.

    Filenames that already carry a two-digit `NN_` ordinal — e.g. producer HTML
    with baked media paths like `--video-src=02_v.mp4` — are stored verbatim so
    those baked references resolve; re-prefixing (`01_02_v.mp4`) would 404 them.
    All other names get the 1-based ordinal exactly once.

    Keeping a name verbatim drops the uniqueness the positional prefix used to
    guarantee, so `used` (names already stored in this request) disambiguates a
    collision: the first occurrence keeps its baked name; a later clashing upload
    gets a numeric suffix instead of silently overwriting it on disk.
    """
    safe = _safe_upload_name(filename, fallback)
    if re.match(r"\d{2}_", safe):
        name = safe
    else:
        name = f"{index:02d}_{safe}"
    if used is not None:
        stem, suffix = Path(name).stem, Path(name).suffix
        counter = 2
        while name in used:
            name = f"{stem}_{counter}{suffix}"
            counter += 1
        used.add(name)
    return name


def _safe_media_filename(filename: str) -> bool:
    if not filename or filename in {".", ".."}:
        return False
    if "/" in filename or "\\" in filename:
        return False
    return not any(ord(ch) < 32 for ch in filename)


def _is_text_html(media_type: str | None) -> bool:
    return bool(media_type and media_type.split(";", 1)[0].strip().lower() == "text/html")


# Producer HTML (views, report pages) owns the whole tab and bypasses Portal's
# templates, so it carries no orientation. Inject a slim fixed native context
# header (home + stream + step + ask + status) above the producer page so every
# producer page says where it is and what the human is being asked to do
# (Batu, 2026-07-09). The header is self-contained inline styles — the sandboxed
# producer page does not load Portal's style.css.
_BODY_OPEN_RE = re.compile(rb"<body[^>]*>", re.IGNORECASE)
_HEAD_OPEN_RE = re.compile(rb"<head[^>]*>", re.IGNORECASE)
_HTML_OPEN_RE = re.compile(rb"<html[^>]*>", re.IGNORECASE)
_DOCTYPE_RE = re.compile(rb"\A\s*<!doctype[^>]*>", re.IGNORECASE)

# Deterministic status → inline chip style. Not user-controlled (status is drawn
# from the lifecycle vocabulary), so it is injected as-is by the template.
# One pill spec — consistent translucent fill (~.16 alpha) + bright legible text,
# varying only hue per status. OPEN uses informational blue rather than the amber
# brand accent (#f4c542, also the Portal link + selection outline) so an "open"
# state never reads as a warning or competes with the brand/selection cue.
_STATUS_CHIP_DEFAULT_STYLE = "background:rgba(160,165,180,.14);color:#b6b9c2"
_STATUS_CHIP_STYLES = {
    "open": "background:rgba(96,150,230,.16);color:#8fb8f0",
    "decided": "background:rgba(74,200,140,.16);color:#7ce0a3",
    "closed": _STATUS_CHIP_DEFAULT_STYLE,
    "superseded": _STATUS_CHIP_DEFAULT_STYLE,
}


def _render_safe_metadata(value: object) -> str | None:
    """Coerce header metadata read from stored JSON (report body_json) at render
    time: request rows are bounded at write time, but report bodies are arbitrary
    JSON — drop non-strings (never render a Python repr) and bound the length."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value[:MAX_TITLE_LENGTH]


def _context_header_bytes(*, stream: dict | None, step, ask, status) -> bytes:
    """Render the self-contained context-header fragment for a producer page."""
    stream_ctx = None
    if stream is not None:
        stream_ctx = {"slug": stream["slug"], "label": stream.get("title") or stream["slug"]}
    html = templates.get_template("context_header.html").render(
        stream=stream_ctx,
        step=step or None,
        ask=ask or None,
        status=status or None,
        status_style=_STATUS_CHIP_STYLES.get(status or "", _STATUS_CHIP_DEFAULT_STYLE),
    )
    return html.encode("utf-8")


def _view_fetch_bridge_bytes(req_id: str, capability: str) -> bytes:
    """Grant legacy producer fetches only this request's verdict capability."""
    script = f"""<script>
(function () {{
  const requestId = {json.dumps(req_id)};
  const viewToken = {json.dumps(capability)};
  const nativeFetch = window.fetch;
  if (typeof nativeFetch !== "function") return;
  window.fetch = function (input, options) {{
    let url;
    try {{
      const rawUrl = (typeof input === "string" || input instanceof URL) ? input : input.url;
      url = new URL(rawUrl, window.location.href);
    }} catch (_) {{
      return nativeFetch.call(this, input, options);
    }}
    if (url.pathname !== "/r/" + encodeURIComponent(requestId) + "/decide") {{
      return nativeFetch.call(this, input, options);
    }}
    url.searchParams.delete("token");
    url.searchParams.set({json.dumps(VIEW_CAPABILITY_PARAM)}, viewToken);
    const safeOptions = Object.assign({{}}, options || {{}}, {{ credentials: "omit" }});
    if (typeof input === "string" || input instanceof URL) {{
      return nativeFetch.call(this, url.toString(), safeOptions);
    }}
    return nativeFetch.call(this, new Request(url.toString(), input), safeOptions);
  }};
}})();
</script>"""
    return script.encode("utf-8")


def _html_with_context_header(
    path,
    media_type: str,
    headers: dict,
    header_bytes: bytes,
    *,
    bootstrap_bytes: bytes = b"",
):
    raw = path.read_bytes()
    if bootstrap_bytes:
        bootstrap_parent = (
            _HEAD_OPEN_RE.search(raw)
            or _HTML_OPEN_RE.search(raw)
            or _DOCTYPE_RE.match(raw)
        )
        insertion = bootstrap_parent.end() if bootstrap_parent is not None else 0
        raw = raw[:insertion] + bootstrap_bytes + raw[insertion:]
    # No <body> tag: still insert AFTER any leading doctype — content before the
    # doctype would demote the whole page to quirks mode.
    match = _BODY_OPEN_RE.search(raw) or _DOCTYPE_RE.match(raw)
    if match is not None:
        raw = raw[: match.end()] + header_bytes + raw[match.end() :]
    else:
        raw = header_bytes + raw
    return HTMLResponse(content=raw, media_type=media_type, headers=headers)


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


def _view_entry_media_path(request_row: dict) -> str | None:
    """First HTML variant of a view-kind request; None for other kinds."""
    if request_row.get("kind") != "view":
        return None
    for variant in request_row.get("variants", []):
        media_path = variant.get("media_path")
        if (
            isinstance(media_path, str)
            and _safe_media_filename(media_path)
            and Path(media_path).suffix.lower() in HTML_EXTS
        ):
            return media_path
    return None


def _view_html_media_type(owner_id: str, filename: str) -> bool:
    """True when filename is an HTML variant of a view-kind request (serve scripted)."""
    if Path(filename).suffix.lower() not in HTML_EXTS:
        return False
    request_row = db.get_request(owner_id)
    if request_row is None or request_row.get("kind") != "view":
        return False
    return any(variant.get("media_path") == filename for variant in request_row.get("variants", []))


def _before_media_path(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,16}", suffix):
        suffix = ".bin"
    return f"__before{suffix}"


async def _write_upload(upload: UploadFile, dest_path: Path) -> int:
    return await _stream_upload(upload, dest_path)


async def _stream_upload(
    upload: UploadFile,
    dest_path: Path,
    *,
    mode: str = "wb",
    size_limit: int | None = None,
    digest=None,
) -> int:
    total = 0
    with dest_path.open(mode) as out:
        while True:
            chunk = await upload.read(UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if size_limit is not None and total > size_limit:
                raise HTTPException(
                    status_code=413,
                    detail=f"game build file exceeds {size_limit // (1024 * 1024)} MB",
                )
            if digest is not None:
                digest.update(chunk)
            await run_in_threadpool(out.write, chunk)
    return total


def _enforce_upload_size(request: Request, limit: int) -> None:
    """Reject an over-limit upload via its Content-Length, returning HTTP 413.

    Runs before the upload is persisted (media-dir write + DB row), so a rejected
    request leaves nothing behind. It does not bound ingest memory — the multipart
    body is already parsed by the time the handler runs — this is a persistence
    guardrail, not a streaming limit (streaming enforcement deferred).

    The guardrail's threat model is an accidental oversized upload through a
    trusted client (the portal CLI / Caddy), all of which send Content-Length;
    a missing or malformed header falls through to normal handling.
    """
    raw = request.headers.get("content-length")
    if raw is None:
        return
    try:
        size = int(raw)
    except ValueError:
        return
    if size > limit:
        raise HTTPException(
            status_code=413,
            detail=f"upload exceeds max size of {limit} bytes ({limit // (1024 * 1024)} MB)",
        )


def _validate_slug(slug: str) -> str:
    if not STREAM_SLUG_RE.fullmatch(slug):
        raise HTTPException(status_code=400, detail="invalid stream slug")
    return slug


def _bounded_text(value: object, name: str, max_length: int) -> str:
    result = _bounded_optional_text(value, name, max_length)
    if result is None:
        raise HTTPException(status_code=400, detail=f"{name} is required")
    return result


def _bounded_optional_text(value: object, name: str, max_length: int) -> str | None:
    """Bound an optional free-text field: absent/blank -> None, else validated like _bounded_text."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{name} must be a string")
    value = value.strip()
    if not value:
        return None
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


async def _json_object_body(request: Request) -> dict:
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    return body


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
    used_names: set[str] = set()
    try:
        for i, upload in enumerate(uploads, start=1):
            original_name = upload.filename or f"file_{i}"
            safe_name = _prefixed_media_name(i, original_name, f"file_{i}", used_names)
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


def _validate_message_direction(value: object) -> str:
    direction = _bounded_text(value, "direction", 32)
    if direction not in db.MESSAGE_DIRECTIONS:
        raise HTTPException(status_code=400, detail=f"invalid message direction: {direction}")
    return direction


def _validate_optional_message_direction(value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_message_direction(value)


def _validate_since(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise HTTPException(status_code=400, detail="since must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="since must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(status_code=400, detail="since must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _parse_unconsumed(value: str | None) -> bool:
    if value is None:
        return False
    if value != "1":
        raise HTTPException(status_code=400, detail="unconsumed must be 1 when supplied")
    return True


def _message_mutation_status(exc: ValueError) -> int:
    if isinstance(
        exc,
        (db.StreamClosedError, db.MessageDeliveryStateError, db.MessageIdempotencyConflictError),
    ):
        return 409
    if isinstance(exc, (db.MessageNotFoundError, db.StreamNotFoundError)):
        return 404
    return 400


def _notify_to_human_message(slug: str, text: str) -> None:
    try:
        server_cfg = config.load_config()
        url = f"{server_cfg['url']}/s/{quote(slug, safe='')}?token={server_cfg['token']}"
        notify_text = f"Portal question in {slug}: {text} - {url}"
        threading.Thread(
            target=notify.send_text,
            args=(server_cfg, notify_text),
            daemon=True,
        ).start()
    except Exception as exc:  # noqa: BLE001 - notification startup must never fail message creation
        log.warning("message notification failed to start: %s", exc)


@app.post("/api/requests")
async def create_request(
    request: Request,
    title: str = Form(...),
    project: str | None = Form(None),
    kind: str = Form(...),
    context: str | None = Form(None),
    manifest: str | None = Form(None),
    step: str | None = Form(None),
    purpose: str | None = Form(None),
    ask: str | None = Form(None),
    stream: str | None = Form(None),
    author: str | None = Form(None),
    before: UploadFile | None = File(None),
    files: list[UploadFile] = File(...),
):
    server_cfg = require_api_token(request)
    _enforce_upload_size(request, server_cfg.get("max_upload_bytes", config.DEFAULT_MAX_UPLOAD_BYTES))
    step = _bounded_optional_text(step, "step", MAX_TITLE_LENGTH)
    purpose = _bounded_optional_text(purpose, "purpose", MAX_TITLE_LENGTH)
    ask = _bounded_optional_text(ask, "ask", MAX_TITLE_LENGTH)
    author = _bounded_optional_text(author, "author", MAX_AUTHOR_LENGTH)
    if stream is not None and stream.strip():
        stream = _validate_slug(stream)
    else:
        stream = None

    if kind not in db.KINDS:
        raise HTTPException(status_code=400, detail=f"invalid kind: {kind}. Must be one of {db.KINDS}")
    if not files:
        raise HTTPException(status_code=400, detail="at least one file is required")
    if kind == "view" and not any(Path(f.filename or "").suffix.lower() in HTML_EXTS for f in files):
        raise HTTPException(status_code=400, detail="view requests require an HTML entry file")

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
        used_names: set[str] = set()
        try:
            if before is not None and before.filename:
                before_media_path = _before_media_path(before.filename)
                await _write_upload(before, dest_dir / before_media_path)
                before_media_type = _media_type_for(before.filename)

            for i, upload in enumerate(request_uploads, start=1):
                orig_name = upload.filename or f"variant_{i}"
                safe_name = _prefixed_media_name(i, orig_name, f"variant_{i}", used_names)
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
                step=step,
                purpose=purpose,
                ask=ask,
                stream=stream,
                author=author,
            )
            try:
                threading.Thread(
                    target=_transcode_gifs_to_loop_mp4,
                    args=(dest_dir, [v["media_path"] for v in variants]),
                    daemon=True,
                ).start()
            except Exception as exc:  # noqa: BLE001 - transcode startup must never fail request creation
                log.warning("gif transcode thread failed to start: %s", exc)
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

    url = f"{server_cfg['url']}/r/{req_id}?token={server_cfg['token']}"
    try:
        threading.Thread(
            target=notify.send_doorbell,
            args=(server_cfg, title, len(variants), url),
            daemon=True,
        ).start()
    except Exception as exc:  # noqa: BLE001 - notification startup must never fail request creation
        log.warning("request notification failed to start: %s", exc)

    result = {"id": req_id, "url": f"{server_cfg['url']}/r/{req_id}", "variant_count": len(variants)}
    if stream:
        created = db.get_request(req_id)
        if created and created.get("stream_id"):
            siblings = db.open_requests_in_stream(created["stream_id"], exclude_id=req_id)
            if siblings:
                result["open_in_stream"] = siblings
    return result


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
    if slug == AGENT_CONVERSATION_STREAM_SLUG:
        raise HTTPException(status_code=409, detail="the internal agent conversation stream cannot be archived")
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


@app.post("/api/streams/{slug}/messages")
async def create_stream_message(request: Request, slug: str):
    require_api_token(request)
    _validate_slug(slug)
    body = await _json_object_body(request)
    direction = _validate_message_direction(body.get("direction"))
    text = _bounded_text(body.get("text"), "text", MAX_MESSAGE_TEXT_LENGTH)
    message = None
    for _ in range(5):
        try:
            message = db.create_message_for_stream(slug, direction, text)
            break
        except sqlite3.IntegrityError:
            continue
        except ValueError as exc:
            raise HTTPException(status_code=_message_mutation_status(exc), detail=str(exc)) from exc
    if message is None:
        raise HTTPException(status_code=500, detail="could not allocate unique message id")
    if direction == "to_human":
        _notify_to_human_message(slug, text)
    return message


@app.get("/api/streams/{slug}/messages")
def list_stream_messages(
    request: Request,
    slug: str,
    since: str | None = None,
    direction: str | None = None,
    unconsumed: str | None = None,
):
    require_api_token(request)
    _validate_slug(slug)
    direction = _validate_optional_message_direction(direction)
    since = _validate_since(since)
    unconsumed_only = _parse_unconsumed(unconsumed)
    stream = db.get_stream(slug)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")
    return db.list_messages(
        stream["id"],
        since=since,
        direction=direction,
        unconsumed=unconsumed_only,
    )


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


@app.post("/api/messages/{message_id}/consume")
def consume_message(request: Request, message_id: str):
    require_api_token(request)
    if not SAFE_SEGMENT_RE.fullmatch(message_id) or message_id in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid message id")
    try:
        return db.consume_message(message_id)
    except ValueError as exc:
        raise HTTPException(status_code=_message_mutation_status(exc), detail=str(exc)) from exc


def _apply_verdict(req_id: str, body: dict, *, allow_revision: bool = True) -> dict:
    r = db.get_request(req_id)
    if r is None:
        raise HTTPException(status_code=404, detail="request not found")

    if r["status"] == "superseded":
        raise HTTPException(
            status_code=409,
            detail={"error": "superseded", "successor": r.get("superseded_by")},
        )
    if r["status"] == "closed":
        raise HTTPException(
            status_code=409,
            detail={"error": "closed", "reason": r.get("close_reason")},
        )

    requested_revision = body.get("redecide") is True
    if requested_revision and not allow_revision:
        raise HTTPException(
            status_code=403,
            detail={"error": "revision_forbidden"},
        )

    verdict_count = db.count_verdicts(req_id)
    if verdict_count > 0 and not requested_revision:
        raise HTTPException(
            status_code=409,
            detail={"error": "verdict_exists", "verdict_count": verdict_count},
        )

    selected = body.get("selected", [])
    ratings = body.get("ratings")
    comment = body.get("comment")
    payload = None

    if not isinstance(selected, list) or not all(isinstance(i, int) for i in selected):
        raise HTTPException(status_code=400, detail="selected must be a list of integers")

    if r.get("kind") == "view":
        # View verdicts are opaque producer-defined JSON; Portal stores, never interprets.
        if "payload" not in body:
            raise HTTPException(status_code=400, detail="view verdicts require a payload field")
        payload = body["payload"]
        _validate_json_response_safe(payload)
        if len(json.dumps(payload).encode("utf-8")) > MAX_BODY_JSON_BYTES:
            raise HTTPException(status_code=400, detail="payload JSON is too large")
    else:
        valid_indices = db.variant_indices(req_id)
        bad = [i for i in selected if i not in valid_indices]
        if bad:
            raise HTTPException(status_code=400, detail=f"selected indices not found on this request: {bad}")

    try:
        result = db.record_verdict(
            req_id,
            selected,
            ratings,
            comment,
            payload=payload,
            allow_revision=requested_revision,
        )
    except db.VerdictExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "verdict_exists", "verdict_count": exc.verdict_count},
        ) from exc
    except ValueError as exc:
        detail = str(exc)
        status = 409 if isinstance(exc, db.RequestTerminalError) or "closed" in detail else 400
        raise HTTPException(status_code=status, detail=detail) from exc
    # Push the verdict back to the posting agent (todos/cards/007): configured
    # hook fires in a background thread; a decide never waits on or fails from it.
    try:
        server_cfg = config.load_config()
        chain_url = f"{server_cfg.get('url', '')}/c/{req_id}"
        threading.Thread(
            target=notify.run_verdict_hook,
            args=(server_cfg, r, result.get("verdict") or {"selected": selected, "comment": comment}, chain_url),
            daemon=True,
        ).start()
    except Exception as exc:  # noqa: BLE001 - notification startup must never fail a decide
        log.warning("verdict notify hook failed to start: %s", exc)
    return result


@app.post("/api/requests/{req_id}/verdict")
async def post_verdict(request: Request, req_id: str):
    require_api_token(request)
    body = await request.json()
    return _apply_verdict(req_id, body)


def _lifecycle_mutation_status(exc: ValueError) -> int:
    if isinstance(exc, (db.RequestNotFoundError, db.SuccessorNotFoundError)):
        return 404
    if isinstance(exc, db.RequestTerminalError):
        return 409
    return 400


@app.post("/api/requests/{req_id}/close")
async def close_request(request: Request, req_id: str):
    require_api_token(request)
    body = await _json_object_body(request)
    reason = _bounded_text(body.get("reason"), "reason", MAX_MESSAGE_TEXT_LENGTH)
    try:
        return db.close_request(req_id, reason)
    except ValueError as exc:
        raise HTTPException(status_code=_lifecycle_mutation_status(exc), detail=str(exc)) from exc


@app.post("/api/requests/{req_id}/supersede")
async def supersede_request(request: Request, req_id: str):
    require_api_token(request)
    body = await _json_object_body(request)
    successor = _bounded_text(body.get("successor"), "successor", 128)
    feedback = _bounded_optional_text(body.get("feedback"), "feedback", MAX_MESSAGE_TEXT_LENGTH)
    try:
        return db.supersede_request(req_id, successor, feedback_md=feedback)
    except ValueError as exc:
        raise HTTPException(status_code=_lifecycle_mutation_status(exc), detail=str(exc)) from exc


@app.post("/api/requests/{req_id}/feedback")
async def set_request_feedback(request: Request, req_id: str):
    require_api_token(request)
    body = await _json_object_body(request)
    feedback = _bounded_text(body.get("feedback"), "feedback", MAX_MESSAGE_TEXT_LENGTH)
    try:
        return db.set_feedback(req_id, feedback)
    except db.RequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --- journeys ---


def _validate_safe_segment(value: object, name: str) -> str:
    """A DB owner/request id used as a path segment: bounded + SAFE_SEGMENT_RE, no dot-dirs."""
    segment = _bounded_text(value, name, 128)
    if not SAFE_SEGMENT_RE.fullmatch(segment) or segment in {".", ".."}:
        raise HTTPException(status_code=400, detail=f"invalid {name}")
    return segment


def _validate_journey_media_ref(ref: object, step_index: int, media_index: int) -> dict:
    # Error details carry the steps[i].media[j] path so a producer fixing a
    # large agent-authored doc can locate the offending element without bisecting.
    where = f"steps[{step_index}].media[{media_index}]"
    if not isinstance(ref, dict):
        raise HTTPException(status_code=400, detail=f"{where} must be an object")
    owner_id = _validate_safe_segment(ref.get("owner_id"), f"{where}.owner_id")
    filename = _bounded_text(ref.get("filename"), f"{where}.filename", 260)
    if not _safe_media_filename(filename):
        raise HTTPException(status_code=400, detail=f"invalid {where}.filename")
    cleaned = {"owner_id": owner_id, "filename": filename}
    caption = _bounded_optional_text(ref.get("caption"), f"{where}.caption", MAX_TITLE_LENGTH)
    if caption is not None:
        cleaned["caption"] = caption
    return cleaned


def _validate_journey_step(step: object, step_index: int) -> dict:
    where = f"steps[{step_index}]"
    if not isinstance(step, dict):
        raise HTTPException(status_code=400, detail=f"{where} must be an object")
    cleaned = {"title": _bounded_text(step.get("title"), f"{where}.title", MAX_TITLE_LENGTH)}
    summary = _bounded_optional_text(step.get("summary"), f"{where}.summary", MAX_MESSAGE_TEXT_LENGTH)
    if summary is not None:
        cleaned["summary"] = summary
    media = step.get("media")
    if media is not None:
        if not isinstance(media, list):
            raise HTTPException(status_code=400, detail=f"{where}.media must be a list")
        if len(media) > MAX_STEP_MEDIA:
            raise HTTPException(status_code=400, detail=f"{where} may reference at most {MAX_STEP_MEDIA} media")
        cleaned["media"] = [
            _validate_journey_media_ref(ref, step_index, media_index) for media_index, ref in enumerate(media)
        ]
    request_id = step.get("request_id")
    if request_id is not None:
        cleaned["request_id"] = _validate_safe_segment(request_id, f"{where}.request_id")
    return cleaned


def _validate_journey_doc(payload: dict) -> dict:
    """Deterministic structural validation of a journey doc. Returns a normalized
    {"steps": [...]} dict carrying only validated fields (unknown keys dropped)."""
    steps = payload.get("steps")
    if not isinstance(steps, list):
        raise HTTPException(status_code=400, detail="journey steps must be a list")
    if len(steps) > MAX_JOURNEY_STEPS:
        raise HTTPException(status_code=400, detail=f"a journey may have at most {MAX_JOURNEY_STEPS} steps")
    doc = {"steps": [_validate_journey_step(step, step_index) for step_index, step in enumerate(steps)]}
    # Optional one-line lede. Journeys are no longer only game stories, so a
    # producer can name what this page is instead of inheriting the game copy.
    subtitle = _bounded_optional_text(payload.get("subtitle"), "subtitle", MAX_TITLE_LENGTH)
    if subtitle is not None:
        doc["subtitle"] = subtitle
    if len(json.dumps(doc).encode("utf-8")) > MAX_BODY_JSON_BYTES:
        raise HTTPException(status_code=400, detail="journey doc is too large")
    _validate_json_response_safe(doc)
    return doc


@app.put("/api/journeys/{slug}")
async def put_journey(request: Request, slug: str):
    """Post or re-post (update-in-place) a journey doc at a stable slug."""
    require_api_token(request)
    _validate_slug(slug)
    body = await _json_object_body(request)
    title = _bounded_text(body.get("title"), "title", MAX_TITLE_LENGTH)
    doc = _validate_journey_doc(body)
    return db.upsert_journey(slug, title, doc)


@app.get("/api/journeys")
def list_journeys(request: Request):
    require_api_token(request)
    return db.list_journeys()


@app.get("/api/journeys/{slug}")
def get_journey(request: Request, slug: str):
    require_api_token(request)
    _validate_slug(slug)
    journey = db.get_journey(slug)
    if journey is None:
        raise HTTPException(status_code=404, detail="journey not found")
    return journey


# --- media serving ---


def _report_context_header_bytes(post_id: str) -> bytes:
    """Context header for a report producer page: home + stream + metadata, no status."""
    post = db.get_post(post_id)
    stream = db.get_stream_by_id(post["stream_id"]) if post and post.get("stream_id") else None
    body = post.get("body") if post else None
    body = body if isinstance(body, dict) else {}
    return _context_header_bytes(
        stream=stream,
        step=_render_safe_metadata(body.get("step")),
        ask=_render_safe_metadata(body.get("ask")),
        status=None,
    )


def _view_context_header_bytes(req_id: str) -> bytes:
    """Context header for a view producer page: home + stream + metadata + request status."""
    r = db.get_request(req_id)
    stream = db.get_stream_by_id(r["stream_id"]) if r and r.get("stream_id") else None
    return _context_header_bytes(
        stream=stream,
        step=(r or {}).get("step"),
        ask=(r or {}).get("ask"),
        status=(r or {}).get("status"),
    )


def _media_file_path(owner_id: str, filename: str) -> Path:
    if (
        not SAFE_SEGMENT_RE.fullmatch(owner_id)
        or owner_id in {".", ".."}
        or not _safe_media_filename(filename)
    ):
        raise HTTPException(status_code=404, detail="media not found")
    media_root = config.media_dir().resolve()
    media_dir = (media_root / owner_id).resolve()
    path = (media_dir / filename).resolve()
    try:
        path.relative_to(media_dir)
        media_dir.relative_to(media_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="media not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="media not found")
    return path


def _view_media_url(req_id: str, filename: str) -> str:
    capability = _view_capability(req_id)
    return (
        f"/view/{quote(req_id, safe='')}/{capability}/"
        f"{quote(filename, safe='')}"
    )


@app.get("/view/{req_id}/{capability}/{filename}")
def get_view_media(req_id: str, capability: str, filename: str):
    if not _view_capability_ok(req_id, capability):
        raise HTTPException(status_code=404, detail="view not found")
    request_row = db.get_request(req_id)
    if request_row is None or request_row.get("kind") != "view":
        raise HTTPException(status_code=404, detail="view not found")
    if filename not in {variant.get("media_path") for variant in request_row.get("variants", [])}:
        raise HTTPException(status_code=404, detail="view media not found")
    path = _media_file_path(req_id, filename)
    media_type, _ = mimetypes.guess_type(str(path))
    headers = {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }
    if Path(filename).suffix.lower() in HTML_EXTS:
        headers["Content-Security-Policy"] = VIEW_HTML_CSP
        return _html_with_context_header(
            path,
            "text/html",
            headers,
            _view_context_header_bytes(req_id),
            bootstrap_bytes=_view_fetch_bridge_bytes(req_id, capability),
        )
    return FileResponse(path, media_type=media_type or "application/octet-stream", headers=headers)


@app.get("/media/{req_id}/{filename}")
def get_media(request: Request, req_id: str, filename: str):
    if not web_view_ok(request):
        raise HTTPException(status_code=401, detail="missing or invalid token")
    path = _media_file_path(req_id, filename)
    media_type, _ = mimetypes.guess_type(str(path))
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
    }
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
        return _html_with_context_header(
            path, report_html_type, headers, _report_context_header_bytes(req_id)
        )
    if _view_html_media_type(req_id, filename):
        if not web_token_ok(request):
            headers["Content-Security-Policy"] = VIEW_HTML_CSP
            return _html_with_context_header(
                path, "text/html", headers, _view_context_header_bytes(req_id)
            )
        response = RedirectResponse(url=_view_media_url(req_id, filename), status_code=303)
        _maybe_set_cookie(response, request)
        return response
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


def _request_status_map(candidate_ids: list[object]) -> dict[str, dict]:
    """One batched read of the live status/title of every referenced request.
    Non-string/empty/duplicate candidates are skipped; unknown ids are simply absent."""
    ids = []
    seen = set()
    for request_id in candidate_ids:
        if isinstance(request_id, str) and request_id and request_id not in seen:
            seen.add(request_id)
            ids.append(request_id)
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    conn = db.connect()
    with db._lock:
        rows = conn.execute(
            f"SELECT id, title, status FROM requests WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    return {row["id"]: dict(row) for row in rows}


def _request_summaries_for_posts(posts: list[dict]) -> dict[str, dict]:
    return _request_status_map(
        [_decision_request_id(post) for post in posts if post.get("type") == "decision"]
    )


def _decision_post_context(post: dict, request_summaries: dict[str, dict]) -> dict | None:
    request_id = _decision_request_id(post)
    if request_id is None:
        return None
    request_row = request_summaries.get(request_id)
    if request_row is None:
        return None
    raw_status = request_row.get("status")
    status = raw_status if raw_status in ("decided", "closed", "superseded") else "pending"
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


def _stream_message_context(stream: dict) -> dict:
    messages = list(reversed(db.list_messages(stream["id"])))
    questions = []
    answered_questions = []
    to_agent = []
    for message in messages:
        if message.get("direction") == "to_human":
            if message.get("consumed_at") is None:
                questions.append(message)
            else:
                answered_questions.append(message)
        elif message.get("direction") == "to_agent":
            to_agent.append(message)
    return {
        "questions": questions,
        "answered_questions": answered_questions,
        "to_agent": to_agent,
    }


def _web_stream_or_404(slug: str) -> dict:
    _validate_slug(slug)
    stream = db.get_stream(slug)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")
    return stream


def _reject_closed_stream(stream: dict) -> None:
    if stream["closed_at"] is not None:
        raise HTTPException(status_code=409, detail=f"stream is closed: {stream['slug']}")


def _web_open_stream_or_404(slug: str) -> dict:
    stream = _web_stream_or_404(slug)
    _reject_closed_stream(stream)
    return stream


def _validate_question_id(value: object) -> str:
    question_id = _bounded_text(value, "question_id", 128)
    if not SAFE_SEGMENT_RE.fullmatch(question_id) or question_id in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid question id")
    return question_id


def _validate_agent_target(provider: object, session_id: object) -> tuple[str, str]:
    if not agents.valid_provider(provider):
        raise HTTPException(status_code=400, detail="invalid agent provider")
    if not agents.valid_session_id(session_id):
        raise HTTPException(status_code=400, detail="invalid agent session id")
    return provider, session_id


def _agent_message_text(value: object) -> str:
    text = _bounded_text(value, "text", agents.MAX_AGENT_TEXT_LENGTH)
    if not agents.valid_single_paragraph(text):
        raise HTTPException(status_code=400, detail="text must be one paragraph without control characters")
    return text


def _client_submission_key(value: object) -> str:
    key = _bounded_text(value, "idempotency_key", 128)
    if not CLIENT_SUBMISSION_KEY_RE.fullmatch(key):
        raise HTTPException(
            status_code=400,
            detail="idempotency_key must be 16-128 URL-safe characters",
        )
    return key


def _agent_directory() -> tuple[list[dict], str | None]:
    try:
        return agents.list_replyable_agents(), None
    except agents.AgentBridgeError as exc:
        return [], str(exc)


def _ensure_agent_conversation_stream() -> dict:
    stream = db.get_stream(AGENT_CONVERSATION_STREAM_SLUG)
    if stream is not None:
        return db.reopen_stream(AGENT_CONVERSATION_STREAM_SLUG) if stream["closed_at"] else stream
    try:
        return db.create_stream(AGENT_CONVERSATION_STREAM_SLUG, "pinned", "Agent conversations")
    except sqlite3.IntegrityError:
        stream = db.get_stream(AGENT_CONVERSATION_STREAM_SLUG)
        if stream is None:
            raise
        return db.reopen_stream(AGENT_CONVERSATION_STREAM_SLUG) if stream["closed_at"] else stream


def _submit_targeted_message(message_id: str, *, allow_unknown: bool = False) -> dict:
    try:
        message = db.claim_message_delivery(message_id, allow_unknown=allow_unknown)
    except ValueError as exc:
        raise HTTPException(status_code=_message_mutation_status(exc), detail=str(exc)) from exc
    try:
        result = agents.submit_to_agent(
            message["target_provider"],
            message["target_session_id"],
            message["text"],
        )
        outcome = result["outcome"]
        detail = result["detail"]
    except Exception:  # noqa: BLE001 - an invoked bridge may already have submitted input
        log.exception("agent terminal submission bridge failed for message %s", message_id)
        outcome = "unknown"
        detail = "portal_bridge_exception"
    try:
        return db.complete_message_delivery(message_id, outcome, detail)
    except Exception as exc:  # noqa: BLE001 - terminal input may already have been submitted
        log.exception("message delivery completion failed for %s", message_id)
        try:
            return db.reconcile_message_delivery_unknown(message_id, "portal_completion_failed")
        except Exception:  # noqa: BLE001 - startup recovery remains the final fallback
            log.exception("message delivery reconciliation failed for %s", message_id)
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=_message_mutation_status(exc), detail=str(exc)) from exc
        raise HTTPException(
            status_code=500,
            detail="message delivery completion failed; outcome is unknown",
        ) from exc


def _create_targeted_to_agent_message(
    stream: dict,
    text: str,
    provider: str,
    session_id: str,
    client_submission_key: str,
) -> dict:
    try:
        message, _created = db.create_or_get_targeted_message(
            stream["id"],
            text,
            provider,
            session_id,
            client_submission_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=_message_mutation_status(exc), detail=str(exc)) from exc

    # Repeated initial requests are reconciliation reads. Only a row that has
    # never been claimed may enter the bridge; every other state is returned
    # verbatim so an ambiguous/lost response cannot duplicate terminal input.
    if message.get("delivery_state") != "pending":
        return message
    try:
        return _submit_targeted_message(message["id"])
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        current = db.get_message(message["id"])
        if current is not None and current.get("delivery_state") != "pending":
            return current
        raise


def _create_to_agent_message(stream: dict, text: str) -> dict:
    for _ in range(5):
        try:
            return db.create_message(stream["id"], "to_agent", text)
        except sqlite3.IntegrityError:
            continue
        except ValueError as exc:
            raise HTTPException(status_code=_message_mutation_status(exc), detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail="could not allocate unique message id")


def _create_answer_message(stream: dict, question_id: str, text: str) -> dict:
    conn = db.connect()
    for _ in range(5):
        with db._lock:
            try:
                question = conn.execute("SELECT * FROM messages WHERE id = ?", (question_id,)).fetchone()
                if question is None or question["stream_id"] != stream["id"]:
                    raise HTTPException(status_code=404, detail="question not found")
                if question["direction"] != "to_human":
                    raise HTTPException(status_code=400, detail="question_id must reference a to_human message")

                fresh_stream = conn.execute("SELECT closed_at FROM streams WHERE id = ?", (stream["id"],)).fetchone()
                if fresh_stream is None:
                    raise HTTPException(status_code=404, detail="stream not found")
                if fresh_stream["closed_at"] is not None:
                    raise HTTPException(status_code=409, detail=f"stream is closed: {stream['slug']}")
                if question["consumed_at"] is not None:
                    raise HTTPException(status_code=409, detail="question already answered")

                consumed_at = db.now_iso()
                cur = conn.execute(
                    """
                    UPDATE messages
                    SET consumed_at = ?
                    WHERE id = ?
                      AND stream_id = ?
                      AND direction = 'to_human'
                      AND consumed_at IS NULL
                    """,
                    (consumed_at, question_id, stream["id"]),
                )
                if cur.rowcount != 1:
                    raise HTTPException(status_code=409, detail="question already answered")

                message_id = db.new_message_id()
                conn.execute(
                    "INSERT INTO messages (id, stream_id, direction, text, created_at) VALUES (?, ?, ?, ?, ?)",
                    (message_id, stream["id"], "to_agent", text, db.now_iso()),
                )
                message = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
                conn.commit()
                assert message is not None
                return dict(message)
            except sqlite3.IntegrityError:
                conn.rollback()
                continue
            except HTTPException:
                conn.rollback()
                raise
            except Exception:
                conn.rollback()
                raise
    raise HTTPException(status_code=500, detail="could not allocate unique message id")


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
    if not web_view_ok(request):
        return _login_redirect(request)
    open_requests = db.list_requests(status="open")
    decided = db.list_requests(status="decided", q=q)
    retired = db.list_requests(status="closed") + db.list_requests(status="superseded")
    streams = _list_stream_summaries()
    journeys = db.list_journeys()
    games = db.list_games()
    response = templates.TemplateResponse(
        request,
        "index.html",
        {
            "open_requests": open_requests,
            "decided": decided,
            "retired": retired,
            "q": q or "",
            "streams": streams,
            "journeys": journeys,
            "games": games,
        },
    )
    _maybe_set_cookie(response, request)
    return response


def _agent_history_context(sessions: list[dict]) -> tuple[list[dict], list[dict]]:
    history = db.list_targeted_messages(limit=100)
    labels = {(session["provider"], session["sid"]): session["label"] for session in sessions}
    for message in history:
        message["target_label"] = labels.get(
            (message["target_provider"], message["target_session_id"]),
            f"{message['target_provider']} · {message['target_session_id'][:12]}",
        )
        stream_open = message["stream_closed_at"] is None
        message["retryable"] = stream_open and message["delivery_state"] == "failed"
        message["confirmable"] = stream_open and message["delivery_state"] == "unknown"
    by_target: dict[tuple[str, str], list[dict]] = {}
    for message in history:
        by_target.setdefault((message["target_provider"], message["target_session_id"]), []).append(message)
    session_rows = []
    for session in sessions:
        row = dict(session)
        row["messages"] = by_target.get((row["provider"], row["sid"]), [])[:5]
        session_rows.append(row)
    return session_rows, history


@app.get("/agents/directory")
def web_agent_directory(request: Request):
    if not web_token_ok(request):
        return _login_redirect(request)
    sessions, error = _agent_directory()
    if error is not None:
        return {"sessions": [], "error": error}
    return {"sessions": sessions, "error": None}


@app.get("/agents", response_class=HTMLResponse)
def web_agents(request: Request):
    if not web_token_ok(request):
        return _login_redirect(request)
    sessions, agency_error = _agent_directory()
    session_rows, history = _agent_history_context(sessions)
    response = templates.TemplateResponse(
        request,
        "agents.html",
        {
            "sessions": session_rows,
            "history": history,
            "agency_error": agency_error,
        },
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    _maybe_set_cookie(response, request)
    return response


@app.post("/agents/{provider}/{session_id}/messages")
async def web_agent_message(request: Request, provider: str, session_id: str):
    if not web_token_ok(request):
        raise HTTPException(status_code=401, detail="missing or invalid token")
    provider, session_id = _validate_agent_target(provider, session_id)
    body = await _json_object_body(request)
    text = _agent_message_text(body.get("text"))
    client_submission_key = _client_submission_key(body.get("idempotency_key"))
    stream = await run_in_threadpool(_ensure_agent_conversation_stream)
    return await run_in_threadpool(
        _create_targeted_to_agent_message,
        stream,
        text,
        provider,
        session_id,
        client_submission_key,
    )


@app.post("/agents/messages/{message_id}/retry")
async def web_agent_message_retry(request: Request, message_id: str):
    if not web_token_ok(request):
        raise HTTPException(status_code=401, detail="missing or invalid token")
    _validate_question_id(message_id)
    body = await _json_object_body(request)
    allow_unknown = body.get("confirm_unknown") is True
    return await run_in_threadpool(_submit_targeted_message, message_id, allow_unknown=allow_unknown)


def _game_page_context(slug: str) -> dict:
    game = db.get_game(slug)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    for build in game["builds"]:
        build["changelog_html"] = _sanitize_context_html(md_lib.markdown(build["changelog_md"]))
        build["artifact_label"] = "APK" if Path(build["artifact_path"]).suffix.lower() == ".apk" else "Build"
        encoded_version = quote(build["version"], safe="")
        build["download_url"] = f"/games/{slug}/builds/{encoded_version}/public-download"
        video_path = config.games_dir() / slug / build["version"] / build["video_path"]
        try:
            video_revision = video_path.stat().st_mtime_ns
        except OSError:
            video_revision = 0
        build["video_url"] = f"/games/{slug}/builds/{encoded_version}/public-video?rev={video_revision}"
        if build[GAME_WEB_FIELD]:
            preview_path = config.games_dir() / slug / build["version"] / build[GAME_WEB_FIELD]
            try:
                preview_revision = preview_path.stat().st_mtime_ns
            except OSError:
                preview_revision = 0
            build["preview_url"] = (
                f"/games/{slug}/builds/{encoded_version}/play/?rev={preview_revision}"
            )
        else:
            build["preview_url"] = None
    return game


@app.get("/games", response_class=HTMLResponse)
def web_games(request: Request):
    if not web_view_ok(request):
        return _login_redirect(request)
    response = templates.TemplateResponse(request, "games.html", {"games": db.list_games()})
    _maybe_set_cookie(response, request)
    return response


@app.get("/games/{slug}", response_class=HTMLResponse)
def web_game_detail(request: Request, slug: str):
    if not web_token_ok(request):
        if _is_link_preview_crawler(request):
            game = db.get_game(slug)
            if game is None:
                raise HTTPException(status_code=404, detail="game not found")
            return _game_crawler_preview_response(request, game)
    game = _game_page_context(slug)
    response = templates.TemplateResponse(
        request,
        "game.html",
        {
            "game": game,
            "og": _game_og_context(request, game),
            "has_remote_config": remote_config.game_settings(slug) is not None,
        },
    )
    _maybe_set_cookie(response, request)
    return response


def _remote_config_context(slug: str, settings: dict) -> dict:
    game = db.get_game(slug)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    template = remote_config.read_template(settings)
    return {
        "game": game,
        "project": settings["project"],
        "params": remote_config.editable_params(template, settings),
    }


@app.get("/games/{slug}/remote-config", response_class=HTMLResponse)
def web_game_remote_config(request: Request, slug: str):
    if not web_token_ok(request):
        return _login_redirect(request)
    settings = remote_config.game_settings(slug)
    if settings is None:
        raise HTTPException(status_code=404, detail="game has no remote config")
    try:
        context = _remote_config_context(slug, settings)
    except remote_config.RemoteConfigError as exc:
        game = db.get_game(slug)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found") from exc
        context = {"game": game, "project": settings["project"], "params": [], "error": str(exc)}
    response = templates.TemplateResponse(request, "remote_config.html", context)
    _maybe_set_cookie(response, request)
    return response


@app.post("/games/{slug}/remote-config")
async def web_game_remote_config_publish(request: Request, slug: str):
    if not web_token_ok(request):
        return _login_redirect(request)
    settings = remote_config.game_settings(slug)
    if settings is None:
        raise HTTPException(status_code=404, detail="game has no remote config")
    form = await request.form()
    updates = {key[len(_RC_FIELD_PREFIX):]: str(value) for key, value in form.items() if key.startswith(_RC_FIELD_PREFIX)}
    try:
        changed = remote_config.publish(settings, updates)
        message = (
            f"Published {len(changed)} change{'s' if len(changed) != 1 else ''}: {', '.join(changed)}"
            if changed
            else "No changes to publish."
        )
        status = "ok"
    except remote_config.RemoteConfigError as exc:
        message, status = str(exc), "error"
    context = _remote_config_context(slug, settings)
    context.update({"message": message, "status": status})
    response = templates.TemplateResponse(request, "remote_config.html", context)
    _maybe_set_cookie(response, request)
    return response


def _resolve_game_build_file(slug: str, version: str, field: str | None = None, *, filename: str | None = None) -> Path:
    _validate_game_release_ref(slug, version)
    build = db.get_game_build(slug, version)
    if build is None:
        raise HTTPException(status_code=404, detail="game build not found")
    stored_name = filename
    if stored_name is None:
        assert field is not None
        stored_name = build[field]
    return _resolve_game_release_path(slug, version, stored_name)


def _resolve_game_release_path(slug: str, version: str, stored_name: str) -> Path:
    release_root = (config.games_dir() / slug / version).resolve()
    path = (release_root / stored_name).resolve()
    try:
        path.relative_to(release_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="game build file not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="game build file not found")
    return path


def _game_file_response(
    path: Path,
    *,
    public: bool,
    download: bool,
    fallback_media_type: str,
    extra_headers: dict[str, str] | None = None,
):
    headers = {
        "Cache-Control": f"{'public' if public else 'private'}, max-age=31536000, immutable",
        "Referrer-Policy": "no-referrer",
    }
    headers.update(extra_headers or {})
    return FileResponse(
        path,
        media_type=mimetypes.guess_type(path.name)[0] or fallback_media_type,
        filename=path.name if download else None,
        content_disposition_type="attachment" if download else "inline",
        headers=headers,
    )


def _private_game_release_file(request: Request, slug: str, version: str, field: str, *, download: bool):
    if not web_view_ok(request):
        return _login_redirect(request)
    path = _resolve_game_build_file(slug, version, field)
    return _game_file_response(path, public=False, download=download, fallback_media_type="application/octet-stream")


@app.get("/games/{slug}/builds/{version}/download")
def download_game_build(request: Request, slug: str, version: str):
    return _private_game_release_file(request, slug, version, GAME_ARTIFACT_FIELD, download=True)


@app.get("/games/{slug}/builds/{version}/public-download")
def public_download_game_build(slug: str, version: str):
    path = _resolve_game_build_file(slug, version, GAME_ARTIFACT_FIELD)
    return _game_file_response(path, public=True, download=True, fallback_media_type="application/octet-stream")


@app.get("/games/{slug}/builds/{version}/video")
def watch_game_build(request: Request, slug: str, version: str):
    return _private_game_release_file(request, slug, version, GAME_VIDEO_FIELD, download=False)


@app.get("/games/{slug}/builds/{version}/play/{path:path}")
def public_play_game_build(slug: str, version: str, path: str = ""):
    """Serve one file of a release's browser preview bundle, publicly and inertly."""
    _validate_game_release_ref(slug, version)
    build = db.get_game_build(slug, version)
    if build is None:
        raise HTTPException(status_code=404, detail="game build not found")
    entry = build[GAME_WEB_FIELD]
    if not entry:
        raise HTTPException(status_code=404, detail="game build has no browser preview")
    stored_name = entry if not path else f"{PurePosixPath(entry).parent}/{path}"
    resolved = _resolve_game_release_path(slug, version, stored_name)
    return _game_file_response(
        resolved,
        public=True,
        download=False,
        fallback_media_type="application/octet-stream",
        extra_headers={
            "Cache-Control": (
                "public, max-age=0, must-revalidate"
                if resolved.suffix.lower() == ".html"
                else "public, max-age=31536000, immutable"
            ),
            "Content-Security-Policy": GAME_WEB_CSP,
            "X-Content-Type-Options": "nosniff",
            # The iframe has an opaque origin, so the bundle's own module
            # scripts and fonts are cross-origin requests to Portal. Without
            # this the Vite entry module never loads and the game never
            # starts. Safe: these files are already public and unauthenticated.
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.get("/games/{slug}/builds/{version}/public-video")
def public_watch_game_build(slug: str, version: str):
    path = _resolve_game_build_file(slug, version, GAME_VIDEO_FIELD)
    return _game_file_response(path, public=True, download=False, fallback_media_type="video/mp4")


@app.get("/s/{slug}", response_class=HTMLResponse)
def web_stream_detail(request: Request, slug: str):
    if not web_view_ok(request):
        return _login_redirect(request)
    _validate_slug(slug)
    stream = db.get_stream_with_posts(slug)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")
    posts = sorted(stream["posts"], key=lambda post: post.get("created_at") or "", reverse=True)
    request_summaries = _request_summaries_for_posts(posts)
    response = templates.TemplateResponse(
        request,
        "stream.html",
        {
            "stream": stream,
            "posts": [_stream_post_context(post, request_summaries) for post in posts],
            "messages": _stream_message_context(stream) if web_token_ok(request) else {},
        },
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    _maybe_set_cookie(response, request)
    return response


@app.post("/s/{slug}/note")
async def web_stream_note(request: Request, slug: str):
    if not web_token_ok(request):
        raise HTTPException(status_code=401, detail="missing or invalid token")
    stream = await run_in_threadpool(_web_open_stream_or_404, slug)
    body = await _json_object_body(request)
    target_provider = body.get("target_provider")
    target_session_id = body.get("target_session_id")
    if (target_provider is None) != (target_session_id is None):
        raise HTTPException(status_code=400, detail="target_provider and target_session_id must be supplied together")
    if target_provider is not None:
        provider, session_id = _validate_agent_target(target_provider, target_session_id)
        text = _agent_message_text(body.get("text"))
        client_submission_key = _client_submission_key(body.get("idempotency_key"))
        return await run_in_threadpool(
            _create_targeted_to_agent_message,
            stream,
            text,
            provider,
            session_id,
            client_submission_key,
        )
    text = _bounded_text(body.get("text"), "text", MAX_MESSAGE_TEXT_LENGTH)
    return await run_in_threadpool(_create_to_agent_message, stream, text)


@app.post("/s/{slug}/answer")
async def web_stream_answer(request: Request, slug: str):
    if not web_token_ok(request):
        raise HTTPException(status_code=401, detail="missing or invalid token")
    stream = await run_in_threadpool(_web_open_stream_or_404, slug)
    body = await _json_object_body(request)
    text = _bounded_text(body.get("text"), "text", MAX_MESSAGE_TEXT_LENGTH)
    question_id = _validate_question_id(body.get("question_id"))
    return await run_in_threadpool(_create_answer_message, stream, question_id, text)


@app.get("/r/{req_id}", response_class=HTMLResponse)
def web_request_detail(request: Request, req_id: str):
    if not web_view_ok(request):
        if _is_link_preview_crawler(request):
            r = db.get_request(req_id)
            if r is None:
                raise HTTPException(status_code=404, detail="request not found")
            return _crawler_preview_response(request, r)
        return _login_redirect(request)
    r = db.get_request(req_id)
    if r is None:
        raise HTTPException(status_code=404, detail="request not found")

    context_html = (
        _sanitize_context_html(md_lib.markdown(r["context_md"])) if r.get("context_md") else ""
    )
    stream_read_only = _request_stream_closed(r)
    before_media = _before_media_context(r)
    view_entry = _view_entry_media_path(r)
    # Terminal views fall through to the Portal page so the lifecycle banner
    # (successor link / close reason) is reachable instead of the stale producer HTML.
    if view_entry is not None and r["status"] not in db.TERMINAL_STATUSES:
        # A view owns the whole tab. Operators receive a scoped verdict URL;
        # anonymous viewers receive a plain media URL with no write authority.
        response = RedirectResponse(url=_view_entry_url(request, r["id"], view_entry), status_code=303)
        _maybe_set_cookie(response, request)
        return response
    back = {"href": "/", "label": "Home"}
    if r.get("stream_id"):
        stream = db.get_stream_by_id(r["stream_id"])
        if stream is not None:
            back = {"href": f"/s/{quote(stream['slug'], safe='')}", "label": stream["title"] or stream["slug"]}

    _augment_variant_loops(r)
    response = templates.TemplateResponse(
        request,
        "request.html",
        {
            "r": r,
            "context_html": context_html,
            "stream_read_only": stream_read_only,
            "before_media": before_media,
            "view_entry_url": _view_entry_url(request, r["id"], view_entry) if view_entry else None,
            "back": back,
            "feedback_html": _feedback_html(r),
            "og": _og_context(request, r),
        },
    )
    _apply_request_page_csp(response)
    _maybe_set_cookie(response, request)
    return response


CRAWLER_UA_RE = re.compile(
    r"whatsapp|facebookexternalhit|twitterbot|slackbot|telegrambot|discordbot|linkedinbot|imessage",
    re.IGNORECASE,
)


def _is_link_preview_crawler(request: Request) -> bool:
    return bool(CRAWLER_UA_RE.search(request.headers.get("user-agent", "")))


def _public_base(request: Request) -> str:
    base = str(request.base_url).rstrip("/")
    if request.headers.get("x-forwarded-proto") == "https" and base.startswith("http:"):
        base = "https:" + base[5:]
    return base


def _first_image_url(request: Request, r: dict) -> str | None:
    """Tokenless preview-image URL (served by the public /og route)."""
    for v in r.get("variants", []):
        if v.get("media_type") != "video":
            return f"{_public_base(request)}/og/{r['id']}"
    return None


def _crawler_preview_response(request: Request, r: dict, fallbacks: list[dict] | None = None) -> HTMLResponse:
    """Meta-tags-only page for link-preview crawlers: no auth, no content
    beyond title/ask/first image, so chats can render a preview card."""
    og = _og_context(request, r, fallbacks)
    import html as html_lib
    title = html_lib.escape(og["title"])
    desc = html_lib.escape(og.get("description") or "")
    image = og.get("image")
    tags = [
        '<meta property="og:type" content="website">',
        f'<meta property="og:title" content="{title}">',
    ]
    if desc:
        tags.append(f'<meta property="og:description" content="{desc}">')
    if image:
        tags.append(f'<meta property="og:image" content="{image}">')
        tags.append('<meta name="twitter:card" content="summary_large_image">')
    body = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title>{''.join(tags)}</head>"
        f"<body>{title}</body></html>"
    )
    return HTMLResponse(body)


def _game_og_context(request: Request, game: dict) -> dict:
    base = _public_base(request)
    slug = quote(game["slug"], safe="")
    latest = game["builds"][0] if game.get("builds") else None
    image_path = None
    if latest is not None:
        image_path = config.games_dir() / game["slug"] / latest["version"] / latest[GAME_PREVIEW_FIELD]
    return {
        "title": f'{game["title"]} — {latest["version"]}' if latest else game["title"],
        "description": game.get("description") or "",
        "url": f"{base}/games/{slug}",
        "image": f"{base}/og/games/{slug}" if image_path is not None and image_path.is_file() else None,
        "image_type": "image/jpeg",
        "image_width": 1200,
        "image_height": 630,
        "image_alt": f'{game["title"]} gameplay preview',
        "video": f"{base}/og/games/{slug}/video" if latest is not None else None,
        "video_type": "video/mp4",
    }


def _game_crawler_preview_response(request: Request, game: dict) -> HTMLResponse:
    og = _game_og_context(request, game)
    title = html_lib.escape(og["title"])
    description = html_lib.escape(og["description"])
    tags = [
        '<meta property="og:type" content="video.other">',
        f'<meta property="og:title" content="{title}">',
        f'<meta property="og:url" content="{html_lib.escape(og["url"])}">',
    ]
    if description:
        tags.append(f'<meta property="og:description" content="{description}">')
    if og.get("image"):
        tags.extend([
            f'<meta property="og:image" content="{html_lib.escape(og["image"])}">',
            '<meta property="og:image:type" content="image/jpeg">',
            '<meta property="og:image:width" content="1200">',
            '<meta property="og:image:height" content="630">',
            f'<meta property="og:image:alt" content="{html_lib.escape(og["image_alt"])}">',
        ])
    if og.get("video"):
        video = html_lib.escape(og["video"])
        tags.extend([
            f'<meta property="og:video" content="{video}">',
            f'<meta property="og:video:secure_url" content="{video}">',
            '<meta property="og:video:type" content="video/mp4">',
        ])
    body = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title>{''.join(tags)}</head><body>{title}</body></html>"
    )
    return HTMLResponse(body, headers={"Cache-Control": "public, max-age=300"})


def _latest_game_release_path(slug: str, filename: str | None = None) -> tuple[dict, Path]:
    if not STREAM_SLUG_RE.fullmatch(slug):
        raise HTTPException(status_code=404, detail="not found")
    build = db.get_latest_game_build(slug)
    if build is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        path = _resolve_game_release_path(
            slug,
            build["version"],
            filename or build[GAME_VIDEO_FIELD],
        )
    except HTTPException as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
    return build, path


@app.get("/og/games/{slug}")
def get_game_og_image(slug: str):
    build, _ = _latest_game_release_path(slug)
    path = _resolve_game_release_path(slug, build["version"], build[GAME_PREVIEW_FIELD])
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "public, max-age=3600"},
    )


@app.get("/og/games/{slug}/video")
def get_game_og_video(slug: str):
    _, path = _latest_game_release_path(slug)
    return FileResponse(
        path,
        media_type=mimetypes.guess_type(path.name)[0] or "video/mp4",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "public, max-age=3600"},
    )


@app.get("/og/{req_id}")
def get_og_image(req_id: str):
    """Public (tokenless) preview image: the request's FIRST image variant
    only, for link-preview crawlers that fetch og:image without cookies."""
    if not SAFE_SEGMENT_RE.fullmatch(req_id) or req_id in {".", ".."}:
        raise HTTPException(status_code=404, detail="not found")
    r = db.get_request(req_id)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    for v in r.get("variants", []):
        if v.get("media_type") != "video":
            media_root = config.media_dir().resolve()
            path = (media_root / req_id / v["media_path"]).resolve()
            try:
                path.relative_to(media_root)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail="not found") from exc
            if not path.is_file():
                break
            media_type, _ = mimetypes.guess_type(str(path))
            return FileResponse(
                path,
                media_type=media_type or "application/octet-stream",
                headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "public, max-age=3600"},
            )
    raise HTTPException(status_code=404, detail="not found")


def _og_context(request: Request, r: dict, fallbacks: list[dict] | None = None) -> dict:
    """Open Graph card for link previews (WhatsApp/iMessage/Slack).

    Uses the first image variant as og:image. The crawler fetches without
    cookies, so the token from the shared URL is forwarded on the image URL.
    """
    image = _first_image_url(request, r)
    if image is None:
        # Video-only version: fall back to the newest earlier version that has
        # an image, so chat previews always show something skimmable.
        for other in reversed(fallbacks or []):
            image = _first_image_url(request, other)
            if image:
                break
    return {
        "title": r["title"],
        "description": r.get("ask") or r.get("purpose") or "",
        "image": image,
    }


def _feedback_html(r: dict) -> str:
    return _sanitize_context_html(md_lib.markdown(r["feedback_md"])) if r.get("feedback_md") else ""


def _apply_request_page_csp(response) -> None:
    # Defense in depth: even if a sanitizer gap let markup through, this CSP
    # blocks inline/injected script and non-self resources. The Portal page
    # only loads same-origin /static assets and /media, so 'self' suffices.
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; media-src 'self'; connect-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )


@app.get("/c/{req_id}", response_class=HTMLResponse)
def web_request_chain(request: Request, req_id: str):
    """Permanent chain view: one tab per version, defaulting to the latest.

    Any request id in the chain resolves to the same page, so links stay
    valid as new versions supersede old ones.
    """
    if not web_view_ok(request):
        if _is_link_preview_crawler(request):
            try:
                chain = db.request_chain(req_id)
            except db.RequestNotFoundError:
                raise HTTPException(status_code=404, detail="request not found")
            return _crawler_preview_response(request, chain[-1], chain)
        return _login_redirect(request)
    try:
        chain = db.request_chain(req_id)
    except db.RequestNotFoundError:
        raise HTTPException(status_code=404, detail="request not found")

    v = request.query_params.get("v", "")
    chain_idx = int(v) if v.isdigit() and 1 <= int(v) <= len(chain) else len(chain)
    r = chain[chain_idx - 1]

    context_html = (
        _sanitize_context_html(md_lib.markdown(r["context_md"])) if r.get("context_md") else ""
    )
    back = {"href": "/", "label": "Home"}
    if r.get("stream_id"):
        stream = db.get_stream_by_id(r["stream_id"])
        if stream is not None:
            back = {"href": f"/s/{quote(stream['slug'], safe='')}", "label": stream["title"] or stream["slug"]}

    _augment_variant_loops(r)
    prev = chain[chain_idx - 2] if chain_idx > 1 else None
    if prev is not None:
        _augment_variant_loops(prev)
    response = templates.TemplateResponse(
        request,
        "chain.html",
        {
            "r": r,
            "prev": prev,
            "chain": chain,
            "chain_idx": chain_idx,
            "view_entry_url": (
                _view_entry_url(request, r["id"], _view_entry_media_path(r))
                if _view_entry_media_path(r)
                else None
            ),
            "context_html": context_html,
            "stream_read_only": _request_stream_closed(r),
            "before_media": _before_media_context(r),
            "back": back,
            "feedback_html": _feedback_html(r),
            "og": _og_context(request, r, chain),
        },
    )
    _apply_request_page_csp(response)
    _maybe_set_cookie(response, request)
    return response


@app.options("/r/{req_id}/decide")
def web_decide_options(request: Request, req_id: str):
    if not _view_verdict_capability_ok(req_id, request.query_params.get(VIEW_CAPABILITY_PARAM)):
        raise HTTPException(status_code=401, detail="missing or invalid view capability")
    return Response(status_code=204, headers=_view_cors_headers())


@app.post("/r/{req_id}/decide")
async def web_decide(request: Request, req_id: str):
    """Accept a human cookie or one request-scoped producer capability."""
    view_capability_ok = _view_verdict_capability_ok(
        req_id,
        request.query_params.get(VIEW_CAPABILITY_PARAM),
    )
    operator_ok = web_token_ok(request)
    if not operator_ok and not view_capability_ok:
        raise HTTPException(status_code=401, detail="missing or invalid token")
    body = await request.json()
    result = _apply_verdict(req_id, body, allow_revision=operator_ok)
    if view_capability_ok:
        return JSONResponse(result, headers=_view_cors_headers())
    return result


# --- journey web page ---


def _journey_media_context(ref: dict) -> dict | None:
    owner_id = ref.get("owner_id")
    filename = ref.get("filename")
    if not isinstance(owner_id, str) or not isinstance(filename, str):
        return None
    if not SAFE_SEGMENT_RE.fullmatch(owner_id) or owner_id in {".", ".."} or not _safe_media_filename(filename):
        return None
    # Embed only what get_media serves inline (browser-safe). Everything else —
    # html, svg, pdf, unknown — is served as attachment/sandboxed, so embedding
    # it would render a broken tag; the template links it instead.
    mime = mimetypes.guess_type(filename)[0] or ""
    if mime.startswith("video/"):
        media_type = "video"
    elif mime.startswith("image/") and mime != "image/svg+xml":
        media_type = "image"
    else:
        media_type = "link"
    embed = media_type in {"video", "image"}
    caption = ref.get("caption") if isinstance(ref.get("caption"), str) else None
    return {
        "url": _media_url(owner_id, filename),
        "media_type": media_type,
        "embed": embed,
        # For link-type media the caption already IS the visible link label,
        # so passing it through again would render the same text twice.
        "caption": caption if embed else None,
        "label": caption or filename,
    }


def _journey_request_context(request_id: str, status_map: dict[str, dict]) -> dict:
    row = status_map.get(request_id)
    status = row.get("status") if row else None
    return {
        "request_id": request_id,
        "href": f"/r/{quote(request_id, safe='')}",
        "exists": row is not None,
        "status": status,
        "title": (row.get("title") if row else None) or request_id,
    }


def _journey_step_context(step: dict, status_map: dict[str, dict]) -> dict:
    media = []
    raw_media = step.get("media")
    for ref in raw_media if isinstance(raw_media, list) else []:
        if isinstance(ref, dict):
            resolved = _journey_media_context(ref)
            if resolved is not None:
                media.append(resolved)
    request_id = step.get("request_id")
    request_ctx = None
    if isinstance(request_id, str) and request_id:
        request_ctx = _journey_request_context(request_id, status_map)
    summary = step.get("summary") if isinstance(step.get("summary"), str) else None
    return {
        "title": step.get("title") or "Untitled step",
        "summary": summary,
        # Summaries are authored as markdown; render them the same way game
        # changelogs are, so lists and emphasis survive instead of showing raw.
        "summary_html": _sanitize_context_html(md_lib.markdown(summary)) if summary else None,
        "media": media,
        "request": request_ctx,
    }


@app.get("/g/{slug}", response_class=HTMLResponse)
def web_journey_detail(request: Request, slug: str):
    if not web_view_ok(request):
        return _login_redirect(request)
    _validate_slug(slug)
    journey = db.get_journey(slug)
    if journey is None:
        raise HTTPException(status_code=404, detail="journey not found")
    doc = journey.get("doc") if isinstance(journey.get("doc"), dict) else {}
    raw_steps = doc.get("steps")
    raw_steps = [step for step in raw_steps if isinstance(step, dict)] if isinstance(raw_steps, list) else []
    status_map = _request_status_map([step.get("request_id") for step in raw_steps])
    steps = [_journey_step_context(step, status_map) for step in raw_steps]
    response = templates.TemplateResponse(
        request,
        "journey.html",
        {"journey": journey, "steps": steps, "subtitle": doc.get("subtitle")},
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    _maybe_set_cookie(response, request)
    return response


def _is_ftd_editor_referrer(request: Request) -> bool:
    referrer = request.headers.get("referer")
    if not referrer:
        return False
    parsed = urlsplit(referrer)
    return parsed.path.startswith("/tools/ftd-editor/")


async def _proxy_legacy_ftd_request(request: Request, editor_path: str) -> Response:
    if not web_token_ok(request) or not _is_ftd_editor_referrer(request):
        raise HTTPException(status_code=404, detail="route not found")
    backend_url, _ = _ftd_editor_config()
    forwarded = {}
    content_type = request.headers.get("content-type")
    if content_type:
        forwarded["content-type"] = content_type
    if _is_ftd_editor_sse_path(editor_path):
        return await _stream_ftd_editor_response(request, backend_url, editor_path, forwarded)
    status, response_headers, payload = await run_in_threadpool(
        _proxy_ftd_editor,
        backend_url,
        request.method,
        editor_path,
        request.url.query,
        await request.body(),
        forwarded,
    )
    return Response(
        payload,
        status_code=status,
        media_type=response_headers.get("Content-Type"),
    )


@app.api_route(
    "/api/{editor_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def legacy_ftd_api_proxy(request: Request, editor_path: str):
    return await _proxy_legacy_ftd_request(request, f"api/{editor_path}")


@app.get("/levels/{asset_path:path}")
async def legacy_ftd_level_asset(request: Request, asset_path: str):
    return await _proxy_legacy_ftd_request(request, f"levels/{asset_path}")


@app.get("/public-levels/{asset_path:path}")
async def legacy_ftd_public_level_asset(request: Request, asset_path: str):
    return await _proxy_legacy_ftd_request(request, f"public-levels/{asset_path}")
