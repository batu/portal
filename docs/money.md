# Money reporting

`/money` is an authenticated, read-only report for Find the Bird and Find the Dog. The default is the previous 30 complete days in Europe/Istanbul. Dates are inclusive, selectable up to 366 days, and may include today. Reports containing today are provisional.

## Metrics

- Spend is Meta ad spend plus Google Ads App campaign cost, using configured accounts only.
- Revenue is AdMob mediation `ESTIMATED_EARNINGS`, requested in TRY and converted from micros with Decimal arithmetic. In-app purchases are excluded.
- Revenue/spend is a calendar-period comparison, not cohort ROAS: revenue includes organic and previously acquired users.
- The best-ad ratio is the maximum attributed ad revenue/spend among paid ads. It requires attribution for every paid row. Meta uses impression-time reporting with a fixed 7-day click / 1-day view window so revenue is credited to the delivery dates that generated the spend. Recent delivery may not have matured. Projected revenue is that ratio multiplied by the selected total spend. This hindsight estimate assumes constant returns under scaling and cannot establish a causal cost of exploration.
- Missing ad revenue is not zero. Only Meta's explicit `app_custom_event.fb_mobile_ad_impression` action value is accepted as attributed ad revenue; generic purchase/conversion values are excluded. Google campaign costs do not manufacture ad-level attribution.

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

Before deployment, use a separate `GALLERY_DATA_DIR` and loopback uvicorn instance to read the selected provider reports and inspect `/money` in the browser. Compare individual-game and combined totals for the same dates. Confirm account coverage, the unavailable-attribution state, and that anonymous visitors reach login even when public artifact viewing is enabled. Installing runtime configuration or restarting the production Portal service requires separate deployment authorization.
