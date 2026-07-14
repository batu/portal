import logging

import pytest

from gallery import config, server  # noqa: F401 - importing installs the access-log redaction filter


@pytest.mark.parametrize(
    ("key", "logged_key"),
    [
        ("token", "token"),
        ("access_token", "access_token"),
        ("api_key", "api_key"),
        ("key", "key"),
        ("password", "password"),
        ("to%6ben", "to%6ben"),
        ("ok=1;token", "token"),
    ],
)
def test_uvicorn_access_log_redacts_query_secrets(caplog, key, logged_key):
    secret = "do-not-log-this-token"
    logger = logging.getLogger("uvicorn.access")

    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:1",
            "GET",
            f"/editor-hub?{key}={secret}&preview=marble",
            "1.1",
            200,
        )

    assert secret not in caplog.text
    assert f"{logged_key}=%5BREDACTED%5D" in caplog.text
    assert "preview=marble" in caplog.text


def test_editor_hub_defaults_to_two_disabled_marble_placeholders(client, token):
    client.cookies.set("gallery_token", token)

    response = client.get("/editor-hub")

    assert response.status_code == 200
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "Marble GrapesJS Editor" in response.text
    assert "Marble Phaser Editor" in response.text
    assert response.text.count("Waiting for Fabrika links") == 2
    for label in ["Revision Preview", "Baseline", "Reset", "References", "Evidence", "Apply request"]:
        assert label in response.text
    assert "editor-service-link" not in response.text


def test_editor_hub_keeps_placeholders_when_config_has_no_valid_entries(client, token):
    cfg = config.load_config()
    cfg["editor_hub"] = [None, "not-an-entry", 42]
    config.save_config(cfg)
    client.cookies.set("gallery_token", token)

    response = client.get("/editor-hub")

    assert response.status_code == 200
    assert "Marble GrapesJS Editor" in response.text
    assert "Marble Phaser Editor" in response.text
    assert response.text.count("Waiting for Fabrika links") == 2


def test_editor_hub_keeps_missing_marble_entry_as_a_placeholder(client, token):
    cfg = config.load_config()
    cfg["editor_hub"] = [
        {
            "id": "marble-grapesjs",
            "editor_url": "https://editor.example/marble",
            "preview_url": "https://preview.example/marble/revision/1",
            "status": "ready",
        }
    ]
    config.save_config(cfg)
    client.cookies.set("gallery_token", token)

    response = client.get("/editor-hub")

    assert response.status_code == 200
    assert "Marble GrapesJS Editor" in response.text
    assert "Marble Phaser Editor" in response.text
    assert response.text.count("Waiting for Fabrika links") == 1
    assert "https://editor.example/marble" in response.text


def test_editor_hub_sanitizes_and_hardens_external_links(client, token):
    cfg = config.load_config()
    cfg["editor_hub"] = [
        {
            "id": "marble-grapesjs",
            "name": "<script>Marble</script>",
            "status": "ready",
            "editor_url": "javascript:alert(1)",
            "preview_url": "https://preview.example/revision/42",
            "reference_links": [
                {"label": "Reference <one>", "url": "https://docs.example/reference"},
                {"label": "Unsafe", "url": "data:text/html,bad"},
                {"label": "Credentials", "url": "https://user:secret@docs.example/private"},
            ],
            "evidence_links": [{"label": "Evidence", "url": "http://evidence.example/report"}],
            "baseline": "Marble baseline v1",
            "reset": "Use the editor's Reset to baseline action.",
            "apply_request": {"status": "queued", "summary": "Apply revision 42"},
        }
    ]
    config.save_config(cfg)
    client.cookies.set("gallery_token", token)

    response = client.get("/editor-hub")

    assert response.status_code == 200
    assert "<script>Marble</script>" not in response.text
    assert "&lt;script&gt;Marble&lt;/script&gt;" in response.text
    assert "javascript:" not in response.text
    assert "data:text" not in response.text
    assert "user:secret" not in response.text
    assert "https://preview.example/revision/42" in response.text
    assert "https://docs.example/reference" in response.text
    assert "http://evidence.example/report" in response.text
    assert response.text.count('target="_blank"') == 3
    assert response.text.count('rel="noopener noreferrer"') == 3
    assert "Marble baseline v1" in response.text
    assert "Use the editor&#39;s Reset to baseline action." in response.text
    assert "queued" in response.text
    assert "Apply revision 42" in response.text


@pytest.mark.parametrize(
    "secret_key",
    ["token", "access_token", "api_key", "key", "password", "to%6ben", "ok=1;token"],
)
def test_editor_hub_rejects_links_with_query_credentials(client, token, secret_key):
    cfg = config.load_config()
    cfg["editor_hub"] = [
        {
            "id": "marble-grapesjs",
            "name": "Marble editor",
            "editor_url": f"https://editor.example/project?{secret_key}=do-not-handoff",
            "preview_url": f"https://preview.example/revision?{secret_key}=do-not-handoff",
            "reference_links": [
                {
                    "label": "Unsafe reference",
                    "url": f"https://docs.example/reference?{secret_key}=do-not-handoff",
                }
            ],
        }
    ]
    config.save_config(cfg)
    client.cookies.set("gallery_token", token)

    response = client.get("/editor-hub")

    assert response.status_code == 200
    assert "do-not-handoff" not in response.text
    assert "editor-service-link" not in response.text
