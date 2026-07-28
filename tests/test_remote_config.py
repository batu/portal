import json

import pytest

from gallery import config, remote_config


TEMPLATE = {
    "parameters": {
        "ungrouped_flag": {
            "defaultValue": {"value": "true"},
            "description": "Not in a group.",
            "valueType": "BOOLEAN",
        }
    },
    "parameterGroups": {
        "Ads": {
            "description": "Ad gating.",
            "parameters": {
                "interstitial_first_level": {
                    "defaultValue": {"value": "10"},
                    "description": "First level that may show an interstitial.",
                    "valueType": "NUMBER",
                },
                "rewarded_ads_enabled": {
                    "defaultValue": {"value": "true"},
                    "description": "Rewarded master switch.",
                    "valueType": "BOOLEAN",
                },
            },
        },
        "Shop": {
            "description": "Products.",
            "parameters": {
                "no_ads_product_id": {
                    "defaultValue": {"value": "com.example.noads"},
                    "description": "",
                    "valueType": "STRING",
                }
            },
        },
    },
}

ADS_ONLY = {"project": "demo-project", "groups": ["Ads"]}
EVERYTHING = {"project": "demo-project"}


def test_game_settings_reads_config(data_dir):
    _, cfg = data_dir
    assert remote_config.game_settings("marble-run") is None
    cfg["remote_config"] = {"marble-run": {"project": "demo-project"}}
    config.save_config(cfg)
    assert remote_config.game_settings("marble-run")["project"] == "demo-project"


def test_game_settings_ignores_entries_without_a_project(data_dir):
    _, cfg = data_dir
    cfg["remote_config"] = {"marble-run": {"groups": ["Ads"]}}
    config.save_config(cfg)
    assert remote_config.game_settings("marble-run") is None


def test_groups_filter_limits_the_editable_surface():
    keys = [row["key"] for row in remote_config.editable_params(TEMPLATE, ADS_ONLY)]
    assert keys == ["interstitial_first_level", "rewarded_ads_enabled"]


def test_without_a_groups_filter_ungrouped_and_grouped_params_are_editable():
    rows = remote_config.editable_params(TEMPLATE, EVERYTHING)
    assert {row["key"] for row in rows} == {
        "ungrouped_flag",
        "interstitial_first_level",
        "rewarded_ads_enabled",
        "no_ads_product_id",
    }
    ungrouped = next(row for row in rows if row["key"] == "ungrouped_flag")
    assert ungrouped["group"] is None


@pytest.mark.parametrize(
    ("value_type", "raw", "expected"),
    [
        ("BOOLEAN", "true", "true"),
        ("BOOLEAN", "on", "true"),
        ("BOOLEAN", "", "false"),
        ("NUMBER", "12", "12"),
        ("NUMBER", " 12.0 ", "12"),
        ("NUMBER", "1.5", "1.5"),
        ("STRING", "  hi  ", "hi"),
    ],
)
def test_coerce_value_normalises_by_declared_type(value_type, raw, expected):
    assert remote_config.coerce_value(value_type, raw) == expected


@pytest.mark.parametrize(("value_type", "raw"), [("NUMBER", "ten"), ("BOOLEAN", "maybe"), ("NUMBER", "nan")])
def test_coerce_value_rejects_values_the_client_would_silently_default(value_type, raw):
    with pytest.raises(remote_config.RemoteConfigError):
        remote_config.coerce_value(value_type, raw)


def test_apply_updates_reports_only_real_changes():
    updated, changed = remote_config.apply_updates(
        TEMPLATE,
        ADS_ONLY,
        {"interstitial_first_level": "3", "rewarded_ads_enabled": "true"},
    )
    assert changed == ["interstitial_first_level"]
    ads = updated["parameterGroups"]["Ads"]["parameters"]
    assert ads["interstitial_first_level"]["defaultValue"]["value"] == "3"
    # The source template must not be mutated in place.
    assert TEMPLATE["parameterGroups"]["Ads"]["parameters"]["interstitial_first_level"]["defaultValue"]["value"] == "10"


def test_apply_updates_refuses_parameters_outside_the_editable_groups():
    with pytest.raises(remote_config.RemoteConfigError, match="no_ads_product_id"):
        remote_config.apply_updates(TEMPLATE, ADS_ONLY, {"no_ads_product_id": "com.evil.sku"})


def test_publish_skips_the_deploy_when_nothing_changed(monkeypatch):
    monkeypatch.setattr(remote_config, "read_template", lambda settings: TEMPLATE)

    def fail(*args, **kwargs):  # pragma: no cover - asserts it is never called
        raise AssertionError("deploy must not run for a no-op edit")

    monkeypatch.setattr(remote_config, "_run", fail)
    assert remote_config.publish(ADS_ONLY, {"interstitial_first_level": "10"}) == []


def test_publish_deploys_an_absolute_template_path(monkeypatch):
    monkeypatch.setattr(remote_config, "read_template", lambda settings: TEMPLATE)
    seen = {}

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, *, cwd):
        firebase_json = args[args.index("-c") + 1]
        seen["args"] = args
        seen["config"] = json.loads(open(firebase_json).read())
        seen["template"] = json.loads(open(seen["config"]["remoteconfig"]["template"]).read())
        return Result()

    monkeypatch.setattr(remote_config, "_run", fake_run)
    changed = remote_config.publish(ADS_ONLY, {"interstitial_first_level": "25"})

    assert changed == ["interstitial_first_level"]
    assert "--non-interactive" in seen["args"]
    assert seen["args"][seen["args"].index("--project") + 1] == "demo-project"
    # `template` resolves against the CWD, not firebase.json, so a relative path
    # here silently breaks the deploy.
    assert seen["config"]["remoteconfig"]["template"].startswith("/")
    published = seen["template"]["parameterGroups"]["Ads"]["parameters"]
    assert published["interstitial_first_level"]["defaultValue"]["value"] == "25"


def test_publish_surfaces_the_cli_error(monkeypatch):
    monkeypatch.setattr(remote_config, "read_template", lambda settings: TEMPLATE)

    class Failure:
        returncode = 1
        stdout = ""
        stderr = "Error: HTTP Error: 403, permission denied"

    monkeypatch.setattr(remote_config, "_run", lambda args, *, cwd: Failure())
    with pytest.raises(remote_config.RemoteConfigError, match="permission denied"):
        remote_config.publish(ADS_ONLY, {"interstitial_first_level": "25"})


# ── web routes ───────────────────────────────────────────────────────────────


def _wire(cfg, **overrides):
    settings = {"project": "demo-project", "groups": ["Ads"]}
    settings.update(overrides)
    cfg["remote_config"] = {"marble-run": settings}
    config.save_config(cfg)


def _publish_build(client, token):
    return client.post(
        "/api/games/marble-run/builds",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "title": "Marble Run",
            "description": "Guide the marble.",
            "version": "1.0.0",
            "changelog": "- build",
        },
        files={
            "artifact": ("marble-run.apk", b"build-data", "application/vnd.android.package-archive"),
            "video": ("gameplay.mp4", b"video-data", "video/mp4"),
            "poster": ("preview.jpg", b"poster-data", "image/jpeg"),
        },
    )


def test_remote_config_page_requires_auth(client, data_dir, token, monkeypatch):
    _, cfg = data_dir
    _wire(cfg)
    _publish_build(client, token)
    monkeypatch.setattr(remote_config, "read_template", lambda settings: TEMPLATE)

    resp = client.get("/games/marble-run/remote-config", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login?next=")


def test_remote_config_publish_requires_auth(client, data_dir, token, monkeypatch):
    _, cfg = data_dir
    _wire(cfg)
    _publish_build(client, token)

    def fail(*args, **kwargs):  # pragma: no cover - must never run unauthenticated
        raise AssertionError("publish must not run without auth")

    monkeypatch.setattr(remote_config, "publish", fail)
    resp = client.post("/games/marble-run/remote-config", data={"rc__interstitial_first_level": "1"}, follow_redirects=False)
    assert resp.status_code == 303


def test_remote_config_page_renders_live_values(client, data_dir, token, monkeypatch):
    _, cfg = data_dir
    _wire(cfg)
    _publish_build(client, token)
    monkeypatch.setattr(remote_config, "read_template", lambda settings: TEMPLATE)

    client.post("/login", data={"password": token, "next": "/"})
    resp = client.get("/games/marble-run/remote-config")
    assert resp.status_code == 200
    assert "interstitial_first_level" in resp.text
    assert 'value="10"' in resp.text
    # Filtered out by the Ads-only group filter.
    assert "no_ads_product_id" not in resp.text


def test_remote_config_publish_forwards_only_prefixed_fields(client, data_dir, token, monkeypatch):
    _, cfg = data_dir
    _wire(cfg)
    _publish_build(client, token)
    monkeypatch.setattr(remote_config, "read_template", lambda settings: TEMPLATE)
    seen = {}

    def fake_publish(settings, updates):
        seen.update(updates)
        return ["interstitial_first_level"]

    monkeypatch.setattr(remote_config, "publish", fake_publish)
    client.post("/login", data={"password": token, "next": "/"})
    resp = client.post(
        "/games/marble-run/remote-config",
        data={"rc__interstitial_first_level": "4", "csrf_decoy": "x"},
    )
    assert resp.status_code == 200
    assert seen == {"interstitial_first_level": "4"}
    assert "Published 1 change" in resp.text


def test_remote_config_publish_shows_the_error_without_500ing(client, data_dir, token, monkeypatch):
    _, cfg = data_dir
    _wire(cfg)
    _publish_build(client, token)
    monkeypatch.setattr(remote_config, "read_template", lambda settings: TEMPLATE)

    def boom(settings, updates):
        raise remote_config.RemoteConfigError("firebase publish failed: permission denied")

    monkeypatch.setattr(remote_config, "publish", boom)
    client.post("/login", data={"password": token, "next": "/"})
    resp = client.post("/games/marble-run/remote-config", data={"rc__interstitial_first_level": "4"})
    assert resp.status_code == 200
    assert "permission denied" in resp.text


def test_unwired_game_has_no_remote_config_route_or_link(client, data_dir, token):
    _publish_build(client, token)
    client.post("/login", data={"password": token, "next": "/"})
    assert client.get("/games/marble-run/remote-config").status_code == 404
    assert "/games/marble-run/remote-config" not in client.get("/games/marble-run").text
