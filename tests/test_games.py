import hashlib

from gallery import config, db


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def publish(client, token, *, version="1.0.0"):
    return client.post(
        "/api/games/marble-run/builds",
        headers=auth_headers(token),
        data={
            "title": "Marble Run",
            "description": "Guide the marble through handcrafted tracks.",
            "version": version,
            "changelog": "- First downloadable build\n- Gameplay capture included",
        },
        files={
            "artifact": ("marble-run.apk", b"build-data", "application/vnd.android.package-archive"),
            "video": ("gameplay.mp4", b"video-data", "video/mp4"),
        },
    )


def test_fresh_schema_includes_games_and_builds(data_dir):
    conn = db.connect()
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"games", "game_builds"} <= tables


def test_publish_persists_immutable_release_files_and_metadata(client, token):
    response = publish(client, token)
    assert response.status_code == 200
    body = response.json()
    assert body["game_url"] == "/games/marble-run"
    assert body["download_url"].endswith("/games/marble-run/builds/1.0.0/public-download")
    assert body["artifact_sha256"] == hashlib.sha256(b"build-data").hexdigest()
    assert (config.games_dir() / "marble-run" / "1.0.0" / "marble-run.apk").read_bytes() == b"build-data"
    assert (config.games_dir() / "marble-run" / "1.0.0" / "gameplay.mp4").read_bytes() == b"video-data"

    duplicate = publish(client, token)
    assert duplicate.status_code == 409
    assert len(db.get_game("marble-run")["builds"]) == 1


def test_publish_requires_auth_changelog_and_video(client, token):
    assert publish(client, "wrong").status_code == 401
    missing_changelog = client.post(
        "/api/games/marble-run/builds",
        headers=auth_headers(token),
        data={"title": "Marble Run", "version": "1.0.0", "changelog": ""},
        files={
            "artifact": ("build.zip", b"x", "application/zip"),
            "video": ("gameplay.mp4", b"y", "video/mp4"),
        },
    )
    assert missing_changelog.status_code == 422

    bad_video = client.post(
        "/api/games/marble-run/builds",
        headers=auth_headers(token),
        data={"title": "Marble Run", "version": "1.0.0", "changelog": "- New"},
        files={
            "artifact": ("build.zip", b"x", "application/zip"),
            "video": ("notes.txt", b"y", "text/plain"),
        },
    )
    assert bad_video.status_code == 400


def test_games_pages_render_video_changelog_and_stable_download(client, token):
    assert publish(client, token, version="1.0.0").status_code == 200
    assert publish(client, token, version="1.1.0").status_code == 200
    page = client.get(f"/games/marble-run?token={token}")
    assert page.status_code == 200
    assert "Marble Run" in page.text
    assert "First downloadable build" in page.text
    assert 'src="/games/marble-run/builds/1.0.0/public-video?rev=' in page.text
    assert 'href="/games/marble-run/builds/1.0.0/public-download"' in page.text
    assert "Download APK · 1.0.0" in page.text
    assert 'role="tablist" aria-label="Build versions"' in page.text
    assert 'data-build-tab="1.1.0"' in page.text
    assert 'data-build-tab="1.0.0"' in page.text
    assert page.text.index('data-build-tab="1.1.0"') < page.text.index('data-build-tab="1.0.0"')
    assert 'data-build-panel="1.0.0"' in page.text

    download = client.get("/games/marble-run/builds/1.0.0/download")
    assert download.status_code == 200
    assert download.content == b"build-data"
    assert "attachment" in download.headers["content-disposition"]
    assert download.headers["cache-control"].endswith("immutable")


def test_game_link_preview_is_public_to_whatsapp_with_image_and_video(client, token):
    assert publish(client, token, version="1.0.0").status_code == 200
    release_dir = config.games_dir() / "marble-run" / "1.0.0"
    (release_dir / "preview.jpg").write_bytes(b"poster-data")

    preview = client.get(
        "/games/marble-run",
        headers={"User-Agent": "WhatsApp/2.26.1"},
        follow_redirects=False,
    )
    assert preview.status_code == 200
    assert '<meta property="og:title" content="Marble Run — 1.0.0">' in preview.text
    assert '<meta property="og:url" content="http://testserver/games/marble-run">' in preview.text
    assert '<meta property="og:image" content="http://testserver/og/games/marble-run">' in preview.text
    assert '<meta property="og:video" content="http://testserver/og/games/marble-run/video">' in preview.text

    image = client.get("/og/games/marble-run")
    assert image.status_code == 200
    assert image.content == b"poster-data"
    assert image.headers["cache-control"].startswith("public")

    video = client.get("/og/games/marble-run/video")
    assert video.status_code == 200
    assert video.content == b"video-data"
    assert video.headers["cache-control"].startswith("public")

    public_video = client.get("/games/marble-run/builds/1.0.0/public-video")
    assert public_video.status_code == 200
    assert public_video.content == b"video-data"

    artifact = client.get("/games/marble-run/builds/1.0.0/public-download")
    assert artifact.status_code == 200
    assert artifact.content == b"build-data"
    assert "attachment" in artifact.headers["content-disposition"]


def test_game_page_and_download_button_are_public_read_only(client, token):
    assert publish(client, token, version="1.0.0").status_code == 200
    page = client.get("/games/marble-run", follow_redirects=False)
    assert page.status_code == 200
    assert 'href="/games/marble-run/builds/1.0.0/public-download"' in page.text


def test_games_library_is_linked_from_index(client, token):
    assert publish(client, token).status_code == 200
    index = client.get(f"/?token={token}")
    library = client.get("/games")
    assert index.status_code == library.status_code == 200
    assert 'href="/games"' in index.text
    assert 'href="/games/marble-run"' in library.text


def test_game_changelog_is_sanitized_before_safe_template_render(client, token):
    response = client.post(
        "/api/games/marble-run/builds",
        headers=auth_headers(token),
        data={
            "title": "Marble Run",
            "version": "1.0.0",
            "changelog": '<script>alert(1)</script><img src="javascript:bad" onerror="alert(2)"> **Safe note**',
        },
        files={
            "artifact": ("build.zip", b"build", "application/zip"),
            "video": ("game.mp4", b"video", "video/mp4"),
        },
    )
    assert response.status_code == 200
    page = client.get(f"/games/marble-run?token={token}")
    assert "<script>alert(1)</script>" not in page.text
    assert "javascript:bad" not in page.text
    assert "onerror" not in page.text
    assert "<strong>Safe note</strong>" in page.text


def test_publish_sanitizes_traversal_shaped_upload_names(client, token):
    response = client.post(
        "/api/games/marble-run/builds",
        headers=auth_headers(token),
        data={"title": "Marble Run", "version": "1.0.0", "changelog": "- Safe paths"},
        files={
            "artifact": ("../../outside build.zip", b"build", "application/zip"),
            "video": ("../capture final.mp4", b"video", "video/mp4"),
        },
    )
    assert response.status_code == 200
    build = response.json()
    assert build["artifact_path"] == "outside_build.zip"
    assert build["video_path"] == "capture_final.mp4"
    release_dir = config.games_dir() / "marble-run" / "1.0.0"
    assert (release_dir / build["artifact_path"]).read_bytes() == b"build"
    assert (release_dir / build["video_path"]).read_bytes() == b"video"
    assert not (config.games_dir() / "outside build.zip").exists()
