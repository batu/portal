---
title: "P5b Lifecycle: close/supersede verbs + verdict lock - Plan"
type: feat
date: 2026-07-09
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: trello-card:3sGqaMuU
execution: code
origin: "trello-card:3sGqaMuU"
trello: "https://trello.com/c/3sGqaMuU"
spec: docs/portal-spec.md
---

# P5b Lifecycle: close/supersede verbs + verdict lock - Plan

## Goal Capsule

| Field | Value |
|---|---|
| Objective | Give requests explicit lifecycle verbs (`close`, `supersede`), make closed/superseded request pages defend themselves (banner + 409 on decide), and lock verdicts so an accidental re-decide is refused unless explicitly opted in. |
| Authority | Trello card `3sGqaMuU` first, then existing Portal db/server/cli/client/template/test patterns, then `docs/portal-spec.md`. |
| Execution profile | Additive SQLite migration (v4) plus new endpoints, client methods, CLI subcommands, template banners, and focused tests in the FastAPI Gallery/Portal app. |
| Stop conditions | Files limited to `gallery/db.py`, `gallery/server.py`, `gallery/cli.py`, `gallery/client.py`, `gallery/templates/**`, `tests/**`. DB changes additive only. Do not add pipeline-specific logic to Portal; views/reports stay self-contained producer HTML. Do not break the media home-pill injection tests. If the baseline suite is red before any edit, report it and stop — do not fix out of scope. |
| Completion signal | `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q` is fully green, including new lifecycle tests and the migration round-trip test. |

## Product Contract

### Summary

Requests currently only move `open -> decided`. There is no first-class way to retire a stale request, and a stale/superseded request page silently accepts a verdict, so a mis-click on an old picker page is recorded as a real decision. This plan adds two persisted lifecycle states (`closed`, `superseded`) reached through explicit verbs across CLI/client/HTTP, makes closed/superseded request pages render a defensive banner and reject decides with 409, and gates re-decides behind an explicit `redecide: true` flag while preserving latest-wins semantics.

### Problem Frame

Live evidence (2026-07-09, Batu's session):
1. A click on a stale, superseded picker page was recorded as "ratify" when send-back was meant — superseded pages silently accept verdicts.
2. There was no producer close/supersede verb, so the conductor closed 8 stale requests by fabricating fake verdicts.
3. Re-decides are silent latest-wins with no guard, so an accidental second decide overwrites the real one with no friction.

The rejected alternative — leaving lifecycle to producer convention — already failed live. Lifecycle must be enforced by the substrate, not by convention.

### Requirements

- R1. A request can be **closed** with a reason and no fabricated verdict. Closing sets a persisted `closed` status and stores the reason.
- R2. A request can be **superseded** by a named successor request. Superseding sets a persisted `superseded` status and stores the successor request id.
- R3. Both verbs are reachable through the CLI (`gallery/cli.py`), the HTTP client (`gallery/client.py`), and the HTTP API (`gallery/server.py`), following the existing verb/route/client patterns.
- R4. The lifecycle status and its associated data (close reason, successor id) are persisted via an **additive** migration that mirrors the existing `MIGRATIONS` + `_validate_v*` + `test_db_migrations.py` pattern, and existing rows survive the upgrade unchanged.
- R5. The request page renders a prominent banner for lifecycle states: `Superseded — live version: <link to successor request>` for superseded, and `Closed: <reason>` for closed. The decide UI is not offered for these requests.
- R6. The decide endpoints (`POST /api/requests/{req_id}/verdict` and `POST /r/{req_id}/decide`) return **409** for closed or superseded requests. For superseded, the 409 error payload carries the successor id; for closed, it carries the reason.
- R7. Once a verdict exists for a request, a further decide returns **409** with a `verdict_count` in the error payload, unless the decide payload carries an explicit `redecide: true`.
- R8. When `redecide: true` is present, the existing latest-wins re-decide behavior is preserved (re-decidability is a ratified feature — gated, not removed).
- R9. The index open list contains exactly requests genuinely pending a decision: `open` status only, excluding `decided`, `closed`, and `superseded`. Closed/superseded requests are surfaced on the index (not silently vanished) without polluting the open list.
- R10. Existing green behavior — request creation, media serving, the media home-pill injection, streams/messages/posts, before/after, view verdicts — is unchanged except where the verdict lock intentionally requires the new `redecide` flag.

### Acceptance Examples

- AE1. Given an open request, when `portal close <id> --reason "stale"` runs, then the request status becomes `closed`, the reason is stored, and no verdict row is created.
- AE2. Given requests A and B, when `portal supersede <A> --successor <B>` runs, then A's status becomes `superseded` and A's stored successor is B.
- AE3. Given a superseded request A (successor B), when `GET /r/<A>` is rendered, then the page shows a "Superseded — live version" banner linking to `/r/<B>` and offers no decide controls.
- AE4. Given a superseded request A (successor B), when `POST /r/<A>/decide` or `POST /api/requests/<A>/verdict` is called, then the response is 409 and the error payload contains B's id.
- AE5. Given a closed request, when a decide is attempted, then the response is 409 and the error payload contains the close reason.
- AE6. Given a request that already has one verdict, when a decide is posted without `redecide: true`, then the response is 409 and the error payload contains `verdict_count` (the number of existing verdicts).
- AE7. Given a request that already has one verdict, when a decide is posted with `redecide: true`, then the response is 200 and the latest verdict wins.
- AE8. Given one open, one decided, one closed, and one superseded request, when the index renders, then the open list contains only the open request, and the closed/superseded requests are still visible somewhere on the index.
- AE9. Given a legacy database at `user_version` < 4, when the app opens it, then it migrates to v4, all prior request/variant/verdict rows are preserved, and the new lifecycle columns default to null/open.

### Scope Boundaries

- Only `gallery/db.py`, `gallery/server.py`, `gallery/cli.py`, `gallery/client.py`, `gallery/templates/**`, and `tests/**` change.
- No pipeline-specific logic in Portal; Portal stores lifecycle state generically and never interprets producer semantics.
- Views and reports remain self-contained producer HTML; no change to how view/report HTML is served or to the home-pill injection.
- DB changes are additive only — no destructive column drops, type changes, or data rewrites of existing rows.
- No new notification behavior, no auth changes.

## Planning Contract

### Assumptions

- The `requests.status` column already exists (`'open'` default, plus `'decided'`). New states `'closed'` and `'superseded'` are additional string values in that same column; the migration adds only the *associated data* columns, not a new status column. State assumption explicitly: no CHECK constraint is added to `status` (the existing column has none, and adding one would be a non-additive rewrite).
- `_apply_verdict` in `gallery/server.py` is the single shared chokepoint for both decide endpoints, so the 409 lifecycle guard and the verdict lock both belong there (deterministic, not per-route).
- `HTTPException(detail=<dict>)` is serialized by FastAPI into `{"detail": {...}}`, and the CLI client (`GalleryClientError`) already surfaces `detail`, so structured 409 payloads (successor id / reason / verdict_count) can ride in `detail`.
- `db.open_count()` and `db.list_requests(status="open")` already key on `status = 'open'`, so R9's open-list purity for the new states is automatic; the work is surfacing closed/superseded on the index and adding an explicit test.
- The verdict lock is an intentional behavior change: existing tests that re-decide without a flag (`tests/test_api.py` re-post step, `tests/test_view_requests.py::test_view_verdict_payload_latest_wins`) must be updated to send `redecide: true`. This is in-scope (`tests/**`) and is not a regression.

### Key Technical Decisions

- KTD1. **Migration v4 adds two nullable columns to `requests`**: `superseded_by TEXT REFERENCES requests(id)` and `close_reason TEXT`, via `_add_column_if_missing` (the exact additive idiom used by `_migrate_v1`/`_migrate_v3`). Add `_migrate_v4`, `_validate_v4_schema`, extend `_validate_schema_version`, and append `(4, _migrate_v4)` to `MIGRATIONS`. Bump the expected `user_version` in `test_db_migrations.py` assertions from 3 to 4 and add a v4 round-trip test.
- KTD2. **Lifecycle transitions live in `db.py` as small guarded functions** mirroring `record_verdict`/`close_stream`: `close_request(req_id, reason)` and `supersede_request(req_id, successor_id)`, each taking `_lock`, doing a single UPDATE, committing, and returning the fresh request. `close_request` raises a not-found `ValueError` for a missing id; `supersede_request` additionally rejects a missing successor and self-supersede. Closed and superseded are terminal: attempting to close or supersede an already closed/superseded request raises so the state can't be silently flipped.
- KTD3. **The decide guard is centralized in `_apply_verdict`.** After loading the request and before recording: (a) if status is `closed` or `superseded`, raise `HTTPException(409, detail={...})` carrying successor id or reason; (b) else count existing verdicts and, if > 0 and `body.get("redecide") is not True`, raise `HTTPException(409, detail={"error": "verdict_exists", "verdict_count": n})`. Add `db.count_verdicts(req_id)`.
- KTD4. **New HTTP endpoints are bearer-authed JSON POSTs** matching the existing shape: `POST /api/requests/{req_id}/close` (body `{"reason": ...}`) and `POST /api/requests/{req_id}/supersede` (body `{"successor": ...}`), each `require_api_token`, validate the body, translate `db` `ValueError`s into 404/400/409, and return the updated request. There is no web (cookie) lifecycle endpoint — closing/superseding is a producer/operator action, not an in-browser one.
- KTD5. **Client + CLI mirror the existing thin wrappers.** `client.close_request(...)` / `client.supersede_request(...)` use `post_json`; CLI adds `portal close <id> --reason ...` and `portal supersede <id> --successor <request_id>` in the same `sub.add_parser` + `cmd_*` + dispatch-dict style, printing the JSON result and exiting non-zero on `GalleryClientError`.
- KTD6. **Template banners reuse existing note/banner classes** (`.verdict-banner`, `.archive-note`) rather than introducing a new visual system. The superseded banner links to `/r/<successor>` (token-free, cookie-auth like other web nav). Because `can_decide` already requires `status == "open"`, closed/superseded requests already suppress the decide panel; the change is adding the explicit banner and passing `r.superseded_by` / `r.close_reason` through the existing request context.
- KTD7. **Index surfacing stays minimal and keeps `open` pure.** Add a small collapsed "Closed & superseded" section to `index.html` (same card markup as the decided list, with a status tag), fed by a focused `db.list_requests` call per state or a combined query. The open list query is unchanged, guaranteeing R9. Chosen over broadening the "Decided" list because that list is search-driven and semantically "decided".

### Relevant Code and Patterns

- `gallery/db.py`: `MIGRATIONS`, `_migrate_v3`/`_validate_v3_schema`, `_add_column_if_missing`, `record_verdict`, `close_stream`, `list_requests`, `open_count`, `_get_request` (request dict shape returned to templates/API).
- `gallery/server.py`: `_apply_verdict` (shared decide path), `post_verdict` + `web_decide` (the two decide routes), `close_stream` route (verb-route pattern), `web_index` (index context), `web_request_detail` (request context), `HTTPException` detail usage, `require_api_token`.
- `gallery/client.py`: `post_json`, `close_stream` (thin verb wrapper), `GalleryClientError` (surfaces `detail`).
- `gallery/cli.py`: `cmd_stream`/`cmd_status`, `sub.add_parser` registration, dispatch dict in `main`, `_exit_client_error`.
- `gallery/templates/request.html`: `verdict-banner`, `archive-note`, `can_decide`, `back` context; `gallery/templates/index.html`: open/decided/streams sections.
- `tests/test_db_migrations.py`: legacy-db round-trip + `user_version` assertions + `record_verdict` guard tests (the v4 test mirrors these).
- `tests/test_api.py`, `tests/test_view_requests.py`, `tests/test_before_after.py`, `tests/test_web_streams.py`: existing decide/verdict/render assertions and the `auth_headers`/`client`/`token` fixtures.
- Board lesson: run tests as `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q`.

## Implementation Units

### U1. Additive v4 migration for lifecycle columns

- **Goal:** Persist `close_reason` and `superseded_by` on `requests` without disturbing existing rows.
- **Requirements:** R4; supports R1, R2; covers AE9.
- **Dependencies:** None.
- **Files:** Modify `gallery/db.py`; Test `tests/test_db_migrations.py`.
- **Approach:** Add `_migrate_v4` calling `_add_column_if_missing(conn, "requests", "superseded_by", "superseded_by TEXT REFERENCES requests(id)")` and `_add_column_if_missing(conn, "requests", "close_reason", "close_reason TEXT")`. Add `_validate_v4_schema` asserting both columns exist. Extend `_validate_schema_version` with a `version >= 4` branch and append `(4, _migrate_v4)` to `MIGRATIONS`. Include the new columns in the base `SCHEMA` so fresh DBs are born at the right shape (still v4 via the migration/`user_version` path).
- **Patterns to follow:** `_migrate_v3` / `_validate_v3_schema` exactly.
- **Test scenarios:** Legacy v3 db upgrades to `user_version == 4` with prior requests/variants/verdicts preserved and new columns null; fresh db reports `user_version == 4` and has both columns; existing `user_version` assertions updated 3 -> 4.
- **Verification:** Migration tests pass; `db._user_version` is 4 after connect.

### U2. Lifecycle transition functions in db.py

- **Goal:** Deterministic, guarded `close`/`supersede` state changes.
- **Requirements:** R1, R2; covers AE1, AE2.
- **Dependencies:** U1.
- **Files:** Modify `gallery/db.py`; Test `tests/test_db_migrations.py` (or a new `tests/test_lifecycle.py`).
- **Approach:** `close_request(req_id, reason)` — under `_lock`, load request (raise `ValueError("request not found: ...")` if missing), reject if already `closed`/`superseded`, `UPDATE requests SET status='closed', close_reason=? WHERE id=?`, commit, return fresh request. `supersede_request(req_id, successor_id)` — load request (missing -> raise), reject self-supersede and already-terminal state, verify successor exists (raise a distinct "successor not found" `ValueError`), `UPDATE requests SET status='superseded', superseded_by=? WHERE id=?`, commit, return fresh request. Add `count_verdicts(req_id) -> int` (`SELECT COUNT(*) FROM verdicts WHERE request_id=?`). Ensure `_get_request` returns `superseded_by` and `close_reason` (it already does `dict(row)`, so they appear once the columns exist — confirm and assert in a test).
- **Patterns to follow:** `close_stream`, `record_verdict`, `open_count`.
- **Test scenarios:** close sets status/reason and creates no verdict; supersede sets status/successor; supersede with unknown successor raises; self-supersede raises; close/supersede on an already-terminal request raises; `count_verdicts` returns correct counts.
- **Verification:** db-level tests pass.

### U3. HTTP endpoints for close and supersede

- **Goal:** Expose the verbs over the bearer-authed JSON API.
- **Requirements:** R3; supports R1, R2.
- **Dependencies:** U2.
- **Files:** Modify `gallery/server.py`; Test `tests/test_api.py`.
- **Approach:** Add `POST /api/requests/{req_id}/close` and `POST /api/requests/{req_id}/supersede`, each `require_api_token`, parse a JSON object body (`_json_object_body`), validate `reason` / `successor` as bounded non-empty strings, call the db function, and map `ValueError` to status: not-found -> 404, self/invalid -> 400, already-terminal -> 409. Return the updated request dict (same shape as `get_request`).
- **Patterns to follow:** `close_stream` route, `_bounded_text`, `_message_mutation_status` style error mapping.
- **Test scenarios:** close returns 200 + closed status; supersede returns 200 + successor set; close/supersede unknown request -> 404; supersede unknown successor -> 404/400; supersede self -> 400; second close/supersede on terminal request -> 409; endpoints reject missing bearer token -> 401.
- **Verification:** API tests pass.

### U4. Decide guard: 409 on closed/superseded + verdict lock

- **Goal:** Closed/superseded pages refuse verdicts; re-decide requires an explicit flag.
- **Requirements:** R6, R7, R8; covers AE4, AE5, AE6, AE7.
- **Dependencies:** U2.
- **Files:** Modify `gallery/server.py`; Test `tests/test_api.py`, `tests/test_view_requests.py`, `tests/test_before_after.py`.
- **Approach:** In `_apply_verdict`, after the 404 check: if `r["status"] == "superseded"`, raise `HTTPException(409, detail={"error": "superseded", "successor": r.get("superseded_by")})`; if `r["status"] == "closed"`, raise `HTTPException(409, detail={"error": "closed", "reason": r.get("close_reason")})`. Then `n = db.count_verdicts(req_id)`; if `n > 0 and body.get("redecide") is not True`, raise `HTTPException(409, detail={"error": "verdict_exists", "verdict_count": n})`. Keep the existing selection/payload validation and `record_verdict` call for the allowed path. **Update existing re-decide tests** to pass `redecide: true`: the re-post step in `tests/test_api.py::test_create_and_decide_flow` and `tests/test_view_requests.py::test_view_verdict_payload_latest_wins`. (`test_before_after.py`'s first decide uses an invalid index that is rejected before a verdict is recorded, so its subsequent valid decide is a first verdict and needs no flag — confirm during implementation.)
- **Patterns to follow:** Existing `HTTPException` raises in `_apply_verdict`; FastAPI dict-detail serialization.
- **Test scenarios:** decide on superseded -> 409 with successor id in `detail`; decide on closed -> 409 with reason in `detail`; second decide without flag -> 409 with `verdict_count`; second decide with `redecide: true` -> 200 and latest wins; first decide (no prior verdict) still succeeds without the flag; both the bearer route and the cookie `/r/{id}/decide` route enforce identically.
- **Verification:** New guard tests pass; updated existing re-decide tests pass with the flag.

### U5. Client + CLI verbs

- **Goal:** Producer-facing `close`/`supersede` through the HTTP client and CLI.
- **Requirements:** R3; covers AE1, AE2.
- **Dependencies:** U3.
- **Files:** Modify `gallery/client.py`, `gallery/cli.py`; Test `tests/test_cli.py`.
- **Approach:** `client.close_request(base_url, token, req_id, reason)` and `client.supersede_request(base_url, token, req_id, successor)` via `post_json` to the U3 routes (quote the id path segment as other client methods do). CLI: register `close` (`<id>`, required `--reason`) and `supersede` (`<id>`, required `--successor`) subparsers; `cmd_close`/`cmd_supersede` call the client, print `json.dumps(result)`, and use `_exit_client_error` on failure; add both to the dispatch dict in `main`.
- **Patterns to follow:** `client.close_stream`, `cmd_stream`, existing `sub.add_parser` registration and dispatch dict.
- **Test scenarios:** `portal close <id> --reason ...` prints the closed request JSON and exits 0; `portal supersede <id> --successor <b>` prints the superseded request JSON; client/API errors exit non-zero with a stderr message. Follow whatever server-injection/fixture pattern `tests/test_cli.py` already uses.
- **Verification:** CLI tests pass.

### U6. Request-page banners

- **Goal:** Closed/superseded request pages defend themselves visually.
- **Requirements:** R5; covers AE3.
- **Dependencies:** U2.
- **Files:** Modify `gallery/templates/request.html` (and `gallery/static/style.css` only if a lifecycle banner needs a distinct accent); Test `tests/test_api.py` or `tests/test_before_after.py` (rendered-page assertions).
- **Approach:** In `request.html`, add a banner block near the existing `verdict-banner`: when `r.status == "superseded"`, render "Superseded — live version:" with a link to `/r/{{ r.superseded_by }}`; when `r.status == "closed"`, render "Closed: {{ r.close_reason }}". Reuse `.verdict-banner`/`.archive-note` styling. `web_request_detail` already passes the full request dict `r`, which now includes `superseded_by`/`close_reason` (U1/U2), so no route change is required beyond confirming those keys are present.
- **Patterns to follow:** Existing `verdict-banner` and `archive-note` blocks; token-free web links.
- **Test scenarios:** superseded request page HTML contains the banner and an `/r/<successor>` link and no decide button; closed request page HTML contains the reason and no decide button; an open request page is unchanged.
- **Verification:** Rendered-page tests pass.

### U7. Index surfacing + open-list purity

- **Goal:** Open list = only pending requests; closed/superseded still visible.
- **Requirements:** R9; covers AE8.
- **Dependencies:** U2.
- **Files:** Modify `gallery/server.py` (`web_index` context), `gallery/templates/index.html`; Test `tests/test_api.py` (or the existing index-render test home).
- **Approach:** Confirm `web_index` open list stays `db.list_requests(status="open")`. Add a small "Closed & superseded" section: fetch those requests (`list_requests(status="closed")` + `list_requests(status="superseded")`, or one call per state) and render them with the existing card markup plus a status tag. Keep the section collapsed/secondary so it does not compete with the open queue.
- **Patterns to follow:** `web_index` context assembly; the existing decided-list card markup in `index.html`.
- **Test scenarios:** with one request per state, the index open section lists only the open request; the closed and superseded requests appear in the new section; `db.open_count()` counts only the open request (regression assert).
- **Verification:** Index test passes; open-count unchanged for non-open states.

## Verification Contract

| Gate | Applies to | Done signal |
|---|---|---|
| Migration round-trip | U1 | Legacy v3 db upgrades to `user_version == 4` with all prior rows preserved and new columns null. |
| db lifecycle unit tests | U2 | close/supersede/count_verdicts behave and reject invalid transitions. |
| API tests | U3, U4 | close/supersede routes return correct statuses; decide returns 409 for closed/superseded (with successor/reason) and for verdict lock (with `verdict_count`); `redecide: true` succeeds. |
| CLI tests | U5 | `portal close` / `portal supersede` print result JSON and exit 0; errors exit non-zero. |
| Rendered-page tests | U6, U7 | Superseded/closed banners and successor link render; index open list is pure and closed/superseded are surfaced. |
| Home-pill regression | R10 | `tests/test_view_requests.py` / media home-pill assertions still pass unchanged. |
| Full suite | all | `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q` is fully green. |
| Diff boundary | all | `git status --porcelain` touches only `gallery/db.py`, `gallery/server.py`, `gallery/cli.py`, `gallery/client.py`, `gallery/templates/**`, `gallery/static/style.css` (only if needed), and `tests/**`. |

## Definition of Done

- Migration v4 is additive, mirrors the v3 pattern, and `test_db_migrations.py` proves the legacy round-trip and the new `user_version == 4`.
- `close_request`, `supersede_request`, and `count_verdicts` exist in `db.py` with guards against missing ids, missing successors, self-supersede, and re-terminating a terminal request.
- `POST /api/requests/{id}/close` and `.../supersede` exist, are bearer-authed, and map errors to 404/400/409.
- The two decide endpoints return 409 for closed/superseded requests (with successor id / reason in the payload) and 409 with `verdict_count` on an unflagged re-decide; `redecide: true` restores latest-wins.
- `gallery/client.py` and `gallery/cli.py` expose `close` and `supersede` following the existing thin-wrapper and subcommand patterns.
- The request page renders the superseded (with successor link) and closed (with reason) banners and offers no decide controls for those states.
- The index open list contains only `open` requests; closed/superseded requests are surfaced in a separate section.
- Existing re-decide tests are updated to pass `redecide: true` (intended behavior change), and the media home-pill tests are untouched and green.
- The full pytest command passes with the `UV_CACHE_DIR` override, and the diff stays within the allowed files.
