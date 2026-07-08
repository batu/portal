# Iframe Report Rendering Needs Both Cookie Sandbox And Inline Media

## Problem

Stream report pages passed server-side checks but rendered blank in a real
browser iframe.

## Root cause

Two browser-only constraints stacked together. First, an iframe with a bare
`sandbox` attribute gets an opaque origin, so the gallery auth cookie is not
sent to `/media/...`. Second, even after the cookie flowed, report HTML still
rendered blank because `/media` served it with `Content-Disposition:
attachment`.

## Rule

For trusted report-post HTML displayed inside Portal iframes, require both:

- iframe markup uses `sandbox="allow-same-origin"` and does not add
  `allow-scripts`;
- report-post HTML media is served inline, has `X-Content-Type-Options:
  nosniff`, has a scriptless sandbox CSP, and keeps non-report HTML downloads as
  attachments.

## How to verify

Run focused web/media tests and inspect live or generated headers:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q tests/test_web_streams.py tests/test_streams_api.py::test_media_serves_html_variants_as_attachment
```

Also confirm the evidence/header artifacts show no attachment disposition for
report HTML and attachment disposition for request variants or decision-post
HTML.

## Sources

- Trello card `A9oMiXGV`, 2026-07-08 comments: first blank-frame root cause was
  the iframe cookie sandbox; second root cause was attachment disposition; later
  comments record the inline media fix and live Chromium pass.
- Trello card `zKUB2Tnl`, 2026-07-08 addenda: phase-1 E2E must assert iframe
  sandbox and report media disposition because TestClient content assertions
  missed the real browser blank state.
- `docs/evidence/2026-07-08-stream-web-pages/evidence.md`.
- `docs/evidence/2026-07-08-stream-web-pages/assets/live-media-headers.txt`.
- `docs/evidence/2026-07-08-portal-phase1/assets/report-media-headers.txt`.
- `docs/evidence/2026-07-08-portal-phase1/assets/request-variant-media-headers.txt`.
- `docs/evidence/2026-07-08-portal-phase1/assets/decision-post-media-headers.txt`.
