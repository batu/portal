---
title: "P5c Context-Header: native chrome above producer pages - Plan"
type: feat
date: 2026-07-10
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: trello-card:rZS6JEsx
execution: code
origin: "trello-card:rZS6JEsx"
trello: "https://trello.com/c/rZS6JEsx"
spec: docs/portal-spec.md
---

# P5c Context-Header: native chrome above producer pages - Plan

## Goal Capsule

| Field | Value |
|---|---|
| Objective | Replace the injected bottom "home pill" on producer HTML (view + report pages) with a slim fixed **context header** that shows Portal-home · stream · step · ask · status, fed by optional additive metadata, and degrading gracefully to home + stream (+ status) when no metadata exists. |
| Authority | Trello card `rZS6JEsx` first, then the existing Portal db/server/cli/client/template/test patterns (esp. the just-landed P5b lifecycle + status vocabulary), then `docs/portal-spec.md`. |
| Execution profile | Additive SQLite migration (v5) for request metadata, additive JSON body fields for report metadata, a rendered header fragment injected at the existing byte-injection seam, plus CLI/client/API pass-through and focused tests in the FastAPI Gallery/Portal app. |
| Stop conditions | Files limited to `gallery/server.py`, `gallery/db.py`, `gallery/cli.py`, `gallery/client.py`, `gallery/templates/**`, `tests/**`. DB changes additive only. Metadata is generic vocabulary — no pipeline-specific fields. Do not reintroduce an iframe / `88vh` box (rejected in 75084cd); the producer page keeps owning its layout. If the baseline suite is red before any edit, report it and stop. |
| Completion signal | `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q` is fully green, including new header-render tests (full metadata, graceful-none, both branches, byte-preservation) and the v5 migration round-trip. |

## Product Contract

### Summary

Producer view/report HTML bypasses Portal's templates, so those pages carry zero orientation. The current stopgap injects `_HOME_PILL` bytes (a bottom-left "← Portal" link) into HTML media responses in `get_media` — navigation only, no context. This plan (1) lets requests and report posts carry **optional** generic metadata (`step`, `purpose`, `ask`), (2) upgrades the byte-injection seam from a pill to a **slim fixed native header** rendered above producer HTML on both the view branch and the report branch of `get_media`, showing Portal-home · stream · step · ask · status, and (3) absorbs/removes `_HOME_PILL`. With no metadata the header still shows home + stream (+ status for requests); it is never blank and never breaks producer layout.

### Problem Frame

Live evidence (2026-07-09, Batu's session), repeated verbatim: "what step am I looking at", "I don't know what I am to review", "what does that mean?", plus three escalating requests for a way back to the index. The home pill answers only the last of those — it navigates but tells the reviewer nothing about *what* they are looking at or *what they are being asked to do*. The rejected alternative — an iframe/`88vh` Portal shell wrapping the producer page — was removed in 75084cd because the producer page must own the full tab; reintroducing it is out of scope. So the orientation must ride *above* the producer page as native chrome injected into the same response, not as a wrapping frame.

### Requirements

- R1. Requests accept optional metadata fields `step`, `purpose`, `ask` (each a short free-text string), passed through `gallery/cli.py` → `gallery/client.py` → the `POST /api/requests` API → `db.create_request`, and stored **additively** on the request row. Omitting them leaves the request unchanged from today.
- R2. Report posts accept the same optional `step`, `purpose`, `ask` fields, passed through the CLI report verb → client → `POST /api/streams/{slug}/posts`, and stored **additively** in the post `body_json` (no report schema change).
- R3. `get_media` renders a slim fixed **context header** above producer HTML on **both** branches it currently pills: the report-HTML branch (`_report_html_media_type`) and the view-HTML branch (`_view_html_media_type`).
- R4. The header shows, left-to-right: a Portal-home link (`/`), the owning **stream** (label linking to `/s/<slug>`), the **step**, the **ask**, and the lifecycle **status** (`open` / `decided` / `closed` / `superseded`, the P5b vocabulary) as a labeled chip. Fields with no value are omitted, not rendered blank.
- R5. Graceful degradation: with no metadata the header still shows the Portal-home link + stream + status (status only where the page has a request status). It is never blank and never produces a broken layout. Report pages, which have no request status, omit the status chip and still show home + stream (+ any metadata).
- R6. The header must look deliberate at desktop width (picker-v3 polish bar), be unobtrusive, and never overlap producer content. It is fully self-contained (inline styles, no dependency on Portal's `style.css`, which the sandboxed producer page does not load).
- R7. Producer page content is **byte-preserved apart from the injected header fragment**: the served bytes equal the original file plus exactly the injected fragment, at a single deterministic seam.
- R8. `_HOME_PILL` and `_html_with_home_pill` are removed once the header covers both branches; no producer page still renders the old pill.
- R9. All metadata is generic substrate vocabulary — nothing pipeline-specific (no Trello/stage/verdict-semantics baked into the columns, header, or API). DB changes are additive only.
- R10. Existing green behavior — request/report creation, media serving of non-HTML files, streams/messages/posts, before/after, view verdicts, P5b lifecycle banners and 409 guards, breadcrumbs — is unchanged.

### Acceptance Examples

- AE1. Given `portal post --kind view --title T --step "frame picking" --ask "pick the winning frame" entry.html`, when the request is created, then the request row stores `step="frame picking"` and `ask="pick the winning frame"`, and `GET /api/requests/<id>` / `db.get_request` expose them.
- AE2. Given a view request with `step`/`ask` set and status `open`, when `GET /media/<id>/entry.html` is served, then the response body contains the original producer HTML plus a header fragment containing a `/` home link, the stream label linking to `/s/<slug>`, the step text, the ask text, and a status chip reading `open`.
- AE3. Given a view request with **no** metadata, when its HTML is served, then the header still contains the `/` home link, the stream label, and the status chip, and contains no empty step/ask placeholders.
- AE4. Given a report post created with `--step`/`--ask`, when `GET /media/<post_id>/report.html` is served, then the header contains the `/` home link, the stream label, the step, and the ask, and **no** status chip (reports have no request status).
- AE5. Given any producer HTML file, when it is served through `get_media`, then stripping exactly the injected header fragment yields bytes identical to the original file on disk.
- AE6. Given a decided view request, when its Portal page `/r/<id>` renders (terminal/decided views fall through to the Portal page), then the P5b lifecycle behavior is unchanged; given a still-open view, the media path carries the header with status `open`.
- AE7. Given the full suite, when `pytest -q` runs, then it is green, `_HOME_PILL` no longer exists in `gallery/server.py`, and the media round-trip / view-request tests assert the header rather than the pill.

### Scope Boundaries

- Only `gallery/db.py`, `gallery/server.py`, `gallery/cli.py`, `gallery/client.py`, `gallery/templates/**`, and `tests/**` change.
- No iframe / viewport-box wrapper; the producer page owns its own layout. Do not reintroduce the `88vh` shape removed in 75084cd.
- No new pipeline-specific vocabulary; `step`/`purpose`/`ask` are generic optional strings.
- DB changes are additive only — no destructive column drops, type changes, or rewrites of existing rows. Report metadata rides in the existing `body_json` (no schema change at all for posts).
- No new auth behavior; the header links stay cookie-first / token-free like the pill and breadcrumbs.
- No change to the Portal-side breadcrumb templates (base/request/stream) — those already orient in-template pages; this card is only the producer-HTML chrome.

## Planning Contract

### Assumptions

- P5b landed: `requests` schema is at `user_version == 4`, `db.TERMINAL_STATUSES == ("closed", "superseded")` exists, statuses are `open` / `decided` / `closed` / `superseded`, and terminal views already fall through from `/r/{id}` to the Portal page (so the media-path header is only ever hit for live/open views plus any non-terminal decided view served directly). Verified in `gallery/db.py` and `gallery/server.py` at spawn.
- `db._get_request` returns `dict(row)`, so any new `requests` columns appear automatically on the request dict once the migration adds them — mirrors how P5b's `superseded_by`/`close_reason` surfaced.
- Report post `body_json` is an arbitrary JSON object already round-tripped by `create_post`/`get_post`; adding `step`/`purpose`/`ask` keys to it is additive and needs no migration.
- `Jinja2Templates` (`templates` in `server.py`) autoescapes `.html` templates, so rendering the header from a template safely HTML-escapes producer-supplied metadata (step/ask/purpose, stream title) before it is injected as bytes. This is the deterministic, non-LLM way to prevent metadata from breaking layout or injecting markup.
- The producer HTML is served sandboxed (`Content-Security-Policy: sandbox ...` for reports, `VIEW_HTML_CSP` for views) and does **not** load Portal's `style.css`; the header therefore must be fully self-contained inline styles, exactly as `_HOME_PILL` already is. No `style.css` change is needed or wanted.
- The current pill is injected once, before the last `</body>`. Moving to a top-anchored header changes the seam and the exact bytes; the two existing pill assertions (`tests/test_web_streams.py` round-trip, `tests/test_view_requests.py::test_producer_html_gets_home_pill`) are expected to change and are in-scope (`tests/**`).

### Key Technical Decisions

- KTD1. **Migration v5 adds three nullable TEXT columns to `requests`**: `step`, `purpose`, `ask`, via `_add_column_if_missing` — the exact additive idiom of `_migrate_v4`. Add `_migrate_v5`, `_validate_v5_schema`, extend `_validate_schema_version` with a `version >= 5` branch, append `(5, _migrate_v5)` to `MIGRATIONS`. Report metadata needs **no** migration (rides in `body_json`), keeping the DB change minimal.
- KTD2. **`db.create_request` gains `step`/`purpose`/`ask` keyword params** (default `None`), added to the INSERT column list. `_get_request` needs no change (it does `dict(row)`). Add a tiny `db.get_stream_by_id(stream_id) -> dict | None` helper (slug + title) so the header can resolve the stream label from a request or post `stream_id` without duplicating the raw SQL currently inlined in `web_request_detail`.
- KTD3. **API pass-through is additive and per-branch.** `POST /api/requests` (`create_request`) gains `step`/`purpose`/`ask` `Form(None)` params, bounded via `_bounded_text` and forwarded to `db.create_request`. Report metadata needs no API-signature change: it arrives inside the existing `body` JSON of `POST /api/streams/{slug}/posts` and is persisted as-is in `body_json`.
- KTD4. **CLI/client mirror the existing thin wrappers.** `cmd_post` adds `--step`/`--purpose`/`--ask` and folds them into its `fields` dict (forwarded by `post_multipart`). `cmd_report` adds the same three flags and folds them into the `body` dict passed to `client.create_stream_post`. No new client function is required — both paths already forward a `fields`/`body` mapping.
- KTD5. **The header is a rendered template fragment, not a bytes constant.** Add `gallery/templates/context_header.html`: a single slim bar with fully self-contained inline styles (no `style.css` dependency, max z-index like the pill), rendering the home link, an optional stream crumb (`/s/<slug>`), optional step, optional ask, and an optional status chip. Render it in `server.py` via `templates.get_template("context_header.html").render(**ctx)` and `.encode("utf-8")`. Autoescape handles metadata safety.
- KTD6. **Replace `_html_with_home_pill` with `_html_with_context_header(path, media_type, headers, header_bytes)`** that injects `header_bytes` at a single deterministic seam: immediately **after the opening `<body ...>` tag** (regex `<body[^>]*>`), falling back to prepending when no `<body>` exists. The fragment is `[fixed slim bar] + [equal-height spacer div]` so normal-flow producer content starts below the bar and is not overlapped (R6), while the served bytes remain original-plus-fragment (R7). Delete `_HOME_PILL` and `_html_with_home_pill`.
- KTD7. **Two call sites assemble context deterministically** in `get_media`. Report branch: load the post (already fetched by `_report_html_media_type`; re-use or re-fetch `db.get_post(req_id)`), resolve stream via `get_stream_by_id(post["stream_id"])`, read `step`/`purpose`/`ask` from `post["body"]`, status = `None`. View branch: load `db.get_request(req_id)`, resolve stream via its `stream_id`, read the new columns, status = `r["status"]`. A small `_context_header_for_*` helper per branch keeps `get_media` readable.
- KTD8. **Overlap is verified against the real picker-v3 page, not assumed.** The spacer handles normal-flow producer pages; a producer page that uses its own viewport-fixed/absolute full-bleed layout could still render under the bar's edge (the pill had the same class of caveat). This residual is called out as a mandatory visual check at desktop width before handoff — the header must look deliberate and not overlap on an actual view page. If a full-bleed producer page overlaps, the implementer tunes the fragment (e.g. keeps the bar slim and confirms acceptable) rather than reintroducing a wrapper box.

### Relevant Code and Patterns

- `gallery/db.py`: `SCHEMA`, `MIGRATIONS`, `_migrate_v4`/`_validate_v4_schema`, `_add_column_if_missing`, `_validate_schema_version`, `create_request` (INSERT), `_get_request` (`dict(row)`), `get_stream` (slug lookup), `TERMINAL_STATUSES`.
- `gallery/server.py`: `_HOME_PILL` + `_html_with_home_pill` (lines ~181–198 — the seam being upgraded), `_report_html_media_type`, `_view_html_media_type`, `get_media` (the two HTML branches at ~859–864), `create_request` endpoint (Form params, `_bounded_text`), `create_stream_post` (body pass-through), `web_request_detail` (the inlined `SELECT slug, title FROM streams` to be factored into `get_stream_by_id`), `templates` (`Jinja2Templates`).
- `gallery/client.py`: `post_multipart` (fields forwarding), `create_stream_post` (`body` forwarding) — both already carry arbitrary maps, so no new client function.
- `gallery/cli.py`: `cmd_post` (`fields` dict + `p.add_argument` registration for the `post` subparser), `cmd_report` (`body={}` today), `_exit_client_error`.
- `gallery/templates/`: `base.html`/`request.html`/`stream.html` for the in-Portal header look (visual reference only — do not modify); new `context_header.html`.
- `tests/test_view_requests.py::test_producer_html_gets_home_pill`, `tests/test_web_streams.py` media round-trip (the two pill assertions to migrate to header assertions); `tests/test_db_migrations.py` (v4 round-trip + `user_version` asserts to extend to v5); `tests/test_api.py`, `tests/test_cli.py` for API/CLI metadata pass-through fixtures.
- Board lessons: run tests as `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q`; after writing this plan doc, confirm it is committed (`git status --porcelain` empty) before handoff.

## Implementation Units

### U1. Additive v5 migration for request metadata

- **Goal:** Persist optional `step`, `purpose`, `ask` on `requests` without disturbing existing rows.
- **Requirements:** R1, R9; covers AE1.
- **Dependencies:** None.
- **Files:** Modify `gallery/db.py`; Test `tests/test_db_migrations.py`.
- **Approach:** Add `_migrate_v5` calling `_add_column_if_missing(conn, "requests", "step", "step TEXT")`, `... "purpose", "purpose TEXT"`, `... "ask", "ask TEXT"`. Add `_validate_v5_schema` asserting the three columns exist. Extend `_validate_schema_version` with a `version >= 5` branch. Append `(5, _migrate_v5)` to `MIGRATIONS`. Add the three columns to the base `SCHEMA` so fresh DBs are born correctly (still reaching v5 via the migration/`user_version` path).
- **Patterns to follow:** `_migrate_v4` / `_validate_v4_schema` exactly.
- **Test scenarios:** Legacy v4 db upgrades to `user_version == 5` with prior request/variant/verdict rows preserved and the three columns null; fresh db reports `user_version == 5` with the three columns; existing `user_version == 4` assertions updated to 5.
- **Verification:** Migration tests pass; `db._user_version` is 5 after connect.

### U2. db.create_request metadata params + get_stream_by_id helper

- **Goal:** Store request metadata on creation and expose a stream-by-id lookup for the header.
- **Requirements:** R1, R4; supports AE1, AE2.
- **Dependencies:** U1.
- **Files:** Modify `gallery/db.py`; Test `tests/test_api.py` or a focused db test.
- **Approach:** Add `step: str | None = None`, `purpose: str | None = None`, `ask: str | None = None` to `create_request`, extend the INSERT column list and value tuple. Confirm `_get_request` returns the new keys (it does `dict(row)` — assert in a test). Add `get_stream_by_id(stream_id: str) -> dict | None` returning `{"slug", "title", ...}` (thin wrapper over `SELECT * FROM streams WHERE id = ?` under `_lock`), and refactor `web_request_detail`'s inlined stream lookup to use it (surgical, keeps behavior identical).
- **Patterns to follow:** `create_request` INSERT shape; `get_stream` / `get_post` connection+lock idiom.
- **Test scenarios:** `create_request(..., step=..., ask=...)` then `get_request` returns those values; omitting them yields `None`; `get_stream_by_id` returns slug/title for a known stream and `None` for an unknown id.
- **Verification:** db/API tests pass; `web_request_detail` still renders the stream crumb unchanged.

### U3. API metadata pass-through

- **Goal:** Accept `step`/`purpose`/`ask` on request creation, and persist them on report posts via the existing body.
- **Requirements:** R1, R2, R9; covers AE1, AE4.
- **Dependencies:** U2.
- **Files:** Modify `gallery/server.py`; Test `tests/test_api.py`.
- **Approach:** `POST /api/requests`: add `step: str | None = Form(None)`, `purpose: str | None = Form(None)`, `ask: str | None = Form(None)`; bound each with `_bounded_text(..., max_length=...)` when present (choose a sane cap, e.g. `MAX_TITLE_LENGTH`); forward to `db.create_request`. Report posts (`POST /api/streams/{slug}/posts`): **no signature change** — `step`/`purpose`/`ask` arrive inside the client-provided `body` JSON and are already persisted in `body_json`; confirm `get_post` surfaces them under `post["body"]`.
- **Patterns to follow:** Existing `Form(None)` params + `_bounded_text` in `create_request`; `create_stream_post` body handling.
- **Test scenarios:** Creating a request with metadata returns 200 and `GET /api/requests/<id>` shows the fields; creating without metadata is unchanged; a report post whose body carries the fields round-trips them via `GET .../posts/<id>`; over-long metadata is rejected/bounded per `_bounded_text`.
- **Verification:** API tests pass.

### U4. CLI + client metadata flags

- **Goal:** Producers set `step`/`purpose`/`ask` from the CLI for both requests and reports.
- **Requirements:** R1, R2; covers AE1, AE4.
- **Dependencies:** U3.
- **Files:** Modify `gallery/cli.py` (and `gallery/client.py` only if a helper is cleaner); Test `tests/test_cli.py`.
- **Approach:** Register `--step`, `--purpose`, `--ask` (each `default=None`) on the `post` subparser and the report subparser. In `cmd_post`, add them to the `fields` dict (forwarded by `post_multipart`; `None` values are already dropped/handled by the existing field serialization — confirm). In `cmd_report`, build `body = {k: v for k, v in {"step":..., "purpose":..., "ask":...}.items() if v is not None}` and pass it as `body=` to `client.create_stream_post` (replacing the current `body={}`).
- **Patterns to follow:** Existing `fields` assembly in `cmd_post`; `p.add_argument` registration block; `create_stream_post(body=...)` call.
- **Test scenarios:** `portal post --kind view --step ... --ask ...` results in a request whose API view shows the metadata; `portal report --step ... --ask ...` results in a post whose body carries them; omitting the flags leaves both paths behaving as today. Follow whatever server-injection/fixture pattern `tests/test_cli.py` already uses.
- **Verification:** CLI tests pass.

### U5. Context-header template + injector, replacing the home pill

- **Goal:** Render a slim fixed native header above producer HTML on both `get_media` branches; remove the pill.
- **Requirements:** R3, R4, R5, R6, R7, R8; covers AE2, AE3, AE4, AE5.
- **Dependencies:** U2 (get_stream_by_id, request metadata surfaced).
- **Files:** Add `gallery/templates/context_header.html`; Modify `gallery/server.py`; Test `tests/test_view_requests.py`, `tests/test_web_streams.py`.
- **Approach:**
  - `context_header.html`: one slim bar, fully self-contained inline styles (max z-index, blur/dark treatment consistent with the old pill but at the top edge, desktop-first spacing). Structure: `<a href="/">← Portal</a>` · optional `<a href="/s/{{ stream.slug }}">{{ stream.label }}</a>` · optional `Step: {{ step }}` · optional `Ask: {{ ask }}` · optional status chip `{{ status }}` with a status-colored accent. Each optional segment is wrapped in `{% if %}` so absent fields render nothing. Autoescape keeps producer metadata safe. Immediately after the bar, emit an equal-height spacer div so normal-flow content is not overlapped.
  - `server.py`: add `_context_header_bytes(*, stream, step, purpose, ask, status)` → `templates.get_template("context_header.html").render(...).encode("utf-8")`. Add `_html_with_context_header(path, media_type, headers, header_bytes)` that inserts `header_bytes` right after the opening `<body ...>` tag (regex `<body[^>]*>`; fallback: prepend). Delete `_HOME_PILL` and `_html_with_home_pill`.
  - Wire both branches of `get_media`: report branch resolves post → stream + body metadata, `status=None`; view branch resolves request → stream + column metadata, `status=r["status"]`.
- **Patterns to follow:** `_HOME_PILL` self-contained inline-style approach and single-seam injection; `Jinja2Templates` usage in `server.py`; token-free `/` and `/s/<slug>` links (breadcrumb hygiene).
- **Test scenarios:** view HTML with full metadata → header contains `/`, `/s/<slug>`, step, ask, and status chip; view HTML with no metadata → header contains `/`, stream, status chip and no empty step/ask; report HTML with metadata → header contains `/`, stream, step, ask and **no** status chip; byte-preservation: removing exactly the injected fragment reproduces the on-disk bytes; header links contain no `token=`; both branches keep their CSP headers.
- **Verification:** New/updated render tests pass; `grep _HOME_PILL gallery/server.py` returns nothing.

### U6. Migrate existing pill tests + fill coverage

- **Goal:** Retire pill assertions and cover the header contract fully.
- **Requirements:** R7, R8, R10; covers AE5, AE7.
- **Dependencies:** U5.
- **Files:** Test `tests/test_view_requests.py`, `tests/test_web_streams.py`, plus wherever request/report render coverage lives.
- **Approach:** Rewrite `test_producer_html_gets_home_pill` (rename to reflect the header) to assert the header markup on both the view and report media responses. Update the `tests/test_web_streams.py` media round-trip: the old `media.content.startswith(b"<html><body>Report pass")` and `endswith(b"</body></html>")` assumptions change because the fragment is injected after `<body>` — assert instead that the original producer bytes are present and that the header fragment appears once, deriving the byte-preservation check from the new single seam. Add a graceful-degradation test (request/report with no metadata) and a full-metadata test.
- **Patterns to follow:** Existing `client`/`token`/`auth_headers` fixtures and rendered-HTML assertions in those files.
- **Test scenarios:** As in U5, expressed as concrete assertions; plus a regression assert that non-HTML media (image/video) is served with no header and unchanged bytes.
- **Verification:** Full suite green; no assertion still references the pill.

## Verification Contract

| Gate | Applies to | Done signal |
|---|---|---|
| Migration round-trip | U1 | Legacy v4 db upgrades to `user_version == 5`, prior rows preserved, `step`/`purpose`/`ask` null. |
| db + API pass-through | U2, U3 | `create_request` stores/returns metadata; report body round-trips `step`/`purpose`/`ask`; over-long values bounded. |
| CLI pass-through | U4 | `portal post` / `portal report` with the new flags produce request/post metadata; omitting them is unchanged. |
| Header render | U5, U6 | Both branches render the header (home + stream + optional step/ask + status where applicable); graceful with no metadata; report branch omits status. |
| Byte-preservation | U5, U6 | Served producer HTML equals original bytes plus exactly the injected fragment at the single seam; non-HTML media unchanged. |
| Pill removal | U5, U6 | `_HOME_PILL` / `_html_with_home_pill` gone from `gallery/server.py`; no test references the pill. |
| Desktop visual check | U5 (KTD8) | On a real live/open view page at desktop width, the header looks deliberate and does not overlap producer content. |
| Full suite | all | `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q` fully green. |
| Diff boundary | all | `git status --porcelain` touches only `gallery/db.py`, `gallery/server.py`, `gallery/cli.py`, `gallery/client.py`, `gallery/templates/**`, and `tests/**`. |

## Definition of Done

- Migration v5 is additive, mirrors the v4 pattern, and `test_db_migrations.py` proves the legacy v4→v5 round-trip and `user_version == 5`.
- `db.create_request` accepts and stores `step`/`purpose`/`ask`; `get_stream_by_id` exists and `web_request_detail` uses it with unchanged behavior.
- `POST /api/requests` accepts the three optional metadata fields; report metadata rides in the post body with no report schema change.
- `gallery/cli.py` `post` and report verbs expose `--step`/`--purpose`/`--ask`, following the existing field/body assembly.
- `get_media` renders a slim fixed self-contained context header above producer HTML on both the report and view branches, showing Portal-home · stream · step · ask · status, degrading gracefully to home + stream (+ status) with no metadata, and never overlapping producer content at desktop width.
- Producer HTML is byte-preserved apart from the single injected header fragment; `_HOME_PILL` and `_html_with_home_pill` are removed.
- Existing pill tests are migrated to header assertions, new header tests cover full-metadata / graceful-none / both branches / byte-preservation, and the P5b lifecycle + breadcrumb behavior is untouched.
- The full pytest command passes with the `UV_CACHE_DIR` override, and the diff stays within the allowed files.
