"""Login page: passphrase form replaces raw 401s on the web UI."""


def test_unauthenticated_pages_redirect_to_login(client):
    for path in ["/", "/editor-hub", "/s/some-stream", "/r/req_none"]:
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 303, path
        assert resp.headers["location"].startswith("/login?next="), path


def test_login_page_renders_without_auth(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Passphrase" in resp.text


def test_login_with_correct_passphrase_sets_cookie_and_redirects(client, token):
    resp = client.post("/login", data={"password": token, "next": "/"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert "gallery_token" in resp.cookies

    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200


def test_http_login_cookie_stays_usable_for_local_development(client, token):
    resp = client.post("/login", data={"password": token}, follow_redirects=False)

    assert "Secure" not in resp.headers["set-cookie"]


def test_https_proxy_login_cookie_is_secure(client, token):
    resp = client.post(
        "/login",
        data={"password": token},
        headers={"x-forwarded-proto": "https"},
        follow_redirects=False,
    )

    assert "Secure" in resp.headers["set-cookie"]


def test_direct_https_login_cookie_is_secure(client, token):
    resp = client.post(
        "https://testserver/login",
        data={"password": token},
        follow_redirects=False,
    )

    assert "Secure" in resp.headers["set-cookie"]


def test_https_proxy_query_token_cookie_is_secure(client, token):
    resp = client.get(
        f"/?token={token}",
        headers={"x-forwarded-proto": "https"},
        follow_redirects=False,
    )

    assert "Secure" in resp.headers["set-cookie"]


def test_login_with_wrong_passphrase_rejected(client):
    resp = client.post("/login", data={"password": "nope", "next": "/"}, follow_redirects=False)
    assert resp.status_code == 401
    assert "Wrong passphrase" in resp.text
    assert "gallery_token" not in resp.cookies


def test_login_next_open_redirect_blocked(client, token):
    resp = client.post("/login", data={"password": token, "next": "//evil.example"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_authed_login_visit_redirects_home(client, token):
    client.post("/login", data={"password": token, "next": "/"}, follow_redirects=False)
    resp = client.get("/login", follow_redirects=False)
    assert resp.status_code == 303


def test_api_still_requires_bearer_token(client):
    resp = client.get("/api/requests", follow_redirects=False)
    assert resp.status_code == 401


def test_login_with_config_passphrase_sets_token_cookie(client, token):
    from gallery import config

    cfg = config.load_config()
    cfg["passphrase"] = "base"
    config.save_config(cfg)

    resp = client.post("/login", data={"password": "base", "next": "/"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.cookies["gallery_token"] == token

    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200


def test_empty_passphrase_config_does_not_allow_empty_password(client):
    resp = client.post("/login", data={"password": "", "next": "/"}, follow_redirects=False)
    assert resp.status_code == 401
