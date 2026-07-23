from __future__ import annotations

from gallery import config
from gallery import server


def _configure(data_dir, ui_root):
    cfg = data_dir[1]
    cfg["ftd_editor"] = {
        "backend_url": "http://127.0.0.1:5192",
        "ui_root": str(ui_root),
    }
    config.save_config(cfg)


def test_ftd_editor_requires_portal_login(client):
    response = client.get("/tools/ftd-editor/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/tools/ftd-editor/"


def test_ftd_editor_serves_only_configured_ui_files(client, data_dir, token, tmp_path):
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<h1>FTD editor</h1>")
    (ui / "assets" / "app.js").write_text("window.editor = true")
    _configure(data_dir, ui)

    index = client.get("/tools/ftd-editor/", cookies={"gallery_token": token})
    asset = client.get(
        "/tools/ftd-editor/assets/app.js",
        cookies={"gallery_token": token},
    )
    escaped = client.get(
        "/tools/ftd-editor/assets/../../config.json",
        cookies={"gallery_token": token},
    )

    assert index.status_code == 200
    assert "FTD editor" in index.text
    assert asset.status_code == 200
    assert "window.editor" in asset.text
    assert escaped.status_code == 404


def test_ftd_editor_query_token_bootstraps_cookie_for_relative_assets(
    client, data_dir, token, tmp_path
):
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text('<script src="./assets/app.js"></script>')
    (ui / "assets" / "app.js").write_text("window.editor = true")
    _configure(data_dir, ui)

    index = client.get(f"/tools/ftd-editor/?token={token}")
    assert index.status_code == 200
    assert "gallery_token=" in index.headers["set-cookie"]
    assert client.get("/tools/ftd-editor/assets/app.js").status_code == 200


def test_ftd_editor_proxy_rewrites_authority_without_forwarding_portal_cookie(
    client, data_dir, token, tmp_path, monkeypatch
):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("editor")
    _configure(data_dir, ui)
    observed = {}

    def proxy(backend_url, method, path, query, body, headers):
        observed.update(
            backend_url=backend_url,
            method=method,
            path=path,
            query=query,
            body=body,
            headers=headers,
        )
        return 200, {"Content-Type": "application/json"}, b'{"ok":true}'

    monkeypatch.setattr(server, "_proxy_ftd_editor", proxy)
    response = client.post(
        "/tools/ftd-editor/api/jobs/actions/ftd.background_generate?x=1",
        cookies={"gallery_token": token},
        headers={"X-FTD-Launch-Credential": "launch"},
        json={"requestId": "request-1"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert observed["path"] == "api/jobs/actions/ftd.background_generate"
    assert observed["query"] == "x=1"
    assert observed["headers"]["x-ftd-launch-credential"] == "launch"
    assert "cookie" not in observed["headers"]


def test_copied_v1_editor_root_api_is_scoped_to_authenticated_editor_referrer(
    client, data_dir, token, tmp_path, monkeypatch
):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("editor")
    _configure(data_dir, ui)
    observed = {}

    def proxy(backend_url, method, path, query, body, headers):
        observed["path"] = path
        return 200, {"Content-Type": "application/json"}, b'{"styles":[]}'

    monkeypatch.setattr(server, "_proxy_ftd_editor", proxy)
    allowed = client.get(
        "/api/config",
        cookies={"gallery_token": token},
        headers={"referer": "http://testserver/tools/ftd-editor/"},
    )
    unrelated = client.get(
        "/api/config",
        cookies={"gallery_token": token},
        headers={"referer": "http://testserver/"},
    )

    assert allowed.status_code == 200
    assert observed["path"] == "api/config"
    assert unrelated.status_code == 404
