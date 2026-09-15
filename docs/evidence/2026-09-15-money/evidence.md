# Money page verification

Status: partial. The page and its numeric/unavailable states are verified locally. Live totals load, but real best-ad performance remains unavailable because ad-level revenue attribution is absent. Production has not been deployed.

## Scope

- Private `/money` page for Find the Bird and Find the Dog, with game and inclusive date filters.
- TRY spend from configured Meta and Google Ads accounts, AdMob mediation estimated earnings, and revenue divided by spend.
- Best-ad hindsight calculation uses attributed ad revenue. Missing attribution stays unavailable rather than being filled with zeros or install proxies.

## Checklist

- [x] Inspect existing Portal routes, provider tooling, and reporting identities.
- [x] Implement arithmetic, provider adapters, cached snapshots, filters, and private page.
- [x] Focused tests: totals, weighting, zero/missing values, incompatible currency/time zones, authentication, filter validation, provider parsing, pagination, redaction, and OAuth consent prevention.
- [x] Read-only live reports succeeded for all three configured sources; raw financial snapshots remain outside this public repository.
- [x] Browser: real reports render at desktop and phone widths; both game filters return distinct totals; phone document width equals viewport width.
- [x] Complete code and visual review, final checks, and review artifact.

## Evidence strategy

The initial test run failed on the missing `gallery.money` module before implementation. Focused arithmetic/route/provider coverage passes 19 tests. The expanded repository suite passes 477 tests. `ruff check` on the four new Python files and `git diff --check` pass. No new dependency was added. Existing FastAPI/Starlette deprecation warnings are unrelated.

## Browser and review results

- [Synthetic desktop success state](synthetic-desktop.png): spend 400, revenue 60, actual ratio 0.150x, best ratio 0.200x, projected revenue 80. These are test values, not business figures.
- [Synthetic phone success state](synthetic-mobile.png) and [expanded disclosures](synthetic-mobile-expanded.png): 390px viewport, 390px document width, internal table scroll reaches 194px of 194px.
- [Invalid date range](synthetic-invalid-range.png): HTTP 400 preserves filters/navigation with an inline alert. Native ArrowUp changes the end date from September 1 to September 2; Enter submits the corrected September 2 one-day range.
- [Unavailable provider](synthetic-incomplete.png): failed Meta reporting prevents total spend and ratio while preserving known revenue and usable filters.
- Keyboard Tab advances from Game to From; Enter opens disclosures with focus retained. No browser console errors observed.
- Three simplification reviewers ran (reuse, quality, efficiency). Applied standard date parsing, registry-derived worker count, cache-hit bypass of the miss lock, and batched Meta identity resolution. Independent cache-miss serialization remains deliberate to bound provider load.
- Code review found attribution date-basis mismatch and identity-call fan-out; both were fixed and rechecked. GET multi-ID reads failed against the live API, so the final implementation uses a read-only Graph batch POST containing only GET operations, verified live with 13 ad rows. Provider acquisition has a 60-second request deadline.
- Independent UI-interaction and visual reviewers both returned `passed`, no remaining findings or gaps.

## Data limits

Live ad-level revenue was absent for the queried paid ads, so the best-ad panel correctly rendered unavailable. Its numeric success state is exercised with synthetic fixtures. Provider identity contamination affects historical per-game earnings; a visible notice accompanies individual game filters. Calendar revenue/spend includes organic and older users and is not cohort ROAS. Google campaign spend contributes to total spend but cannot identify an individual winning ad without attribution.

The configured Google Ads manager lists one non-manager customer, which was verified and reported zero spend in the selected period. A different directly accessible customer returned 403 during discovery and is not claimed as covered. The page explicitly scopes coverage to configured accounts.

## Privacy and deployment

This repository is public. Committed screenshots use synthetic data only. Live snapshots, credentials, runtime configuration, and live financial screenshots are excluded. Production configuration and service restart remain a separate deployment action.

Next action: review the local implementation and approve production activation. Resolve ad-level revenue attribution before treating the fourth metric as measurable; do not substitute CPI without an explicit product decision.

## Provider references

- [Google Ads reporting](https://developers.google.com/google-ads/api/docs/reporting/overview)
- [AdMob mediation reports](https://developers.google.com/admob/api/reference/rest/v1/accounts.mediationReport/generate)
- [Meta Insights example maintained by Meta](https://www.postman.com/meta/facebook-marketing-api/request/u07tack/get-ad-insights-l1)
