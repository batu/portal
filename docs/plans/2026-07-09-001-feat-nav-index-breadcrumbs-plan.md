---
title: "Portal Navigation Breadcrumbs - Plan"
type: feat
date: 2026-07-09
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
origin: "trello-card:mhONwIBb"
trello: "https://trello.com/c/mhONwIBb"
spec: docs/portal-spec.md
---

# Portal Navigation Breadcrumbs - Plan

## Goal Capsule

| Field | Value |
|---|---|
| Objective | Add a reliable way back to the full Portal index from stream and request pages by making the header brand a root link and replacing page-level back links with breadcrumbs. |
| Authority | Trello card `mhONwIBb` first, then existing Portal template/CSS/test patterns, then `docs/portal-spec.md` navigation and auth constraints. |
| Execution profile | Lightweight template/CSS/test change in the FastAPI Gallery/Portal app. |
| Stop conditions | Do not touch `gallery/server.py` or `gallery/db.py`; if breadcrumb data cannot be built from the existing template context, stop and report the blocker. |
| Completion signal | The full test suite passes, and live curl checks after the launchd restart show the index, stream, and request navigation links render. |

## Product Contract

### Summary

Every web page should expose the full Portal index through the `Portal` brand link, and stream/request pages should show breadcrumb navigation instead of one-off back links.
The request breadcrumb should keep the existing stream destination while adding the root index and current request title.

### Problem Frame

Batu requested an obvious way back to the full index from individual pages.
The current stream and request templates use local back links (`Home`, or the request's stream target) that do not communicate the full hierarchy, so a user can lose the broader index path when reviewing a single stream or decision page.

### Requirements

- R1. The header brand text `Portal` links to `/` on every rendered web page and keeps the current cookie-first web auth pattern without adding token-bearing navigation links.
- R2. Request pages render a breadcrumb shaped as `Index / <stream> / <request title>`, where `Index` links to `/`, `<stream>` links to the current `back.href` target, and `<request title>` is the current page text.
- R3. Request pages without a stream still expose `Index / <request title>` rather than losing the index link.
- R4. Stream pages render a breadcrumb shaped as `Index / <stream>`, where `Index` links to `/` and the stream label is the current page text.
- R5. Breadcrumb styling matches the existing compact `.back-link` treatment and does not introduce a heavier navigation component.
- R6. Existing media links, browser write forms, stream decision links, and verdict behavior remain unchanged.
- R7. Implementation stays inside templates, CSS, and focused tests; `gallery/server.py` and `gallery/db.py` are out of scope.

### Acceptance Examples

- AE1. Given a user opens `/s/alpha?token=<valid>`, when the page renders, then the top header contains `Portal` linking to `/`, the page breadcrumb contains `Index` linking to `/`, and the current stream title appears as the final crumb.
- AE2. Given a request belongs to stream `alpha`, when the user opens `/r/<req_id>?token=<valid>`, then the breadcrumb contains `Index`, the stream crumb links to `/s/alpha`, and the current request title appears as the final crumb.
- AE3. Given a request page or stream page renders after a token-bearing first visit, when the user inspects ordinary navigation links, then the breadcrumb and brand links do not leak the raw token in rendered hrefs.

### Scope Boundaries

- No changes to FastAPI route handlers, request/stream database lookups, auth middleware, media serving, browser write twins, or data models.
- No new JavaScript behavior or client-side routing.
- No redesign of the header, stream timeline, request decision panel, before/after review UI, or index cards.

## Planning Contract

### Assumptions

- `gallery/templates/base.html` already renders the brand as an anchor in this worktree; the implementation should preserve that shape and add focused coverage if the test suite does not already prove it.
- `gallery/server.py` already passes `back.href` and `back.label` to `request.html`; request breadcrumbs should consume that context rather than introducing server-side breadcrumb construction.
- Cookie auth is the intended web navigation mechanism after a token-bearing visit sets `gallery_token`; breadcrumb and brand links should stay token-free like stream page decision links and browser form actions.

### Key Technical Decisions

- KTD1. Use template-local breadcrumb markup instead of route changes. `request.html` can derive the request breadcrumb from existing `back` and `r` values, and `stream.html` already has `stream` title/slug context.
- KTD2. Replace `.back-link` usages with a reusable breadcrumb class while keeping compatible styling. This keeps the visible treatment consistent and avoids leaving both a breadcrumb and a back link competing for the same role.
- KTD3. Assert rendered HTML for navigation rather than adding route-level behavior tests. The requested behavior is template output, and the no-server-change boundary makes `TestClient` page assertions the right proof.
- KTD4. Preserve token hygiene for ordinary navigation. Existing media URL token forwarding is a separate behavior and should not be used as the pattern for breadcrumbs or the brand link.

### Relevant Code and Patterns

- `gallery/templates/base.html` owns the shared header and brand link.
- `gallery/templates/request.html` currently renders the request-level `.back-link` from `back.href` and `back.label`.
- `gallery/templates/stream.html` currently renders a stream-level `.back-link` to `/`.
- `gallery/static/style.css` defines `.back-link`, `.brand`, and the compact Portal visual system.
- `tests/test_web_streams.py`, `tests/test_api.py`, and `tests/test_before_after.py` already assert rendered stream/request page HTML.
- `docs/solutions/2026-07-08-browser-writes-need-cookie-twins.md` documents the token-free browser navigation and write-path convention.
- `docs/solutions/2026-07-08-run-uv-with-sandbox-cache.md` documents the required `UV_CACHE_DIR=/private/tmp/uv-cache` test prefix.

## Implementation Units

### U1. Add breadcrumb markup and matching styles

- **Goal:** Replace stream/request back links with breadcrumbs while preserving the shared brand link to the index.
- **Requirements:** R1, R2, R3, R4, R5, R6, R7; covers AE1, AE2, AE3.
- **Dependencies:** None.
- **Files:**
  - Modify: `gallery/templates/base.html`
  - Modify: `gallery/templates/request.html`
  - Modify: `gallery/templates/stream.html`
  - Modify: `gallery/static/style.css`
  - Test: `tests/test_web_streams.py`
  - Test: `tests/test_api.py` or `tests/test_before_after.py` if existing request-page coverage is the narrower home for assertions
- **Approach:** Keep the shared brand anchor in `base.html` and ensure its href is `/`.
  Replace the single `.back-link` in `stream.html` with breadcrumb markup whose first crumb is `Index` linking to `/` and whose final crumb is the stream title or slug.
  Replace the single `.back-link` in `request.html` with breadcrumb markup whose first crumb is `Index`, whose middle crumb uses `back.href` and `back.label` when that target is stream-specific, and whose final crumb is `r.title`.
  For the fallback request case where `back.href` is `/`, omit the duplicate middle crumb and render `Index / <request title>`.
  Add CSS that reuses the sizing, muted color, hover, and spacing conventions from `.back-link`; keep separators as text, not layout-heavy controls.
- **Execution note:** Start with focused `TestClient` HTML assertions for the stream and request pages, then update templates/styles to satisfy them.
- **Patterns to follow:** Existing `.back-link` spacing and hover rules in `gallery/static/style.css`; token-free stream links in `gallery/templates/stream.html`; request `back` context consumption in `gallery/templates/request.html`.
- **Test scenarios:**
  - Happy path: a stream page rendered with a token shows `Portal` href `/`, `Index` href `/`, and the stream title as the current crumb.
  - Happy path: a request attached to a stream shows `Portal` href `/`, `Index` href `/`, a stream crumb with the same href that the old back link used, and the request title as the current crumb.
  - Edge case: a request without a resolvable stream does not render duplicate `Index` crumbs and still shows the request title as the final crumb.
  - Edge case: rendered brand and breadcrumb hrefs do not contain `token=`.
  - Regression: stream decision links, media links, request variant markup, decision controls, and browser form actions remain unchanged except for the removed back-link markup.
- **Verification:** Focused web tests fail on the old single-back-link markup and pass once breadcrumbs and brand assertions match the rendered pages.

## Verification Contract

| Gate | Applies to | Done signal |
|---|---|---|
| Focused rendered-page tests | U1 | Stream and request page assertions prove the breadcrumb labels, hrefs, token hygiene, and fallback behavior. |
| Full suite | U1 | `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q` passes. |
| Diff boundary | U1 | `git diff -- gallery/server.py gallery/db.py` is empty. |
| Live restart | U1 | `launchctl kickstart -k gui/501/com.appletolye.gallery` completes before live curl checks. |
| Live curl | U1 | Curling `/` and one real request page confirms the brand/index links and request breadcrumb render in the deployed service. |

## Definition of Done

- The only production files changed are `gallery/templates/base.html`, `gallery/templates/request.html`, `gallery/templates/stream.html`, and `gallery/static/style.css`, unless tests need focused updates.
- The request page no longer renders the old single back-link as its primary navigation; it renders the index/stream/request breadcrumb instead.
- The stream page no longer renders the old `Home` back-link as its primary navigation; it renders the index/stream breadcrumb instead.
- The header brand remains a root link on every page that extends `base.html`.
- Rendered breadcrumb and brand links are token-free, relying on the existing cookie-auth web flow.
- Focused tests cover stream pages, request pages attached to streams, request fallback behavior, and token hygiene.
- The required full pytest command passes with the uv cache override.
- The live launchd service is restarted and curl output for `/` plus a request page is checked before handoff.
