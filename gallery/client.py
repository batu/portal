"""Minimal HTTP client for the gallery CLI. stdlib-only (urllib), no requests dependency."""

import json
import mimetypes
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import cast


class GalleryClientError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _request(method: str, url: str, headers: dict, data: bytes | None = None) -> dict | list:
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
    except ValueError as exc:
        raise GalleryClientError(0, f"invalid URL {url!r}: {exc}") from exc
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except json.JSONDecodeError:
            pass
        raise GalleryClientError(exc.code, detail) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GalleryClientError(0, str(exc)) from exc


def get_json(base_url: str, token: str, path: str) -> dict | list:
    return _request("GET", base_url + path, _auth_headers(token))


def post_json(base_url: str, token: str, path: str, obj: dict) -> dict:
    headers = _auth_headers(token)
    headers["Content-Type"] = "application/json"
    return _request("POST", base_url + path, headers, json.dumps(obj).encode("utf-8"))


def put_json(base_url: str, token: str, path: str, obj: dict) -> dict:
    headers = _auth_headers(token)
    headers["Content-Type"] = "application/json"
    return cast(dict, _request("PUT", base_url + path, headers, json.dumps(obj).encode("utf-8")))


def delete_json(base_url: str, token: str, path: str) -> dict:
    return cast(dict, _request("DELETE", base_url + path, _auth_headers(token)))


def post_multipart(base_url: str, token: str, path: str, fields: dict, files: list) -> dict:
    """fields: simple string form fields. files: Path entries, or (field_name, Path) entries."""
    boundary = uuid.uuid4().hex
    parts = []

    for name, value in fields.items():
        if value is None:
            continue
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")

    for item in files:
        if isinstance(item, tuple):
            field_name, file_path = item
            file_path = Path(file_path)
        else:
            field_name = "files"
            file_path = Path(item)
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{file_path.name}"\r\n'.encode()
        )
        parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
        parts.append(file_path.read_bytes())
        parts.append(b"\r\n")

    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)

    headers = _auth_headers(token)
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    return _request("POST", base_url + path, headers, body)


def close_request(base_url: str, token: str, req_id: str, reason: str) -> dict:
    req_id = urllib.parse.quote(req_id, safe="")
    return post_json(base_url, token, f"/api/requests/{req_id}/close", {"reason": reason})


def get_request(base_url: str, token: str, req_id: str) -> dict:
    req_id = urllib.parse.quote(req_id, safe="")
    return get_json(base_url, token, f"/api/requests/{req_id}")


def set_request_feedback(base_url: str, token: str, req_id: str, feedback: str) -> dict:
    return post_json(base_url, token, f"/api/requests/{req_id}/feedback", {"feedback": feedback})


def supersede_request(base_url: str, token: str, req_id: str, successor: str, feedback: str | None = None) -> dict:
    req_id = urllib.parse.quote(req_id, safe="")
    body: dict = {"successor": successor}
    if feedback is not None:
        body["feedback"] = feedback
    return post_json(base_url, token, f"/api/requests/{req_id}/supersede", body)


def create_stream(base_url: str, token: str, slug: str, kind: str, title: str) -> dict:
    return post_json(base_url, token, "/api/streams", {"slug": slug, "kind": kind, "title": title})


def close_stream(base_url: str, token: str, slug: str) -> dict:
    slug = urllib.parse.quote(slug, safe="")
    return post_json(base_url, token, f"/api/streams/{slug}/close", {})


def get_stream(base_url: str, token: str, slug: str) -> dict:
    slug = urllib.parse.quote(slug, safe="")
    return get_json(base_url, token, f"/api/streams/{slug}")


def create_stream_post(
    base_url: str,
    token: str,
    slug: str,
    type: str,
    title: str,
    author: str,
    body: dict | None = None,
    files: list[Path] | None = None,
) -> dict:
    slug = urllib.parse.quote(slug, safe="")
    fields = {
        "type": type,
        "title": title,
        "author": author,
        "body": json.dumps(body) if body is not None else None,
    }
    return post_multipart(base_url, token, f"/api/streams/{slug}/posts", fields, files or [])


def get_stream_post(base_url: str, token: str, slug: str, post_id: str) -> dict:
    slug = urllib.parse.quote(slug, safe="")
    post_id = urllib.parse.quote(post_id, safe="")
    return get_json(base_url, token, f"/api/streams/{slug}/posts/{post_id}")


def create_stream_message(base_url: str, token: str, slug: str, direction: str, text: str) -> dict:
    slug = urllib.parse.quote(slug, safe="")
    return post_json(base_url, token, f"/api/streams/{slug}/messages", {"direction": direction, "text": text})


def list_stream_messages(
    base_url: str,
    token: str,
    slug: str,
    *,
    since: str | None = None,
    direction: str | None = None,
    unconsumed: bool = False,
) -> list[dict]:
    slug = urllib.parse.quote(slug, safe="")
    params = {}
    if since is not None:
        params["since"] = since
    if direction is not None:
        params["direction"] = direction
    if unconsumed:
        params["unconsumed"] = "1"
    query = urllib.parse.urlencode(params)
    path = f"/api/streams/{slug}/messages"
    if query:
        path = f"{path}?{query}"
    return cast(list[dict], get_json(base_url, token, path))


def consume_message(base_url: str, token: str, message_id: str) -> dict:
    message_id = urllib.parse.quote(message_id, safe="")
    return post_json(base_url, token, f"/api/messages/{message_id}/consume", {})


def upsert_journey(base_url: str, token: str, slug: str, title: str, doc: dict) -> dict:
    slug = urllib.parse.quote(slug, safe="")
    # The explicit title argument wins over any "title" key riding in the doc.
    return put_json(base_url, token, f"/api/journeys/{slug}", {**doc, "title": title})


def get_journey(base_url: str, token: str, slug: str) -> dict:
    slug = urllib.parse.quote(slug, safe="")
    return cast(dict, get_json(base_url, token, f"/api/journeys/{slug}"))


def list_journeys(base_url: str, token: str) -> list[dict]:
    return cast(list[dict], get_json(base_url, token, "/api/journeys"))


def publish_game_build(
    base_url: str,
    token: str,
    slug: str,
    *,
    title: str,
    version: str,
    changelog: str,
    artifact: Path,
    video: Path,
    poster: Path,
    description: str = "",
) -> dict:
    slug = urllib.parse.quote(slug, safe="")
    fields = {
        "title": title,
        "version": version,
        "changelog": changelog,
        "description": description,
    }
    return post_multipart(
        base_url,
        token,
        f"/api/games/{slug}/builds",
        fields,
        [("artifact", artifact), ("video", video), ("poster", poster)],
    )


def update_game_changelog(base_url: str, token: str, slug: str, version: str, changelog: str) -> dict:
    slug = urllib.parse.quote(slug, safe="")
    version = urllib.parse.quote(version, safe="")
    return post_json(base_url, token, f"/api/games/{slug}/builds/{version}/changelog", {"changelog": changelog})


def remove_game_build(base_url: str, token: str, slug: str, version: str) -> dict:
    slug = urllib.parse.quote(slug, safe="")
    version = urllib.parse.quote(version, safe="")
    return delete_json(base_url, token, f"/api/games/{slug}/builds/{version}")
