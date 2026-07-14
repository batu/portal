import logging

import pytest

from gallery import config


@pytest.mark.parametrize("key", ["token", "access_token", "api_key", "key", "password"])
def test_uvicorn_access_log_redacts_query_secrets(caplog, key):
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
    assert f"{key}=%5BREDACTED%5D" in caplog.text
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


def test_editor_hub_sanitizes_and_hardens_external_links(client, token):
    cfg = config.load_config()
    cfg["editor_hub"] = [
        {
            "id": "marble-grapesjs",
            "name": "<script>Marble</script>",
            "status": "ready",
            "editor_url": "javascript:alert(1)",
            "preview_url": "https://preview.example/revision/42?token=public-value",
            "reference_links": [
                {"label": "Reference <one>", "url": "https://docs.example/reference"},
                {"label": "Unsafe", "url": "data:text/html,bad"},
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
    assert "https://preview.example/revision/42?token=public-value" in response.text
    assert "https://docs.example/reference" in response.text
    assert "http://evidence.example/report" in response.text
    assert response.text.count('target="_blank"') == 3
    assert response.text.count('rel="noopener noreferrer"') == 3
    assert "Marble baseline v1" in response.text
    assert "Use the editor&#39;s Reset to baseline action." in response.text
    assert "queued" in response.text
    assert "Apply revision 42" in response.text
