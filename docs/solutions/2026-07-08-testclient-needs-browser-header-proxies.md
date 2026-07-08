---
title: "TestClient Needs Browser Header Proxies"
date: "2026-07-08"
module: "testing"
problem_type: "browser-parity"
tags: ["testclient", "browser-proof", "headers", "testing"]
---

# TestClient Needs Browser Header Proxies

## Problem

FastAPI `TestClient` can prove route status, body text, and headers, but it
does not exercise browser iframe, cookie-origin, download-disposition, or media
rendering behavior.

## Root cause

The failing Portal report iframe looked fine to server-side content tests:
`/media` returned 200 and the HTML body existed. Real browsers still rendered
blank because iframe sandboxing and `Content-Disposition` are browser policies.

## Rule

When a worker cannot run a real browser, add TestClient assertions for the exact
browser contract instead of relying on content presence:

- iframe sandbox tokens;
- absence or presence of `Content-Disposition` by media type and post type;
- `Content-Type`, `nosniff`, and CSP for inline HTML;
- token absence in rendered pages and generated artifacts.

Treat these as proxies, not as visual proof. Visible UI still needs browser
review or a cited InSitu/conductor browser observation.

## How to verify

Use the full phase-1 E2E flow and inspect its rendered artifacts:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q tests/test_e2e_portal.py
```

Then check the generated header files under
`docs/evidence/2026-07-08-portal-phase1/assets/`.

## Sources

- Trello card `zKUB2Tnl`, 2026-07-08 addendum: the two-layer blank iframe bug
  happened live while TestClient content assertions still passed, so headers
  became the TestClient-visible proxy.
- Trello card `zKUB2Tnl`, review comment: phase-1 evidence was hardened after
  review to use the browser verdict route, parse `Content-Disposition`
  case-insensitively, normalize evidence IDs, fail on raw token leaks, and avoid
  Telegram side effects.
- `docs/evidence/2026-07-08-portal-phase1/evidence.md`.
- `docs/evidence/2026-07-08-portal-phase1/generate_rendered_assets.py`.
