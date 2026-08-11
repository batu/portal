from __future__ import annotations

import hashlib
import io
import json
import tarfile

import pytest

from gallery import config
from gallery import server


def _write_artifact(data_dir, *, mutate_manifest: bool = False, extra: tuple[str, bytes] | None = None):
    files = {
        "index.html": b'<script type="module" src="./assets/app.js"></script>',
        "assets/app.js": b'document.body.dataset.editor = "ready"',
    }
    assets = [
        {"path": path, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        for path, payload in sorted(files.items())
    ]
    aggregate = json.dumps({"basePath": "./", "assets": assets}, separators=(",", ":")).encode()
    content_hash = hashlib.sha256(aggregate).hexdigest()
    manifest = {
        "manifestVersion": 1,
        "version": "0.1.0",
        "basePath": "./",
        "contentHash": "0" * 64 if mutate_manifest else content_hash,
        "assets": assets,
    }
    relative = f"marble-run/difficulty-editor/archives/{content_hash}.tar.gz"
    archive = data_dir / "games" / relative
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as bundle:
        for path, payload in {**files, "build-manifest.json": json.dumps(manifest).encode()}.items():
            info = tarfile.TarInfo(path)
            info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))
        if extra is not None:
            info = tarfile.TarInfo(extra[0])
            info.size = len(extra[1])
            bundle.addfile(info, io.BytesIO(extra[1]))
    return relative, content_hash


def _configure(data_dir, relative: str, content_hash: str):
    cfg = data_dir[1]
    cfg["marble_run_difficulty_editor"] = {
        "archive_path": relative,
        "content_hash": content_hash,
    }
    config.save_config(cfg)
    server._difficulty_editor_root_cache.clear()


def test_gateway_requires_portal_login(client):
    response = client.get("/tools/marble-run-difficulty/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/tools/marble-run-difficulty/"


def test_gateway_serves_exact_verified_artifact(client, data_dir, token):
    relative, content_hash = _write_artifact(data_dir[0])
    _configure(data_dir, relative, content_hash)

    index = client.get("/tools/marble-run-difficulty/", cookies={"gallery_token": token})
    asset = client.get("/tools/marble-run-difficulty/assets/app.js", cookies={"gallery_token": token})

    assert index.status_code == 200
    assert './assets/app.js' in index.text
    assert index.headers["cache-control"] == "no-cache"
    assert asset.status_code == 200
    assert 'dataset.editor = "ready"' in asset.text
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert token not in asset.text
    extracted = data_dir[0] / "games" / "marble-run" / "difficulty-editor" / "artifacts" / content_hash
    assert (extracted / "build-manifest.json").is_file()


@pytest.mark.parametrize("failure", ["wrong-hash", "malformed-manifest", "undeclared-file", "missing-archive"])
def test_gateway_fails_closed_for_invalid_artifact(client, data_dir, token, failure):
    relative, content_hash = _write_artifact(
        data_dir[0],
        mutate_manifest=failure == "malformed-manifest",
        extra=("surprise.js", b"no") if failure == "undeclared-file" else None,
    )
    if failure == "wrong-hash":
        content_hash = "f" * 64
    if failure == "missing-archive":
        relative = "marble-run/difficulty-editor/archives/missing.tar.gz"
    _configure(data_dir, relative, content_hash)

    response = client.get("/tools/marble-run-difficulty/", cookies={"gallery_token": token})

    assert response.status_code == 503


def test_gateway_rejects_traversal_and_unknown_assets(client, data_dir, token):
    relative, content_hash = _write_artifact(data_dir[0])
    _configure(data_dir, relative, content_hash)

    escaped = client.get(
        "/tools/marble-run-difficulty/assets/%2e%2e/build-manifest.json",
        cookies={"gallery_token": token},
    )
    unknown = client.get(
        "/tools/marble-run-difficulty/assets/missing.js",
        cookies={"gallery_token": token},
    )

    assert escaped.status_code == 404
    assert unknown.status_code == 404


def test_nav_only_exposes_configured_editor(client, data_dir, token):
    before = client.get("/", cookies={"gallery_token": token})
    assert "Marble Run Difficulty" not in before.text
    relative, content_hash = _write_artifact(data_dir[0])
    _configure(data_dir, relative, content_hash)

    after = client.get("/", cookies={"gallery_token": token})
    assert "/tools/marble-run-difficulty/" in after.text
