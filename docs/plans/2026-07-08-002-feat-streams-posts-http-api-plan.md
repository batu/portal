---
title: "feat: Add streams/posts HTTP API and before upload storage"
type: feat
status: active
date: 2026-07-08
origin: "trello-card:8OEiwp9u"
trello: "https://trello.com/c/8OEiwp9u"
spec: docs/portal-spec.md
---

# feat: Add streams/posts HTTP API and before upload storage

## Summary

Add the Portal HTTP surface on top of the landed stream/post DB helpers: bearer-token stream create/read/close endpoints, multipart post creation with report media storage and soft size warnings, legacy request visibility through streams, optional before-image storage on requests, and thin stdlib client helpers. The implementation stays inside the server/client/DB/test scope fence and preserves existing request endpoints while making the new stream view testable through API responses.

---

## Problem Frame

The DB migration and schema work now exists, but agents still cannot publish or read streams/posts over HTTP. Legacy `/api/requests` creates decision requests, yet the Portal stream APIs are absent, report uploads have no endpoint, and optional before images have no upload path even though their storage columns exist.

---

## Assumptions

*This plan was authored in pipeline mode without synchronous user confirmation. The items below are agent inferences that fill gaps in the input and should be reviewed before implementation proceeds.*

- The Trello shortlink for frontmatter is `https://trello.com/c/8OEiwp9u`; this twf context exposed the short id but not a richer card URL.
- The prior DB migration/helper card has landed before this implementation starts. In this worktree, `gallery/db.py` already contains stream/post tables, stream/post helpers, request `stream_id`, before-media columns, and a legacy request dual-write.
- The card's API acceptance should govern the project-to-stream slug visible over HTTP. The current helper in this branch appends a hash suffix for collision resistance, while the card expects `project='fabrika/x'` to appear at `GET /api/streams/proj-fabrika-x`; implementation should make the stored stream slug exactly `proj-fabrika-x` and update the prior hash-suffix test accordingly.
- For `POST /api/streams/{slug}/posts`, the minimal body contract can be a JSON form field plus file metadata added by the server. The spec says "body fields" but does not define a richer report schema for this server-only card.
- Uploaded report assets should remain flat under `media/<post_id>/` because the existing `/media/{id}/{filename}` route only serves one filename path segment.
- Client helper tests can live in `tests/test_streams_api.py` by monkeypatching the low-level request helper; there is no existing dedicated `tests/test_client.py`, and the card's scope fence names `tests/test_api.py` and `tests/test_streams_api.py`.

---

## Requirements

- R1. Add bearer-token JSON endpoints for creating, closing, and reading streams: `POST /api/streams`, `POST /api/streams/{slug}/close`, and `GET /api/streams/{slug}`.
- R2. Add bearer-token post endpoints: `POST /api/streams/{slug}/posts` for multipart `report` posts and request-backed `decision` posts, plus `GET /api/streams/{slug}/posts/{id}` for stream-scoped post lookup.
- R3. Auto-create a missing stream as `kind='session'` when posting to `/api/streams/{slug}/posts`, rather than returning an unknown-stream error.
- R4. Store uploaded post files under `media/<post_id>/` and keep them servable through the existing `/media/{id}/{filename}` handler.
- R5. Enforce the 200 MB per-post soft cap as an acceptance warning only: total uploaded bytes over the cap still succeed and include a warning field in the response.
- R6. Keep legacy `/api/requests` behavior intact while ensuring created requests are visible through their mapped stream in the same transaction as the request/variants rows.
- R7. Map legacy requests with `project='fabrika/x'` to the HTTP-visible stream slug `proj-fabrika-x`, and requests without a project to `inbox`.
- R8. Accept an optional `before` upload on `POST /api/requests`, store it under the request media directory as `__before.<ext>`, and persist `before_media_path` and `before_media_type` on the request row.
- R9. Never store the before image as a variant row; variants remain 1-based and verdict validation remains based only on candidate variants.
- R10. Accept `kind='before-after'` for request creation as a pick-one-compatible decision kind, because `docs/portal-spec.md` section 6 names it as accepted.
- R11. Add thin helpers in `gallery/client.py` for each new streams/posts API endpoint, preserving the existing stdlib-only `urllib` style.
- R12. Keep `messages`, ask/pull, stream note boxes, browser twin routes, Portal CLI commands, and stream web pages out of this card.
- R13. Verify the full suite with `uv run pytest -q`, with focused tests for every card acceptance criterion.
- R14. Harden media serving before relying on `/media/{id}/{filename}` for post and before media: validate path segments, confine resolved paths under the intended media directory, and add active-content headers/policy.
- R15. Validate permanent stream/post inputs: URL-safe stream slugs, non-empty bounded title/author fields, bounded body JSON, and safe upload filenames.
- R16. Write multipart uploads incrementally while counting bytes for the soft cap, so warning-only size semantics do not require loading large uploads wholly into memory.

---

## Card Acceptance Criteria Trace

| Card acceptance criterion | Requirements | Units | Test scenario anchor |
|---|---|---|---|
| Stream create/close/get round-trip; posting to unknown slug auto-creates `kind=session` | R1, R3 | U2 | U2 stream round-trip and unknown-slug post tests |
| Report post with files lands in `media/<post_id>/` and is served by `/media` | R2, R4, R14, R15, R16 | U1, U2 | U2 report upload, media serving, path confinement, and active-content header tests |
| Legacy request with `project='fabrika/x'` is visible in `proj-fabrika-x`; no project is visible in `inbox` | R6, R7 | U1, U2 | U1 exact stored slug test and U2 legacy stream visibility tests |
| Request with before upload persists before fields, serves file, keeps variants 1-based, and preserves verdict flow | R8, R9, R10 | U1, U3 | U3 before upload, media serving, variant index, and verdict tests |
| Post upload over 200 MB is accepted with a warning | R5, R16 | U2 | U2 monkeypatched soft-cap warning test |
| Client helpers exist for the new endpoints | R11 | U4 | U4 monkeypatched client helper tests |

---

## Scope Boundaries

- No `messages` table or message HTTP endpoints.
- No server-side long-polling, sleeping route handlers, or code that holds the module-level DB lock while waiting for human/agent input.
- No stream web UI, `/s/<slug>` template, note box, answer box, or cookie-authenticated browser twin route.
- No `portal` binary, CLI command expansion, launchd/deploy change, or README rewrite.
- No evidence-folder crawling or automatic import of files not explicitly uploaded.
- No public auth, per-stream token, Cloudflare/Tailscale access, or multi-user identity work.
- No broad media serving refactor beyond what is necessary for flat `media/<post_id>/<filename>` report assets.
- No hard rejection solely because a post exceeds the 200 MB soft cap; the explicit card requirement is warning-only acceptance. Underlying filesystem failures can still surface as storage errors.
- No historical backfill of pre-Portal request rows into streams/posts.

### Deferred to Follow-Up Work

- Stream browser pages and cookie-authenticated page actions: later Portal core/UI card.
- `portal stream`, `portal report`, and `portal post --before` CLI commands: later CLI card.
- Phase-2 `messages`, ask/pull, and Telegram-on-question behavior: later inbox card per `docs/portal-spec.md`.
- Public share/auth hardening and per-stream tokens: phase 3 or later.

---

## Context & Research

### Relevant Code and Patterns

- `gallery/server.py` owns FastAPI routes, bearer auth through `require_api_token`, cookie/query-token web auth through `web_token_ok`, upload storage under `config.media_dir()`, and `HTTPException` translation.
- `gallery/db.py` owns persistence with a module-level SQLite connection, `_lock` around reads/writes, JSON-in-text columns, `create_stream`, `get_stream`, `ensure_stream`, `close_stream`, `create_post`, `list_posts`, `get_post`, and existing legacy request dual-write.
- `gallery/client.py` is stdlib-only and exposes `get_json`, `post_json`, and `post_multipart` as thin wrappers around a private `_request`.
- `tests/conftest.py` isolates state with `GALLERY_DATA_DIR`, `config.init_config(force=True)`, and `db.reset_connection()`.
- `tests/test_api.py` shows the existing FastAPI `TestClient` style for auth, multipart uploads, media serving, verdicts, and unchanged legacy request behavior.
- `tests/test_db_migrations.py` already covers stream/post DB helpers and legacy dual-write atomicity, but currently encodes a hash-suffixed project-stream slug behavior that conflicts with this card's HTTP acceptance.

### Institutional Learnings

- No `docs/solutions/` directory or critical-patterns file exists in this worktree.
- `docs/portal-spec.md` is the primary local contract. It emphasizes push-only producers, plain HTTP + thin client shims, bearer-auth API routes, no server-side long-polling, and before images stored outside variants.
- The prior plan `docs/plans/2026-07-08-001-feat-db-migration-portal-schema-plan.md` confirms that DB migration/schema work intentionally left HTTP routes, before upload wiring, and client helpers for a later card.

### External References

- External research is not needed for this plan. The feature follows existing FastAPI multipart, sqlite, and stdlib client patterns already present in the repo.

---

## Key Technical Decisions

- Reuse DB helpers instead of rebuilding persistence in `server.py`: the dependency card created the stream/post schema and helper layer specifically for this HTTP card.
- Add narrow DB read/write extensions only where HTTP behavior needs them: stream-scoped post lookup, stream-with-post-index retrieval, caller-reserved post ids for `media/<post_id>/` storage, before-media persistence on request creation, and project-stream slug reconciliation.
- Treat the card's stream slug acceptance as authoritative: the actual stored stream slug for `project='fabrika/x'` should be `proj-fabrika-x`, not a hidden hash-suffixed slug with an HTTP alias.
- Keep new `/api/*` routes bearer-token protected through `require_api_token`, matching current `/api/requests` behavior.
- Keep post upload handling flat and explicit: save files under `media/<post_id>/` with safe basenames, then store relative filenames/media types in the post body returned by the API.
- Make the 200 MB cap a server constant that tests can monkeypatch, compute the warning from bytes actually read during upload handling, and write upload data in chunks so the warning-only rule does not force large in-memory buffers.
- Treat direct `decision` posts as request-backed index posts: require body JSON to reference an existing request id, reject missing/unknown request ids, and keep creation of answerable decisions on `/api/requests`.
- Harden the generic media route before expanding its use: reject traversal-ish path segments after URL decoding, resolve the target path, require it to stay under `config.media_dir() / media_id`, and set `X-Content-Type-Options: nosniff`.
- Use a conservative active-content policy on `/media`: serve image/video allowlisted types inline; serve HTML/SVG/unknown uploads as attachments or otherwise non-executable. Inline/sandboxed report rendering belongs to a later stream web UI card.
- Keep before upload out of the variant loop: write the before file separately, then pass before path/type to the DB request writer.
- Extend client multipart support only as far as needed for named file fields and streams/posts helpers; do not add a `requests` dependency.
- Keep API response shapes stable enough for client helpers and tests, but avoid introducing unused typed author, tags, stream-token, or message payload concepts.

---

## Open Questions

### Resolved During Planning

- Should this card implement message/ask/pull endpoints? No. The spec and card both defer messages to phase 2.
- Should this card add Portal CLI commands? No. The card's scope fence names `gallery/client.py` helpers, not `gallery/cli.py`.
- Should reports be rejected when they exceed 200 MB? No. The card explicitly says warn and accept.
- Should the before image be a selectable variant? No. The spec and card explicitly reject that because variants are 1-based.
- Should the implementation change the existing media handler to serve nested report asset paths? Not for this card. Flat report uploads satisfy the acceptance criteria and match the current route shape.
- Should direct `decision` posts create new request/variant rows? No for this server-side card. The request-centric decision flow stays on `/api/requests`; direct decision posts through `/api/streams/{slug}/posts` must reference an existing request id.

### Deferred to Implementation

- Exact stream/post response envelope shape: follow existing dict-return style and keep tests focused on the contract fields the client and acceptance criteria need.
- Exact HTTP status mapping for duplicate stream creation and closed-stream writes: choose clear 4xx responses and cover them with focused tests.
- Exact handling of duplicate uploaded filenames in one post: choose deterministic safe names similar to request variant uploads.
- Exact update strategy for existing `tests/test_db_migrations.py` slug assertions when `db._stream_slug_for_project` changes to satisfy this card.

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```mermaid
flowchart TB
    Agent[Agent/client] --> API[Bearer /api routes]
    API --> Server[gallery/server.py]
    Server --> DB[gallery/db.py helpers]
    Server --> Media[media/<request_or_post_id>/ files]
    DB --> Streams[streams rows]
    DB --> Posts[posts rows]
    DB --> Requests[requests/variants/verdicts rows]
    Media --> Handler[existing /media/{id}/{filename}]
```

The stream endpoints should be thin: authenticate, validate request data, call DB helpers, translate DB errors to HTTP errors, and return serializable dicts. Multipart post creation should reserve a post id before file placement, stream uploads into `media/<post_id>/` while tracking total bytes for the soft cap, insert the post body with the final file metadata, and return the created post plus any warning. Legacy request creation should keep its existing response shape while adding optional before-file storage and preserving stream dual-write.

---

## Implementation Units

- U1. **Reconcile DB helpers for HTTP stream contracts**

**Goal:** Add the DB-layer behavior the new routes need without expanding beyond stream/post reads, before-media persistence, and the legacy slug contract.

**Requirements:** R2, R6, R7, R8, R9, R10, R15

**Dependencies:** Prior DB migration/helper card merged

**Files:**
- Modify: `gallery/db.py`
- Test: `tests/test_streams_api.py`
- Test: `tests/test_api.py`
- Modify if slug-helper assertions change: `tests/test_db_migrations.py`

**Approach:**
- Add or adjust DB helpers for reading a stream plus its ordered post index and for fetching a post only when it belongs to a given stream slug.
- Add a narrow way for the server to reserve or provide the post id used by a post insert, so report files can land under `media/<post_id>/` and the inserted body can include final file metadata.
- Extend request creation storage to accept optional before-media path/type and persist those fields on `requests`.
- Accept `before-after` as a valid request kind while keeping selection validation based on existing variant indices.
- Reconcile `_stream_slug_for_project` with the card's expected stored slug `proj-fabrika-x` for `project='fabrika/x'`.
- Keep all new helpers using the existing module-level connection and `_lock`; avoid new SQLite connections or migration changes.

**Execution note:** Start with tests that expose the slug divergence and before-media persistence before editing `db.py`.

**Patterns to follow:**
- `gallery/db.py` `get_request`, `list_posts`, and `create_request` JSON/dict style.
- `tests/test_db_migrations.py` helper-level tests for dual-write and request stream linkage.

**Test scenarios:**
- Happy path: a project request for `project='fabrika/x'` is associated with a stream readable as `proj-fabrika-x`.
- Happy path: a projectless request is associated with the `inbox` stream.
- Happy path: post creation can use a reserved/caller-provided post id so the returned post id matches the media directory.
- Happy path: `get_request` returns `before_media_path` and `before_media_type` when request creation receives before metadata.
- Happy path: `kind='before-after'` creates a request and verdict selection `[1]` is accepted when one candidate variant exists.
- Edge case: before metadata does not create a variant row, and `variant_indices(req_id)` remains `{1, ..., n}` with no `0`.
- Edge case: stream-scoped post lookup does not return a post from a different stream.
- Edge case: a simulated request dual-write failure rolls back request/variant/post rows and does not leave a new project stream behind unless the existing transaction behavior intentionally documents otherwise.
- Integration: existing request creation, list, get, and verdict behavior remains unchanged except for additive fields already present on request rows.

**Verification:**
- DB helper behavior supports the route tests without route-level code reaching into raw SQL.
- Existing DB migration/helper tests either remain green or are intentionally updated only where the card's slug contract supersedes the prior hash-suffix assertion.

---

- U2. **Add bearer-auth stream and post HTTP endpoints**

**Goal:** Expose the Portal stream/post API over FastAPI using existing auth and DB patterns.

**Requirements:** R1, R2, R3, R4, R5, R6, R7, R12, R13, R14, R15, R16

**Dependencies:** U1

**Files:**
- Modify: `gallery/server.py`
- Create: `tests/test_streams_api.py`

**Approach:**
- Add `POST /api/streams` to create explicit streams from JSON `slug`, `kind`, and `title`; validate `kind`, require a URL-segment-safe lowercase slug, and require a non-empty bounded title.
- Add `POST /api/streams/{slug}/close` and keep closed streams readable but not writable through post creation.
- Add `GET /api/streams/{slug}` returning stream details plus an ordered post index.
- Add `POST /api/streams/{slug}/posts` as multipart, restricted to `type='report'` or `type='decision'`, with required bounded title/author and optional bounded JSON/body form fields.
- For `type='decision'`, require body JSON to reference an existing request id; reject missing or unknown request ids instead of creating an unanswerable decision.
- Auto-create a missing stream with `kind='session'` only on post creation, not on plain stream GET.
- Save uploaded post files under `media/<post_id>/` using flat safe filenames and include their relative filenames/media types in the post body returned by the API.
- Stream uploaded bytes to disk in chunks while counting them; if the total exceeds the soft cap constant, include a warning field and still return success.
- Add `GET /api/streams/{slug}/posts/{id}` and return 404 when either the stream or stream-scoped post is missing.
- Harden `GET /media/{id}/{filename}` as part of this unit: validate path segments, confine resolved paths under the target media directory, and set `nosniff`/attachment behavior for active or unknown content types.
- Translate DB `ValueError`/integrity failures into clear HTTP errors rather than leaking stack traces.

**Execution note:** Implement route behavior test-first because this unit defines the external API contract.

**Patterns to follow:**
- `gallery/server.py` existing `/api/requests` auth, upload, media, and `HTTPException` patterns.
- `tests/test_api.py` FastAPI `TestClient` style and `auth_headers` helper.

**Test scenarios:**
- Happy path: authenticated stream create, close, and get round-trip returns the expected stream fields and closed timestamp.
- Happy path: posting a report to an unknown slug auto-creates a `kind='session'` stream and returns the created post.
- Happy path: report post uploads land under `media/<post_id>/`, appear in the post body/index, and the existing `/media/<post_id>/<filename>?token=...` route serves the bytes.
- Happy path: request-backed `decision` post with an existing `request_id` is accepted, appears in the stream post index, and is returned by `GET /api/streams/{slug}/posts/{id}`.
- Happy path: `GET /api/streams/{slug}/posts/{id}` returns the post only under its owning stream.
- Happy path: legacy `/api/requests` with `project='fabrika/x'` is visible in `GET /api/streams/proj-fabrika-x` as a decision post referencing the request id.
- Happy path: legacy `/api/requests` without a project is visible in `GET /api/streams/inbox`.
- Edge case: all new `/api/streams*` routes reject missing/invalid bearer auth with 401.
- Edge case: `GET /api/streams/missing` returns 404 and does not auto-create.
- Edge case: posting to a closed stream returns a 4xx error and does not create a post or media files beyond any deliberately cleaned-up temporary writes.
- Edge case: monkeypatching the soft cap to a tiny value makes an oversized upload succeed with a warning field.
- Edge case: media traversal attempts using `..`, encoded separators, or path-like filenames return 404 or 400 and never serve files outside the target media directory.
- Edge case: uploaded HTML/SVG/unknown files are not served inline from `/media`; responses include `X-Content-Type-Options: nosniff` and attachment or equivalent non-executable handling.
- Error path: invalid post type, invalid body JSON, invalid slug/title/author/body sizes, missing decision `request_id`, unknown decision `request_id`, or duplicate stream creation returns a clear 4xx response.

**Verification:**
- `tests/test_streams_api.py` proves the stream/post API acceptance criteria.
- Existing request tests in `tests/test_api.py` continue to pass without changing expected legacy response shape.

---

- U3. **Add optional before upload to legacy request API**

**Goal:** Wire the existing request endpoint to store one before image outside variants.

**Requirements:** R8, R9, R10, R13

**Dependencies:** U1

**Files:**
- Modify: `gallery/server.py`
- Extend: `tests/test_api.py`

**Approach:**
- Add optional multipart field `before` to `POST /api/requests`.
- Store the before upload under the request media directory using `__before.<ext>` based on the original filename suffix, with a safe fallback extension if needed.
- Persist `before_media_path` and `before_media_type` via the DB request creation path.
- Keep candidate uploads in the existing `files` field and continue numbering only those files as variants.
- Accept `before-after` as a request kind in the same API path and keep verdict validation unchanged.
- Keep the existing response body for request creation additive-only; no new response field is required unless implementation chooses to expose before metadata there.

**Execution note:** Characterize existing `/api/requests` variant indexing in the new test before adding the before file path.

**Patterns to follow:**
- `gallery/server.py` current `create_request` upload loop and `_media_type_for`.
- Existing media-serving assertion in `tests/test_api.py`.

**Test scenarios:**
- Happy path: posting a request with a `before` file and two candidate files sets `before_media_path`, sets `before_media_type`, and returns two variants indexed `1` and `2`.
- Happy path: the before file is served through `/media/<req_id>/<before_media_path>?token=...`.
- Happy path: verdict submission with selected variant `[1]` still succeeds and ignores the before image.
- Happy path: `kind='before-after'` is accepted by `/api/requests`.
- Edge case: a request without `before` preserves current behavior and leaves before fields null.
- Edge case: a before upload with a path-like original filename is stored as the fixed `__before.<ext>` name, not an arbitrary client path.

**Verification:**
- Before upload acceptance is covered in `tests/test_api.py`.
- Variant indices remain 1-based and `db.variant_indices` never includes `0`.

---

- U4. **Add thin client helpers for stream/post endpoints**

**Goal:** Give agent code a small stdlib client surface for the new HTTP endpoints without adding CLI commands or dependencies.

**Requirements:** R11, R13

**Dependencies:** U2

**Files:**
- Modify: `gallery/client.py`
- Test: `tests/test_streams_api.py`

**Approach:**
- Add helpers for create stream, close stream, get stream, create stream post, and get stream post.
- Reuse `post_json`, `get_json`, and the existing `_request` error handling.
- Extend multipart helper support only if needed for named file fields or body JSON, while preserving the existing `post_multipart(..., files=[...])` call used by `gallery/cli.py`.
- Keep helper names and argument order close to existing `get_json`/`post_json`/`post_multipart` style.
- Do not edit `gallery/cli.py` on this card.

**Execution note:** Add lightweight helper tests by monkeypatching `gallery.client._request` so URL paths, methods, and auth behavior are covered without starting a real server.

**Patterns to follow:**
- `gallery/client.py` existing thin wrappers and `GalleryClientError`.
- `tests/test_cli.py` monkeypatch style for focused command/helper behavior.

**Test scenarios:**
- Happy path: create/close/get stream helpers call the expected HTTP methods and paths.
- Happy path: get stream post helper requests the stream-scoped post path.
- Happy path: create post helper sends multipart fields for type/title/author/body and uploads files under the expected field convention.
- Edge case: extending multipart support for named file fields does not break the existing `/api/requests` client call shape used by `gallery.cli`.

**Verification:**
- Client helper tests pass without network access.
- No CLI parser tests need to change.

---

- U5. **Run focused and full verification**

**Goal:** Confirm the implementation satisfies the card and does not regress the existing Gallery API.

**Requirements:** R13

**Dependencies:** U1, U2, U3, U4

**Files:**
- Test: `tests/test_streams_api.py`
- Test: `tests/test_api.py`
- Test if touched: `tests/test_db_migrations.py`

**Approach:**
- Run the new stream API tests first to isolate failures in the new contract.
- Run existing API tests to verify baseline request/verdict/media behavior.
- Run the full suite after the focused tests pass.
- Record any unavoidable divergence from the prior DB helper slug tests in the implementation handoff.

**Patterns to follow:**
- README development command uses `uv run pytest`.

**Test scenarios:**
- Integration: `uv run pytest tests/test_streams_api.py tests/test_api.py -q` passes.
- Integration: `uv run pytest -q` passes with only the known pre-existing warning if it still appears.

**Verification:**
- The final implementation handoff includes the exact commands run and whether warnings were pre-existing.

---

## System-Wide Impact

- **Interaction graph:** Agent/client calls hit bearer `/api` routes in `gallery/server.py`, route handlers call `gallery/db.py` helpers under the existing connection/lock model, and uploaded files are served by the existing media handler.
- **Error propagation:** DB duplicate/missing/closed-stream errors should become intentional 4xx API responses. Invalid multipart/JSON input should return 400-class errors. Uploads over the soft cap should not be errors.
- **State lifecycle risks:** Post creation spans DB rows and filesystem writes. The plan keeps writes local and tested, but implementers should avoid leaving rows that reference missing files; orphan-file cleanup on DB failure is acceptable if scoped to new writes.
- **Media security risks:** Expanding `/media` from request variants to request before images and report files increases exposure. Harden path confinement and active-content handling before treating the route as generic.
- **Concurrency risks:** No route should sleep or poll while holding the DB lock. New helpers should use the same short critical sections as existing DB helpers.
- **API surface parity:** Existing `/api/requests`, `/api/requests/{id}`, verdict routes, web decide route, and media route remain compatible. New stream endpoints are additive.
- **Integration coverage:** Tests must cover legacy request creation becoming visible through streams, because DB-only tests do not prove the HTTP contract.
- **Unchanged invariants:** Variant indices remain 1-based; before images are not selectable; latest verdict wins; `messages` stays absent; `gallery/client.py` remains stdlib-only.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Current project-stream slug helper conflicts with card acceptance | Make slug reconciliation an early DB/API unit, add an explicit test for `GET /api/streams/proj-fabrika-x`, and update prior helper tests only if required. |
| New routes leak raw DB exceptions | Route handlers should translate expected `ValueError` and integrity errors into clear 4xx responses, with tests for duplicate/missing/closed cases. |
| Filesystem and DB writes can diverge during multipart post creation | Reserve post ids before file placement, keep file paths deterministic, and clean up new files on known DB failures if implementation structure makes that practical. |
| Soft cap accidentally becomes a hard reject or memory spike | Keep the cap as warning-only, stream writes in chunks, and prove warning-only behavior by monkeypatching a tiny cap in tests. |
| Generic media route becomes a path traversal or stored-XSS surface | Add path confinement checks, safe filename handling, `nosniff`, and attachment/non-inline handling for active or unknown file types. |
| Before upload shifts variant numbering | Write before outside the candidate upload loop and assert variants remain 1-based. |
| Client helper changes break existing CLI multipart uploads | Preserve the existing `post_multipart(base_url, token, path, fields, files)` behavior and test any compatibility-sensitive extension. |
| Scope expands into Portal UI/CLI/messages | Keep those items in Scope Boundaries and do not touch `gallery/cli.py` unless a test reveals a client compatibility issue. |

---

## Documentation / Operational Notes

- No README or deploy update is required for this server-side API/storage card.
- The implementation handoff should mention whether the project stream slug helper was changed from the hash-suffixed behavior introduced by the dependency branch.
- The implementation handoff should include `uv run pytest -q` output summary and any known warning status.

---

## Sources & References

- Origin card: `trello-card:8OEiwp9u`
- Trello shortlink: https://trello.com/c/8OEiwp9u
- Portal contract: `docs/portal-spec.md`
- Dependency plan: `docs/plans/2026-07-08-001-feat-db-migration-portal-schema-plan.md`
- Server implementation: `gallery/server.py`
- DB implementation: `gallery/db.py`
- Client implementation: `gallery/client.py`
- Existing API tests: `tests/test_api.py`
- DB migration/helper tests: `tests/test_db_migrations.py`
- Test fixtures: `tests/conftest.py`
