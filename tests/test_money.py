from decimal import Decimal

import pytest

from gallery import money


def reports():
    return [
        {"provider": "Meta", "kind": "spend", "status": "ok", "currency": "TRY",
         "timezone": "Europe/Istanbul", "rows": [
             {"game": "find-the-bird", "ad_id": "1", "name": "Bird A", "spend": "100", "installs": "10"},
             {"game": "find-the-dog", "ad_id": "2", "name": "Dog B", "spend": "300", "installs": "10"}]},
        {"provider": "Google Ads", "kind": "spend", "status": "ok", "currency": "TRY",
         "timezone": "Europe/Istanbul", "rows": []},
        {"provider": "AdMob", "kind": "revenue", "status": "ok", "currency": "TRY",
         "timezone": "Europe/Istanbul", "rows": [
             {"game": "find-the-bird", "revenue": "25"},
             {"game": "find-the-dog", "revenue": "35"}]},
    ]


def test_weighted_totals_and_best_ad_counterfactual():
    result = money.summarize(reports(), "all")
    assert result["spend"] == Decimal("400")
    assert result["revenue"] == Decimal("60")
    assert result["ratio"] == Decimal("0.15")
    assert result["best"]["name"] == "Bird A"
    assert result["total_installs"] == 20
    assert result["revenue_per_install"] == 3
    assert result["best_cpi"] == 10
    assert result["best_ratio"] == Decimal("0.3")
    assert result["best_projected_revenue"] == Decimal("120")


def test_filter_before_totalling_or_selecting_winner():
    result = money.summarize(reports(), "find-the-dog")
    assert result["spend"] == 300
    assert result["revenue"] == 35
    assert result["best"]["name"] == "Dog B"


def test_missing_install_measurement_blocks_estimate():
    data = reports()
    data[0]["rows"][0]["installs"] = None
    result = money.summarize(data, "all")
    assert result["ratio"] == Decimal("0.15")
    assert result["best_ratio"] is None
    assert result["total_installs"] is None


def test_zero_install_ads_count_toward_budget_but_cannot_win():
    data = reports()
    data[0]["rows"][0]["installs"] = "0"
    result = money.summarize(data, "all")
    assert result["spend"] == 400
    assert result["best"]["name"] == "Dog B"
    assert result["best_cpi"] == 30
    assert result["best_ratio"] == Decimal("0.2")


@pytest.mark.parametrize("installs", ["100", None])
def test_zero_spend_rows_do_not_dilute_or_block_paid_install_baseline(installs):
    data = reports()
    data[0]["rows"].append({"game": "find-the-bird", "ad_id": "free", "name": "Zero spend", "spend": "0", "installs": installs})
    result = money.summarize(data, "all")
    assert result["total_installs"] == 20
    assert result["best_ratio"] == Decimal("0.3")
    assert result["best_projected_installs"] == 40
    assert result["best_gain"] == 60


def test_zero_revenue_is_valid_but_missing_revenue_blocks_estimate():
    data = reports()
    data[2]["rows"] = []
    assert money.summarize(data, "all")["best_ratio"] == 0
    data[2]["status"] = "unavailable"
    assert money.summarize(data, "all")["best_ratio"] is None


def test_equal_cpi_prefers_larger_observed_sample():
    data = reports()
    data[0]["rows"][1]["installs"] = "30"
    assert money.summarize(data, "all")["best"]["name"] == "Dog B"


@pytest.mark.parametrize("failure", ["unavailable", "not_configured"])
def test_missing_provider_blocks_total_and_ratio(failure):
    data = reports()
    data[1]["status"] = failure
    result = money.summarize(data, "all")
    assert result["spend"] is None
    assert result["reported_spend"] == 400
    assert result["revenue"] == 60
    assert result["ratio"] is None
    assert result["best_ratio"] is None


def test_currency_and_timezone_must_match():
    for field, value in [("currency", "USD"), ("timezone", "America/Los_Angeles")]:
        data = reports()
        data[1][field] = value
        assert money.summarize(data, "all")["ratio"] is None


def test_zero_spend_and_zero_revenue_are_distinct_from_missing():
    data = reports()
    for report in data:
        report["rows"] = []
    result = money.summarize(data, "all")
    assert result["spend"] == result["revenue"] == 0
    assert result["ratio"] is result["best_ratio"] is None


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "garbage"])
def test_invalid_money_rejected(value):
    with pytest.raises(ValueError):
        money.amount(value)


def test_private_route_even_with_public_viewing(client, token, monkeypatch):
    from gallery import config
    cfg = config.load_config()
    cfg["public_viewing"] = True
    config.save_config(cfg)
    monkeypatch.setattr(money, "load_reports", lambda start, end: reports())
    assert client.get("/money", follow_redirects=False).status_code == 303
    page = client.get(f"/money?token={token}&start=2026-09-01&end=2026-09-14")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert "400.00" in page.text
    assert "0.150×" in page.text
    assert "CPI-based estimate" in page.text
    assert token not in page.text


def test_invalid_filters_do_not_call_providers(client, token, monkeypatch):
    def unexpected(*args):
        pytest.fail("Invalid filters must not fetch providers")
    monkeypatch.setattr(money, "load_reports", unexpected)
    for query in ["start=bad", "start=2026-09-14&end=2026-09-01", "game=other"]:
        page = client.get(f"/money?token={token}&{query}")
        assert page.status_code == 400
        assert 'role="alert"' in page.text
        assert 'name="start"' in page.text
        assert 'type="submit"' in page.text
