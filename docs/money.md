# Money reporting

`/money` is an authenticated, read-only report for Find the Bird and Find the Dog. The default is the previous 30 complete days in Europe/Istanbul. Dates are inclusive, selectable up to 366 days, and may include today. Reports containing today are provisional.

## Metrics

- Spend is Meta ad spend plus Google Ads ad cost, reconciled to App campaign totals, using configured accounts only.
- Revenue is AdMob mediation `ESTIMATED_EARNINGS`, requested in TRY and converted from micros with Decimal arithmetic. In-app purchases are excluded.
- Revenue/spend is a calendar-period comparison, not cohort ROAS: revenue includes organic and previously acquired users.
- The best-ad estimate replays the full selected budget at the lowest observed positive-spend CPI, assuming equal revenue per install across the selected games and ads. Revenue per install = total period ad revenue / recorded paid installs. Projected installs = total spend / lowest CPI. Projected revenue = projected installs × revenue per install. Projected revenue/spend = revenue per install / lowest CPI. The panel also shows the gain over observed revenue.
- Meta uses `mobile_app_install` actions with impression-time reporting and a fixed 7-day click / 1-day view window. `omni_app_install` overlaps and is not added again. Google uses ad-level `metrics.conversions` filtered to the DOWNLOAD conversion category; modeled fractional conversions are preserved. Missing actions in a successful report mean zero *recorded* installs. A missing install measurement or failed provider prevents the estimate. Zero-install ads remain in spend but cannot win; equal CPI prefers the larger sample.
- Period earnings include organic and earlier users, while paid installs may be under-attributed. Their quotient is an optimistic proxy, not measured lifetime revenue per acquired user. Different providers' attribution methods and recent cohorts are not fully comparable. The replay assumes unchanged CPI and monetization at higher spend; hindsight selection and small samples prevent causal claims about exploration cost.

Missing providers, incomplete pagination, invalid values, incompatible currencies/time zones, and unresolved identities prevent complete totals. Provider failures expose redacted status only. Valid empty provider results mean zero delivery. Historical Dog-to-Bird AdMob identity contamination is disclosed for per-game reporting.

## Runtime setup

Add a `money` object to the existing private Gallery configuration. Do not commit runtime configuration or credentials. Paths below are examples, not credentials. Existing Google OAuth grants must already be present; the page never initiates a consent flow.

```json
{
  "money": {
    "meta": {
      "account_id": "META_AD_ACCOUNT_ID_WITHOUT_ACT_PREFIX",
      "token_file": "/private/path/meta-marketing-api.token"
    },
    "google_ads": {
      "customer_ids": ["GOOGLE_ADS_CUSTOMER_ID_WITHOUT_DASHES"],
      "developer_token_file": "/private/path/google-ads-developer-token",
      "oauth_credentials": "/private/path/client_secret.json",
      "oauth_cache": "/private/path/google_ads_oauth2l_cache",
      "oauth2l": "/absolute/path/to/oauth2l"
    },
    "admob": {
      "publisher_id": "pub-PUBLISHER_ID",
      "oauth_credentials": "/private/path/client_secret.json",
      "oauth_cache": "/private/path/admob_oauth2l_cache",
      "oauth2l": "/absolute/path/to/oauth2l",
      "app_games": {}
    }
  }
}
```

`google_ads.login_customer_id` is optional for manager-account access. Include all relevant non-manager customer IDs once; unconfigured accounts are outside report coverage. AdMob linked store IDs map to the two games; optional `app_games` maps unlinked AdMob app IDs to `find-the-bird` or `find-the-dog` after operator verification. Meta maps the promoted application ID, never campaign-name guesses.

Both spending accounts and AdMob must use Europe/Istanbul reporting dates; spend currency must be TRY. Other currencies/time zones are rejected rather than silently combined.

OAuth2l cached scopes must match the configured client and the existing grants: Google Ads uses `https://www.googleapis.com/auth/adwords`; AdMob uses readonly, report, and monetization scopes in that order. The monetization scope is reused from the existing local grant; all operations here are read-only. Token files must be regular, owner-only files. Credentials never go into query strings, responses, cache contents, or error messages.

Snapshots live in `GALLERY_DATA_DIR/money`, keyed by date window and configuration fingerprint, with a 15-minute lifetime. A subsequent visit refreshes expired reports. Cache hits do not wait for provider calls; cache misses are serialized to limit provider load, with three independent providers fetched concurrently. There is no background scheduler. Failed reports do not borrow totals from another period.

## Verify

```sh
uv run --extra dev pytest tests/test_money.py tests/test_money_providers.py -q
```

Before deployment, use a separate `GALLERY_DATA_DIR` and loopback uvicorn instance to read the selected provider reports and inspect `/money` in the browser. Compare individual-game and combined totals for the same dates. Confirm account coverage, the CPI replay and its assumptions, missing-provider behavior, and that anonymous visitors reach login even when public artifact viewing is enabled. Installing runtime configuration or restarting the production Portal service requires separate deployment authorization.
