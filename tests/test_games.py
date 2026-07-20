import hashlib
import io
import zipfile

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
            "poster": ("preview.jpg", b"poster-data", "image/jpeg"),
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
    assert (config.games_dir() / "marble-run" / "1.0.0" / "preview.jpg").read_bytes() == b"poster-data"

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
            "poster": ("preview.jpg", b"z", "image/jpeg"),
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
            "poster": ("preview.jpg", b"z", "image/jpeg"),
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
    assert 'data-src="/games/marble-run/builds/1.0.0/public-video?rev=' in page.text
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
            "poster": ("preview.jpg", b"poster", "image/jpeg"),
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
            "poster": ("../preview final.jpg", b"poster", "image/jpeg"),
        },
    )
    assert response.status_code == 200
    build = response.json()
    assert build["artifact_path"] == "outside_build.zip"
    assert build["video_path"] == "capture_final.mp4"
    assert build["preview_path"] == "preview_final.jpg"
    release_dir = config.games_dir() / "marble-run" / "1.0.0"
    assert (release_dir / build["artifact_path"]).read_bytes() == b"build"
    assert (release_dir / build["video_path"]).read_bytes() == b"video"
    assert (release_dir / build["preview_path"]).read_bytes() == b"poster"
    assert not (config.games_dir() / "outside build.zip").exists()


def test_changelog_correction_and_recoverable_release_removal(client, token):
    assert publish(client, token).status_code == 200

    updated = client.post(
        "/api/games/marble-run/builds/1.0.0/changelog",
        headers=auth_headers(token),
        json={"changelog": "- Correct release delta"},
    )
    assert updated.status_code == 200
    assert updated.json()["changelog_md"] == "- Correct release delta"

    removed = client.delete(
        "/api/games/marble-run/builds/1.0.0",
        headers=auth_headers(token),
    )
    assert removed.status_code == 200
    trash_path = config.data_dir() / removed.json()["recoverable_path"]
    assert (trash_path / "marble-run.apk").read_bytes() == b"build-data"
    assert db.get_game("marble-run") is None
    assert not (config.games_dir() / "marble-run" / "1.0.0").exists()


def test_game_release_management_requires_auth_and_valid_poster(client, token):
    bad_poster = client.post(
        "/api/games/marble-run/builds",
        headers=auth_headers(token),
        data={"title": "Marble Run", "version": "1.0.0", "changelog": "Initial release"},
        files={
            "artifact": ("build.apk", b"build", "application/octet-stream"),
            "video": ("game.mp4", b"video", "video/mp4"),
            "poster": ("preview.png", b"poster", "image/png"),
        },
    )
    assert bad_poster.status_code == 400
    assert publish(client, token).status_code == 200
    assert client.post(
        "/api/games/marble-run/builds/1.0.0/changelog",
        json={"changelog": "changed"},
    ).status_code == 401
    assert client.delete("/api/games/marble-run/builds/1.0.0").status_code == 401


def make_bundle(members, *, root=""):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in members.items():
            archive.writestr(f"{root}{name}", content)
    return buffer.getvalue()


WEB_BUNDLE = {
    "index.html": "<!doctype html><title>Marble Run</title><script src='assets/app.js'></script>",
    "assets/app.js": "console.log('marble')",
}


def publish_with_web(client, token, bundle, *, version="1.0.0"):
    return client.post(
        f"/api/games/marble-run/builds",
        headers=auth_headers(token),
        data={"title": "Marble Run", "version": version, "changelog": "- Playable in the browser"},
        files={
            "artifact": ("marble-run.apk", b"build-data", "application/vnd.android.package-archive"),
            "video": ("gameplay.mp4", b"video-data", "video/mp4"),
            "poster": ("preview.jpg", b"poster-data", "image/jpeg"),
            "web": ("dist.zip", bundle, "application/zip"),
        },
    )


def test_web_bundle_publishes_and_serves_a_sandboxed_playable_preview(client, token):
    response = publish_with_web(client, token, make_bundle(WEB_BUNDLE))
    assert response.status_code == 200
    body = response.json()
    assert body["preview_url"] == "/games/marble-run/builds/1.0.0/play/"
    assert body["web_preview_path"] == "web/index.html"

    entry = client.get("/games/marble-run/builds/1.0.0/play/")
    assert entry.status_code == 200
    assert "Marble Run" in entry.text
    assert "sandbox" in entry.headers["content-security-policy"]
    assert entry.headers["x-content-type-options"] == "nosniff"

    asset = client.get("/games/marble-run/builds/1.0.0/play/assets/app.js")
    assert asset.status_code == 200
    assert asset.content == b"console.log('marble')"
    assert asset.headers["content-type"].startswith("text/javascript") or "javascript" in asset.headers["content-type"]

    page = client.get("/games/marble-run")
    assert 'data-src="/games/marble-run/builds/1.0.0/play/"' in page.text
    assert 'sandbox="allow-scripts"' in page.text
    assert "allow-same-origin" not in page.text
    assert "data-device-preset" in page.text


def test_web_bundle_accepts_a_single_top_level_dist_directory(client, token):
    response = publish_with_web(client, token, make_bundle(WEB_BUNDLE, root="dist/"))
    assert response.status_code == 200
    assert response.json()["web_preview_path"] == "web/dist/index.html"
    assert client.get("/games/marble-run/builds/1.0.0/play/").status_code == 200
    assert client.get("/games/marble-run/builds/1.0.0/play/assets/app.js").status_code == 200


def test_web_bundle_cannot_escape_its_release_directory(client, token):
    escape = publish_with_web(client, token, make_bundle({"index.html": "x", "../evil.txt": "pwn"}))
    assert escape.status_code == 400
    assert not (config.games_dir() / "marble-run" / "evil.txt").exists()
    assert not (config.games_dir() / "evil.txt").exists()
    assert db.get_game("marble-run") is None
    assert not (config.games_dir() / "marble-run" / "1.0.0").exists()

    assert publish_with_web(client, token, make_bundle(WEB_BUNDLE)).status_code == 200
    (config.games_dir() / "marble-run" / "secret.txt").write_text("nope")
    assert client.get("/games/marble-run/builds/1.0.0/play/../secret.txt").status_code == 404
    assert client.get("/games/marble-run/builds/1.0.0/play/%2e%2e/secret.txt").status_code == 404
    assert client.get("/games/marble-run/builds/1.0.0/play/../../../../etc/passwd").status_code == 404


def test_web_bundle_rejects_bombs_unsupported_members_and_missing_entry(client, token):
    too_many = publish_with_web(client, token, make_bundle(
        {"index.html": "x", **{f"assets/f{i}.js": "x" for i in range(2001)}}
    ))
    assert too_many.status_code == 400
    assert "files" in too_many.json()["detail"]

    unsupported = publish_with_web(client, token, make_bundle({"index.html": "x", "run.sh": "rm -rf /"}))
    assert unsupported.status_code == 400
    assert "unsupported" in unsupported.json()["detail"]

    no_entry = publish_with_web(client, token, make_bundle({"main.html": "x"}))
    assert no_entry.status_code == 400
    assert "index.html" in no_entry.json()["detail"]

    not_a_zip = publish_with_web(client, token, b"definitely-not-a-zip")
    assert not_a_zip.status_code == 400
    assert db.get_game("marble-run") is None


def test_releases_without_a_web_bundle_stay_fully_usable(client, token):
    assert publish(client, token).status_code == 200
    build = db.get_game_build("marble-run", "1.0.0")
    assert build["web_preview_path"] == ""

    assert client.get("/games/marble-run/builds/1.0.0/play/").status_code == 404
    assert client.get("/games/marble-run/builds/1.0.0/play/assets/app.js").status_code == 404

    page = client.get("/games/marble-run")
    assert page.status_code == 200
    assert "No browser preview for this build" in page.text
    assert "data-play-surface" not in page.text
    assert 'href="/games/marble-run/builds/1.0.0/public-download"' in page.text


def test_web_preview_is_public_to_read_while_publishing_stays_authenticated(client, token):
    assert publish_with_web(client, token, make_bundle(WEB_BUNDLE)).status_code == 200
    assert client.get("/games/marble-run/builds/1.0.0/play/", follow_redirects=False).status_code == 200
    assert publish_with_web(client, "wrong", make_bundle(WEB_BUNDLE), version="2.0.0").status_code == 401


def test_removing_a_release_takes_its_web_preview_with_it(client, token):
    assert publish_with_web(client, token, make_bundle(WEB_BUNDLE)).status_code == 200
    removed = client.delete("/api/games/marble-run/builds/1.0.0", headers=auth_headers(token))
    assert removed.status_code == 200
    trash_path = config.data_dir() / removed.json()["recoverable_path"]
    assert (trash_path / "web" / "index.html").is_file()
    assert client.get("/games/marble-run/builds/1.0.0/play/").status_code == 404


def test_v10_database_migrates_to_an_empty_web_preview_path(data_dir):
    conn = db.connect()
    conn.execute("PRAGMA user_version = 10")
    conn.execute("ALTER TABLE game_builds DROP COLUMN web_preview_path")
    conn.commit()
    conn.close()
    db._conn = None
    assert "web_preview_path" in db._column_names(db.connect(), "game_builds")

    build = db.create_game_build(
        "marble-run",
        title="Marble Run", description="", version="0.9.0", changelog_md="- Legacy",
        artifact_path="a.apk", artifact_size=1, artifact_sha256="x",
        video_path="v.mp4", preview_path="p.jpg",
    )
    assert build["web_preview_path"] == ""
