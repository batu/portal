---
title: "feat: Add stream web pages and index stream section"
type: feat
status: active
date: 2026-07-08
origin: "trello-card:A9oMiXGV"
trello: "https://trello.com/c/A9oMiXGV"
spec: docs/portal-spec.md
---

# feat: Add stream web pages and index stream section

## Summary

Add the server-rendered human surface for Portal streams: `/s/{slug}` pages that show report and decision posts with existing web-token auth, plus a streams section on the home page. The implementation should reuse the landed streams/posts API and DB helpers, keep `/api/*` behavior unchanged, and stay phone-friendly with the existing Jinja/CSS/vanilla web patterns.

---

## Problem Frame

Streams and posts can exist in the service, but there is no permanent human-readable page where a stream accrues reports and decision links. The Portal spec defines `/s/<slug>` as the stable sharing unit for session and pinned streams, and the card asks for a server-rendered page rather than a browser JS app because browser code cannot send bearer headers.

---

## Assumptions

*This plan was authored in pipeline mode without synchronous user confirmation. The items below are agent inferences that fill gaps in the input and should be reviewed before implementation proceeds.*

- The dependency card for streams/posts HTTP API has landed before this implementation starts. In this worktree, `gallery/db.py`, `gallery/server.py`, and `tests/test_streams_api.py` already include stream/post tables, helpers, bearer endpoints, report uploads, decision posts, and legacy request dual-write behavior.
- The strict scope fence should be honored by keeping any stream-summary query needed for the index page inside `gallery/server.py`, even though a public `db.list_streams()` helper would better match the persistence-layer pattern. This divergence should be reported in SURPRISES after implementation.
- The current `/media/{id}/{filename}` policy serves HTML/SVG/unknown uploads as attachments. This card should not change that shared media policy; render report link/iframe markup against the existing media URL, verify the media link is fetchable, and report any real-browser iframe limitation as a follow-up surprise.
- "Latest activity" for an empty stream should fall back to `streams.created_at`; otherwise it should use the newest post timestamp.
- Decision post status badges should map request `status='open'` to the user-facing "pending" badge and `status='decided'` to "decided".

---

## Requirements

- R1. Add `GET /s/{slug}` as a server-rendered Jinja page protected by the existing cookie/query-token web auth helpers (`web_token_ok` and `_maybe_set_cookie`), matching current web-route 401 behavior for missing or invalid tokens.
- R2. Return 404 for unknown stream slugs without auto-creating streams.
- R3. Render stream metadata on `/s/{slug}`: slug, title, kind, created time, and an archived marker when `closed_at` is set.
- R4. Render posts newest-first on `/s/{slug}`.
- R5. Render `report` posts as a media link plus a sandboxed iframe element pointing at the report HTML/media entry from `/media/<post_id>/<filename>`, relying on the web auth cookie rather than propagating `?token=` into generated links. The iframe markup is in scope; changing `/media` content-disposition so HTML truly renders inline in all browsers is follow-up work.
- R6. Render `decision` posts as links to `/r/{req_id}` with a pending/decided status badge derived from the existing request row.
- R7. Keep the stream page itself read-only for closed streams: no note, answer, verdict, or mutating stream controls are added by this card, while existing decision links may remain visible.
- R8. Add a streams section to `templates/index.html` showing slug, title, kind, post count, and latest activity, with each item linking to `/s/<slug>`.
- R9. Keep the UI mobile-friendly by extending the existing `base.html`, `index.html`, `request.html`, and `style.css` conventions; no JS framework and no bearer-auth calls from page JS.
- R10. Do not modify `/api/*` handlers, `gallery/cli.py`, `gallery/client.py`, or `pyproject.toml`.
- R11. Add focused `TestClient` coverage in `tests/test_web_streams.py` and verify with the full project test command.

---

## Card Acceptance Criteria Trace

| Card acceptance criterion | Requirements | Units | Test scenario anchor |
|---|---|---|---|
| `/s/<slug>` 200 with valid token cookie/query param, 401 for missing/invalid token | R1 | U1 | U1 auth tests |
| Unknown slug returns 404 | R2 | U1 | U1 missing-stream test |
| Report post appears with working media link | R4, R5 | U1, U2 | U1/U2 report context, render, and media-link tests |
| Decision post links to `/r/{req_id}` with status badge | R6 | U2 | U2 decision-link/status tests |
| Closed stream shows archived state | R3, R7 | U2 | U2 archived marker test |
| Index page lists streams | R8 | U3 | U3 index stream-list test |
| Existing tests stay green and `/api/*` unchanged | R9, R10, R11 | U1-U3 | Full-suite verification |

---

## Scope Boundaries

- No new `/api/*` endpoints or changes to existing API request/response contracts.
- No bearer-token calls from browser JavaScript.
- No message posts, stream note box, `/s/{slug}/note`, `/s/{slug}/answer`, ask/pull, or browser twin routes for phase-2 messages.
- No CLI work in `gallery/cli.py`, no client helper work in `gallery/client.py`, and no dependency changes in `pyproject.toml`.
- No schema migrations, historical backfill, stream deletion, stream token model, public sharing, Cloudflare/Tailscale auth expansion, or multi-user identity work.
- No broad design-system rewrite or JavaScript framework.

### Deferred to Follow-Up Work

- Phase-2 stream messaging and steering controls from `docs/portal-spec.md` section 7.
- CLI stream/report commands from the parallel CLI card.
- A shared `/media` content-disposition, inline-report, or CSP policy change for true browser inline report HTML rendering, if dogfooding shows the existing attachment policy blocks the iframe use case.
- README/API documentation updates unless a later documentation card requests them.

---

## Context & Research

### Relevant Code and Patterns

- `gallery/server.py` owns FastAPI routes, Jinja template rendering, `web_token_ok`, `_maybe_set_cookie`, `/media/{id}/{filename}`, and existing web routes `/` and `/r/{req_id}`.
- `gallery/templates/base.html`, `gallery/templates/index.html`, and `gallery/templates/request.html` show the current compact server-rendered template style and phone-first layout.
- `gallery/static/style.css` defines the dark/light color variables, card/list patterns, tags, badges, and responsive media behavior to extend.
- `gallery/static/app.js` only activates on `.request-detail`; stream pages should not reuse that class unless they intentionally want request-page behavior.
- `gallery/db.py` already exposes `get_stream_with_posts(slug)`, `get_request(req_id)`, and legacy decision-post dual-write. It does not expose a public list-streams summary helper for the home page.
- `tests/test_api.py` covers existing web auth and request-page behavior; `tests/test_streams_api.py` covers the bearer stream/post API and current media hardening.
- `tests/conftest.py` isolates tests with `GALLERY_DATA_DIR`, `config.init_config(force=True)`, and `db.reset_connection()`.

### Institutional Learnings

- No repo-local `docs/solutions/` directory exists. The applicable local knowledge is in `docs/portal-spec.md`, the two existing Portal plans in `docs/plans/`, current code/tests, and the twf worker policy.
- `docs/plans/2026-07-08-002-feat-streams-posts-http-api-plan.md` intentionally deferred stream web UI to a later card and hardened active-content media as attachment-by-default.

### External References

- External research is not needed. The feature follows existing FastAPI/Jinja/TestClient patterns already present in the repo.

---

## Key Technical Decisions

- Reuse server-rendered Jinja pages instead of adding a client-side app, because the spec and card reject bearer-auth browser JS for this surface.
- Reuse existing web auth exactly like `/` and `/r/{req_id}`: accept cookie or `?token=`, set the cookie when the query token is valid, and return the same missing/invalid token status as existing web routes.
- Build `/s/{slug}` from `db.get_stream_with_posts(slug)` and enrich only the template context in `server.py`: report media view models, decision request lookups, status badges, and post ordering.
- Keep `/api/*` untouched; use API routes only from tests as setup helpers when convenient.
- Do not propagate the long-lived query token into generated media or request links. Set the existing HttpOnly cookie when `?token=...` is valid, rely on that cookie for same-origin links/subresources, and add a no-referrer response policy for stream pages.
- Prefer a small `server.py` stream-summary helper for the index page to stay inside the card's scope fence; do not add a DB helper unless implementation proves the route-local query would be materially worse.
- Treat report iframe rendering as sandboxed markup for this card, not a shared media-policy change. The iframe must omit same-origin/script allowances; if attachment-by-default prevents true browser inline rendering, capture that in SURPRISES and defer the policy decision.

---

## Open Questions

### Resolved During Planning

- Should this card implement stream messages or steering notes? No. The spec marks messages/ask/pull as phase 2, and the card asks for read-only closed streams and no page JS bearer calls.
- Should this card modify CLI/client/dependencies? No. The card explicitly says this runs parallel with the CLI card and must not touch `cli.py`, `client.py`, or `pyproject.toml`.
- Should unknown `/s/{slug}` auto-create streams? No. Auto-create applies to agent post creation, not human web reads.
- Should decision posts create new request rows? No. Decision posts link to existing `/r/{req_id}` pages using the request id stored in post body JSON.

### Deferred to Implementation

- Exact shape of the stream-page view model: choose simple dictionaries that keep templates readable and avoid leaking raw post-body branching into Jinja.
- Exact future media-inline mechanism for report HTML if attachment-by-default blocks real-browser iframe rendering: preserve active-content protections and handle it in a follow-up, not this card.
- Exact empty-state copy for streams with no posts: keep it short and consistent with `index.html`'s existing "Nothing waiting on you." style.

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```mermaid
flowchart TB
    Browser[Phone/browser] --> WebAuth[web_token_ok cookie or query token]
    WebAuth --> StreamRoute[GET /s/{slug}]
    WebAuth --> IndexRoute[GET /]
    StreamRoute --> StreamDB[get_stream_with_posts]
    StreamRoute --> RequestDB[get_request for decision posts]
    IndexRoute --> SummaryQuery[stream summaries for index]
    StreamRoute --> StreamTemplate[templates/stream.html]
    IndexRoute --> IndexTemplate[templates/index.html streams section]
    StreamTemplate --> Media[/media/<post_id>/<filename>]
    StreamTemplate --> RequestPage[/r/<req_id>]
```

The route layer should authenticate first, fetch stream/post data, derive a compact presentation model, and hand that model to Jinja. Templates should render links, badges, iframe/link markup, and empty states only; they should not perform DB lookups or complex type dispatch.

---

## Implementation Units

- U1. **Add stream web route and context assembly**

**Goal:** Add authenticated `/s/{slug}` routing and server-side context building while preserving existing API behavior.

**Requirements:** R1, R2, R3, R4, R5, R6, R7, R9, R10, R11

**Dependencies:** Streams/posts DB and API dependency card landed

**Files:**
- Modify: `gallery/server.py`
- Create: `tests/test_web_streams.py`

**Approach:**
- Add `GET /s/{slug}` as an HTML route near the existing web UI routes.
- Use `web_token_ok(request)` before any stream lookup and `_maybe_set_cookie(response, request)` on successful render.
- Validate the slug with the existing stream slug validation before lookup, and return 404 for missing streams.
- Fetch stream/posts through `db.get_stream_with_posts(slug)`.
- Sort posts newest-first for the web view without changing the API ordering contract.
- Set a no-referrer response policy for the stream page so a `?token=` URL used to establish the cookie is not forwarded by report frames or links.
- Build decision post context by reading `body.request_id`, calling `db.get_request(req_id)`, and mapping request status to a display badge.
- Build report post context from `post["body"]["files"]`, selecting the report HTML/media entry used for link/iframe display.
- Keep missing or malformed post body data from crashing the page; render a minimal "unavailable" state for that post and continue.

**Execution note:** Start with failing `TestClient` coverage for auth, 404, ordering, and decision-link context before adding the route.

**Patterns to follow:**
- `gallery/server.py` `web_index` and `web_request_detail` auth/render/cookie flow.
- `tests/test_api.py` web auth tests for `/?token=...` and `/r/{req_id}?token=...`.

**Test scenarios:**
- Happy path: `GET /s/{slug}?token=<token>` returns 200 for an existing stream and sets `gallery_token`.
- Happy path: a second `GET /s/{slug}` using the cookie from the first response returns 200.
- Happy path: posts render newest-first when the stream contains older and newer posts.
- Happy path: a decision post with `{"request_id": req_id}` links to `/r/{req_id}` and shows a pending badge while the request is open.
- Edge case: missing or invalid token returns 401, matching existing web routes.
- Error path: `GET /s/missing?token=<token>` returns 404 and does not create a stream.
- Edge case: a malformed decision post body does not 500 the stream page.
- Edge case: a report post with no files or malformed `files` body data does not 500 the stream page and renders an unavailable state.

**Verification:**
- The new web route is covered by focused tests and does not require any `/api/*` handler changes.

---

- U2. **Create stream page template and mobile styles**

**Goal:** Render a phone-friendly stream detail page with archived state, report links/iframes, decision links, and clear empty/read-only states.

**Requirements:** R3, R4, R5, R6, R7, R9, R11

**Dependencies:** U1

**Files:**
- Create: `gallery/templates/stream.html`
- Modify: `gallery/templates/base.html`
- Modify: `gallery/static/style.css`
- Test: `tests/test_web_streams.py`

**Approach:**
- Add `stream.html` extending `base.html` and using existing card/list/tag conventions from `index.html` and `request.html`.
- Show stream title, slug, kind, created age, and an archived marker when `closed_at` is present.
- Render an empty state when the stream has no posts.
- For report posts, show title, author, age, a media link, and a sandboxed iframe for the selected HTML/media file. Do not include query tokens in the `href` or `src`; rely on the cookie set by the page response.
- For decision posts, show title, author, age, a link to `/r/{req_id}`, and a status badge. Do not include query tokens in the link.
- Add CSS for stream headers, post lists, report frames, status badges, and archived markers using the existing color variables and compact mobile layout.
- Add a restrictive `sandbox` attribute to report iframes. Do not include `allow-same-origin` or `allow-scripts` in this card.
- Avoid adding page JavaScript unless a tiny enhancement is strictly necessary; no JS framework and no bearer-auth fetches.

**Execution note:** Keep this unit template/style/context-only. Do not expand into media serving policy even if the iframe behavior looks imperfect in a real browser; document that as a follow-up surprise.

**Patterns to follow:**
- `gallery/templates/index.html` request cards and empty states.
- `gallery/templates/request.html` media-link token handling.
- `gallery/static/style.css` `.request-list`, `.request-card`, `.tag`, `.variant-media`, and light-mode override patterns.

**Test scenarios:**
- Happy path: a report post uploaded with `report.html` renders the report title, a link to `/media/<post_id>/<filename>`, and an iframe pointing at the same media URL.
- Happy path: the report media URL is fetchable using the cookie set by the stream page response.
- Happy path: the report iframe includes a `sandbox` attribute without same-origin or script allowances.
- Edge case: rendered report and decision links do not include `token=` query parameters.
- Happy path: after deciding a linked request, the decision post status badge changes from pending to decided.
- Happy path: a closed stream page shows an archived marker and no mutating controls or forms.
- Edge case: a stream with no posts renders a clear empty state.
- Edge case: HTML report media default active-content protections remain unchanged by this card.

**Verification:**
- The stream page is readable on narrow layouts, uses existing visual conventions, and renders report and decision posts without a browser-side bearer token.

---

- U3. **Add streams section to the home page**

**Goal:** Show available streams on `/` with enough metadata for a human to find the relevant permanent stream page.

**Requirements:** R8, R9, R10, R11

**Dependencies:** U1

**Files:**
- Modify: `gallery/server.py`
- Modify: `gallery/templates/index.html`
- Modify: `gallery/static/style.css`
- Test: `tests/test_web_streams.py`

**Approach:**
- Extend `web_index` to add a `streams` context value containing slug, title, kind, post count, latest activity timestamp, and closed/archived state.
- Because there is no public `db.list_streams()` helper in the current scope, implement the smallest read-only summary query inside `server.py` or a private server helper. Keep it clearly isolated and do not touch `gallery/db.py` unless implementation proves the scope tradeoff is unacceptable.
- Order streams by latest activity newest-first, falling back to stream creation time when a stream has no posts.
- Add a home-page section that links each stream card to `/s/<slug>` and shows slug, title, kind, post count, latest activity, and archived state.
- Preserve the existing open and decided request sections and their search behavior.

**Execution note:** Add index tests before template edits so the expected summary fields stay tied to card acceptance rather than incidental markup.

**Patterns to follow:**
- Existing `web_index` context shape and `index.html` request list structure.
- `gallery/db.py` SQL style only as a reference for the route-local summary query.

**Test scenarios:**
- Happy path: `/` with a valid token lists a created stream with slug, title, kind, post count, and latest activity text.
- Happy path: clicking/link markup points to `/s/<slug>`.
- Happy path: a stream with two posts shows post count `2` and sorts ahead of an older stream.
- Edge case: a closed stream appears with an archived marker in the index section.
- Edge case: when no streams exist, the section renders a short empty state and existing request lists still render.

**Verification:**
- The index page acceptance criterion is covered without changing `/api/*` behavior or existing request-list semantics.

---

## System-Wide Impact

- **Interaction graph:** New web routes read from the same SQLite connection and template stack as existing web pages. They also read request rows for decision post badges and media files for report links.
- **Error propagation:** Auth failures should match existing web routes; missing streams and missing media stay 404; malformed post body data should degrade per-post rather than fail the full page.
- **State lifecycle risks:** This card should be read-only for streams. It must not create streams, posts, requests, verdicts, or media as part of page rendering.
- **API surface parity:** `/api/*`, CLI, client helpers, and existing request-page behavior are explicitly unchanged.
- **Integration coverage:** Tests should exercise the real route/template/media/request chain with `TestClient`, not just helper functions.
- **Unchanged invariants:** Stream slugs remain permanent; closed streams remain readable archives; browser pages use cookie/query auth rather than bearer auth; report and decision posts remain created by the existing API/DB surfaces.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| The index streams section needs summary data but no public DB helper exists inside the scope fence. | Keep the summary read isolated in `server.py`, test it through `/`, and report the scope mismatch in SURPRISES. |
| Current `/media` behavior serves HTML attachments, which can fight inline report iframes. | Do not change media policy in this card; render the required link/iframe markup, verify the media URL is fetchable, and report any browser limitation for follow-up. |
| Decision posts can reference request ids that are missing or malformed. | Build defensive presentation context and render an unavailable state instead of raising a server error. |
| Query tokens can leak if copied into generated links, frames, history, or referrers. | Do not render `token=` in stream links or iframe URLs, rely on the HttpOnly cookie, and set a no-referrer response policy on stream pages. |
| Template changes can accidentally trigger request-page JavaScript. | Do not reuse `.request-detail` on stream pages and keep stream behavior server-rendered. |

---

## Documentation / Operational Notes

- No README or deployment updates are required for this card unless the implementation discovers an operator-facing setup change.
- Verification should use the board-specific pytest invocation from the worker context, including the configured uv cache override.

---

## Sources & References

- **Origin:** Trello card `A9oMiXGV`
- **Spec:** `docs/portal-spec.md`
- **Dependency plan:** `docs/plans/2026-07-08-002-feat-streams-posts-http-api-plan.md`
- **DB/migration plan:** `docs/plans/2026-07-08-001-feat-db-migration-portal-schema-plan.md`
- Related code: `gallery/server.py`
- Related code: `gallery/db.py`
- Related templates: `gallery/templates/base.html`, `gallery/templates/index.html`, `gallery/templates/request.html`
- Related styles/scripts: `gallery/static/style.css`, `gallery/static/app.js`
- Related tests: `tests/test_api.py`, `tests/test_streams_api.py`, `tests/conftest.py`
