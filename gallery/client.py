"""Minimal HTTP client for the gallery CLI. stdlib-only (urllib), no requests dependency."""

import json
import mimetypes
import uuid
import urllib.error
import urllib.request
from pathlib import Path


class GalleryClientError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _request(method: str, url: str, headers: dict, data: bytes | None = None) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
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


def get_json(base_url: str, token: str, path: str) -> dict:
    return _request("GET", base_url + path, _auth_headers(token))


def post_json(base_url: str, token: str, path: str, obj: dict) -> dict:
    headers = _auth_headers(token)
    headers["Content-Type"] = "application/json"
    return _request("POST", base_url + path, headers, json.dumps(obj).encode("utf-8"))


def post_multipart(base_url: str, token: str, path: str, fields: dict, files: list[Path]) -> dict:
    """fields: simple string form fields. files: ordered list of file paths uploaded as 'files'."""
    boundary = uuid.uuid4().hex
    parts = []

    for name, value in fields.items():
        if value is None:
            continue
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")

    for file_path in files:
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="files"; filename="{file_path.name}"\r\n'.encode()
        )
        parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
        parts.append(file_path.read_bytes())
        parts.append(b"\r\n")

    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)

    headers = _auth_headers(token)
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    return _request("POST", base_url + path, headers, body)
