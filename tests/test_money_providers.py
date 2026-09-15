import json

import pytest

from gallery import config, money, money_providers as providers


def test_meta_install_actions_do_not_double_count_omni_alias(monkeypatch):
    monkeypatch.setattr(providers, "secret", lambda path: "fixture")
    calls = []
    def request(url, token, body=None, **kwargs):
        calls.append(url)
        if "fields=currency" in url:
            return {"currency": "TRY", "timezone_name": "Turkey"}
        if body and "batch" in body:
            batch = json.loads(body["batch"])
            assert batch == [{"method": "GET", "relative_url": "10?fields=promoted_object"}]
            assert kwargs["form"] is True
            return [{"code": 200, "body": json.dumps({"promoted_object": {"application_id": "1327770709435424"}})}]
        assert "action_report_time=impression" in url
        assert "action_attribution_windows=" in url
        row = {"ad_id": "1", "ad_name": "Arbitrary title", "adset_id": "10", "spend": "12.50"}
        if "after=" not in url:
            return {"data": [{**row, "actions": [{"action_type": "purchase", "value": "999"}]}],
                    "paging": {"next": "https://untrusted.invalid/?access_token=never-follow", "cursors": {"after": "next"}}}
        return {"data": [{**row, "ad_id": "2", "actions": [{"action_type": "mobile_app_install", "value": "3"}, {"action_type": "omni_app_install", "value": "3"}]}]}
    monkeypatch.setattr(providers, "request_json", request)
    result = providers.meta({"token_file": "unused", "account_id": "123"}, "2026-09-01", "2026-09-14")
    assert result["rows"][0]["game"] == "find-the-bird"
    assert result["rows"][0]["installs"] == "0"
    assert result["rows"][1]["installs"] == "3"
    assert all(url.startswith("https://graph.facebook.com/") for url in calls)
    assert calls.count("https://graph.facebook.com/v23.0/") == 1


def test_google_spend_conversion_and_other_games_excluded(monkeypatch):
    monkeypatch.setattr(providers, "oauth", lambda *args: "fixture")
    monkeypatch.setattr(providers, "secret", lambda path: "fixture")
    def request(url, token, body, headers):
        if "FROM customer" in body["query"]:
            return {"results": [{"customer": {"currencyCode": "TRY", "timeZone": "Europe/Istanbul", "manager": False}}]}
        if "FROM ad_group_ad" in body["query"]:
            if "metrics.conversions" in body["query"]:
                assert "segments.conversion_action_category = 'DOWNLOAD'" in body["query"]
                return {"results": [{"adGroupAd": {"resourceName": "customers/123/adGroupAds/10~20"}, "metrics": {"conversions": "2.5"}}]}
            return {"results": [{"campaign": {"id": "10"}, "adGroupAd": {"resourceName": "customers/123/adGroupAds/10~20", "ad": {"id": "20", "name": "App ad"}}, "metrics": {"costMicros": "12345678"}}]}
        return {"results": [{"campaign": {"id": "10", "name": "App campaign", "appCampaignSetting": {"appId": "6796698146"}}, "metrics": {"costMicros": "12345678"}},
                            {"campaign": {"id": "11", "name": "Other", "appCampaignSetting": {"appId": "123"}}, "metrics": {"costMicros": "999999999"}}]}
    monkeypatch.setattr(providers, "request_json", request)
    result = providers.google_ads({"developer_token_file": "unused", "customer_ids": ["123"]}, "2026-09-01", "2026-09-14")
    assert len(result["rows"]) == 1
    assert result["rows"][0]["spend"] == "12.345678"
    assert result["rows"][0]["installs"] == "2.5"


@pytest.mark.parametrize("truncated", [False, True])
def test_admob_micros_currency_and_truncation(monkeypatch, truncated):
    monkeypatch.setattr(providers, "oauth", lambda *args: "fixture")
    def request(url, token, body=None):
        if url.endswith("/accounts"):
            return {"account": [{"publisherId": "pub-123", "reportingTimeZone": "Europe/Istanbul"}]}
        if "/apps?" in url:
            return {"apps": [{"appId": "bird", "linkedAppInfo": {"appStoreId": "6796698146"}},
                             {"appId": "dog", "linkedAppInfo": {"appStoreId": "6772100729"}}]}
        assert body["reportSpec"]["localizationSettings"]["currencyCode"] == "TRY"
        return [{"header": {"localizationSettings": {"currencyCode": "TRY"}}},
                {"row": {"dimensionValues": {"APP": {"value": "bird"}}, "metricValues": {"ESTIMATED_EARNINGS": {"microsValue": "1234567"}}}},
                {"footer": {"matchingRowCount": "2" if truncated else "1"}}]
    monkeypatch.setattr(providers, "request_json", request)
    if truncated:
        with pytest.raises(ValueError, match="Truncated"):
            providers.admob({"publisher_id": "pub-123"}, "2026-09-01", "2026-09-14")
    else:
        assert providers.admob({"publisher_id": "pub-123"}, "2026-09-01", "2026-09-14")["rows"] == [{"game": "find-the-bird", "revenue": "1.234567"}]


def test_cache_reuses_exact_window_and_redacts_provider_failures(data_dir, monkeypatch):
    cfg = config.load_config()
    cfg["money"] = {key: {"configured": True} for key in money.PROVIDERS}
    config.save_config(cfg)
    calls = []
    def fetch(provider, settings, start, end):
        calls.append((provider, start, end))
        if provider == "meta":
            raise RuntimeError("secret credential and private provider response")
        return {"currency": "TRY", "timezone": "Europe/Istanbul", "rows": []}
    monkeypatch.setattr(providers, "fetch_report", fetch)
    first = money.load_reports("2026-09-01", "2026-09-14")
    assert len(calls) == 3
    assert first == money.load_reports("2026-09-01", "2026-09-14")
    assert len(calls) == 3
    assert "secret credential" not in json.dumps(first)
    assert money.summarize(first, "all")["spend"] is None
    money.load_reports("2026-09-02", "2026-09-14")
    assert len(calls) == 6


def test_oauth_without_cached_grant_never_launches_consent(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.write_text("{}")
    creds = tmp_path / "creds"
    creds.write_text('{"installed": {"client_id": "fixture", "client_secret": "fixture"}}')
    monkeypatch.setattr(providers.subprocess, "run", lambda *a, **kw: pytest.fail("Must not start consent"))
    with pytest.raises(ValueError, match="No existing"):
        providers.oauth({"oauth_cache": str(cache), "oauth_credentials": str(creds)}, "scope")
