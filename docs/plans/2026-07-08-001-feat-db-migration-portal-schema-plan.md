---
title: "feat: Add DB migration runner and Portal schema v1"
type: feat
status: active
date: 2026-07-08
origin: "trello-card:4t1RKydd"
trello: "https://trello.com/c/4t1RKydd"
spec: docs/portal-spec.md
---

# feat: Add DB migration runner and Portal schema v1

## Summary

Add a minimal SQLite migration runner inside `gallery/db.py`, use it to land Portal schema v1, and add the stream/post helpers that make the new schema usable. The plan keeps the implementation inside the DB layer plus focused tests, while preserving the current single connection and lock model.

---

## Problem Frame

`gallery/db.py` currently applies schema with `CREATE TABLE IF NOT EXISTS` on each connection. That can create missing tables, but it cannot add columns to an existing `requests` table, so existing installations cannot receive the Portal request columns without an explicit migration step.

Portal spec v1 also needs durable stream/post storage and a DB-layer bridge from legacy requests to decision posts, without introducing a full migration framework or renaming gallery surfaces on this card.

---

## Assumptions

*This plan was authored in pipeline mode without synchronous user confirmation. The items below are agent inferences that fill gaps in the input and should be reviewed before implementation proceeds.*

- The Trello shortlink for frontmatter is `https://trello.com/c/4t1RKydd`; this twf build exposed the short id but not a richer card URL.
- Spec section 4's DB-layer legacy compatibility belongs in this card because it can be implemented within `gallery/db.py` without changing `server.py`, `cli.py`, or `client.py`.
- Historical legacy request rows should be preserved but not backfilled into `streams`/`posts`; the dual-write applies to requests created after v1 lands.
- `project` stream slugs should use a deterministic, conservative normalization such as `proj-` plus lowercase hyphen-normalized project text, while `project is None` maps to `inbox`.
- `ensure_stream(slug)` may use the slug as the default title when lazily creating a `kind='session'` stream, because the card does not name a separate title source.
- `before-after` kind acceptance and before-media upload wiring are deferred to a later API/CLI/UI card; this card only creates the nullable storage columns.

---

## Requirements

- R1. Add a minimal `PRAGMA user_version`-gated migration runner in `gallery/db.py`, with numbered migration functions and no external framework.
- R2. Implement migration v1 to create `streams` and `posts`, add nullable `requests.stream_id`, `requests.before_media_path`, and `requests.before_media_type`, and set `user_version` to 1 on success.
- R3. Do not create a `messages` table in v1.
- R4. Preserve fresh DB behavior: first `connect()` creates all current Gallery tables plus Portal v1 schema and leaves `user_version == 1`.
- R5. Preserve upgrade behavior: a pre-Portal DB reopens through `connect()`, gains v1 schema, and keeps existing `requests`, `variants`, and `verdicts` rows intact.
- R6. Make reconnecting an already-migrated DB a no-op with no duplicate-column failures or row mutations.
- R7. Add stream helpers: `create_stream`, `get_stream`, `close_stream`, and `ensure_stream`.
- R8. Add post helpers: `create_post`, `list_posts`, and `get_post`, with JSON body round trips and post id generation following the existing `db.py` id convention.
- R9. Serialize first connection initialization and migration execution so concurrent first callers cannot race through `ALTER TABLE` before `_conn` is cached.
- R10. Keep stream foreign-key relationships enforced for new v1 rows, with `requests.stream_id` and `posts.stream_id` referencing `streams(id)` and no cascade-delete behavior.
- R11. Keep changes scoped to `gallery/db.py`, new `tests/test_db_migrations.py`, and `tests/conftest.py` only if fixture reuse proves insufficient.
- R12. Keep `server.py`, `cli.py`, and `client.py` unchanged.

---

## Scope Boundaries

- No Alembic or migration framework.
- No Gallery-to-Portal package, binary, route, or template rename.
- No `messages` table, ask/pull endpoints, or steering inbox behavior.
- No `server.py`, `cli.py`, or `client.py` edits.
- No before/after UI, media upload flag, or `before-after` kind routing.
- No public auth, stream token, Cloudflare, or Tailscale access changes.
- No broad schema refactor, ORM introduction, or unrelated cleanup.

### Deferred to Follow-Up Work

- API/CLI/UI Portal routes and stream pages: later Portal core cards.
- Before-media upload handling and toggle/side-by-side rendering: later before/after card.
- Message queue schema and helpers: phase 2 migration, per `docs/portal-spec.md`.
- Historical backfill of old requests into streams/posts, if desired: separate migration decision.

---

## Context & Research

### Relevant Code and Patterns

- `gallery/db.py` owns persistence with stdlib `sqlite3`, one module-level connection, `sqlite3.Row`, WAL mode, foreign keys enabled per connection, and `_lock` around writes.
- `connect()` currently opens the database, applies `SCHEMA` with `executescript`, commits, and caches `_conn`.
- Existing IDs use short prefixed opaque strings, for example `req_` plus random hex.
- Existing write helpers perform manual SQL and explicit commits under `_lock`.
- `tests/conftest.py` already isolates DB tests with `GALLERY_DATA_DIR`, `db.reset_connection()`, and tmp directories.
- `README.md` documents `uv` development commands and confirms tests do not touch `~/.gallery`.

### Institutional Learnings

- No `docs/solutions/` directory or prior solution notes were present in this worktree.
- `docs/portal-spec.md` is the primary project-local contract for this card.

### External References

- SQLite `PRAGMA user_version`: application-owned database header version state. https://www.sqlite.org/pragma.html
- SQLite `ALTER TABLE ADD COLUMN`: nullable unconstrained columns are valid, cheap schema edits; duplicate-column idempotence must be handled by the application. https://www.sqlite.org/lang_altertable.html
- SQLite transactions: explicit migration transactions should avoid accidental nested transaction assumptions. https://www.sqlite.org/lang_transaction.html
- Python `sqlite3`: `executescript()` commits pending transactions before running scripts, so migration batches should use explicit transaction control instead of relying on `executescript()` atomicity. https://docs.python.org/3/library/sqlite3.html

---

## Key Technical Decisions

- Keep migrations local to `gallery/db.py`: The card rejects a framework and the app is a single-user SQLite service.
- Run migrations from `connect()` before caching `_conn`: Every entry point already flows through `connect()`, so this upgrades both fresh and existing DBs without a separate command.
- Treat `SCHEMA` as bootstrap schema, then apply numbered migrations: This lets fresh DBs and legacy DBs follow the same v1 path and avoids duplicate-column issues from baking v1 columns into the bootstrap table definition.
- Make v1 migration idempotent by inspecting existing columns/tables as well as `user_version`: A partially-applied DB with `user_version == 0` should be repairable on the next connect.
- Keep request columns nullable and simple: SQLite `ALTER TABLE ADD COLUMN` has constraints around non-null, unique, and foreign-key defaults; nullable columns match the spec and the migration surface.
- Serialize connection initialization around open, bootstrap schema, migration execution, and `_conn` assignment: `CREATE TABLE IF NOT EXISTS` tolerated races better than `ALTER TABLE`; v1 migration should not run concurrently on two first-call connections.
- Keep stream slug as the human-facing stable identifier: `streams.id` can remain an opaque DB id, while `slug` is unique and immutable for `/s/<slug>` routing.
- Split transaction-local internals from public helpers: internal helpers that run inside `create_request` should accept the active connection and avoid taking `_lock` or committing; public helpers can wrap those internals with `_lock` plus commit/rollback.
- Enforce closed-stream read-only behavior at helper level where practical: Spec section 2 defines closed session streams as read-only archives.

---

## Open Questions

### Resolved During Planning

- Should `messages` ship in this migration? No. The spec and card both reserve it for phase 2.
- Should this use Alembic or a full migration framework? No. The card explicitly rejects that as overkill for this tool.
- Should existing rows be rewritten during upgrade? No for this plan. The acceptance criteria require preservation; no spec text requires backfilling old requests into streams/posts during v1 migration.

### Deferred to Implementation

- Exact helper return shapes: Match the existing `db.py` style and keep tests behavior-focused rather than over-specifying incidental dict contents.
- Exact exception type/message for writes to closed streams or duplicate stream slugs: Keep it simple and test observable behavior without coupling tests to prose.
- Exact project slug normalization helper name: Implement locally in `gallery/db.py` only if the legacy compatibility unit needs it.

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```text
connect()
  if cached connection exists, return it
  take the initialization lock
    check cached connection again
    open sqlite connection
    configure row_factory, WAL, and foreign_keys
    apply bootstrap Gallery tables
    run pending migrations:
      read PRAGMA user_version
      for each migration version above current:
        start one explicit transaction
        run idempotent migration function
        set PRAGMA user_version to that version
        commit
    cache and return module-level connection
```

For v1, the migration function creates missing Portal tables and adds only missing nullable `requests` columns. Stream/post helpers then operate on the v1 schema. Shared internals should separate transaction-local inserts from public lock/commit wrappers so `create_request` can produce one stream-linked decision post inside its existing write transaction without deadlocking or committing early.

---

## Implementation Units

- U1. **Add the migration runner and v1 schema migration**

**Goal:** Make `connect()` upgrade both fresh and existing databases to schema version 1.

**Requirements:** R1, R2, R3, R4, R5, R6, R9, R10, R11, R12

**Dependencies:** None

**Files:**
- Modify: `gallery/db.py`
- Test: `tests/test_db_migrations.py`

**Approach:**
- Add a `MIGRATIONS` list of versioned functions in `gallery/db.py`.
- Guard first connection initialization with a dedicated init lock or an equivalent double-checked locking pattern so only one thread can open, bootstrap, migrate, and assign `_conn` at a time.
- Call the migration runner from `connect()` after opening/configuring the connection and before assigning `_conn`.
- Keep the existing Gallery base tables available before migration v1 runs.
- In v1, create `streams` and `posts` if missing, add the three nullable request columns if missing, and set `PRAGMA user_version` to 1 only after the migration succeeds.
- Define new stream relationships with normal SQLite foreign keys and no cascade-delete behavior; `requests.stream_id` and `posts.stream_id` should point at `streams(id)`.
- Use explicit transaction control for each migration function and avoid relying on `executescript()` as the migration transaction boundary.
- Ensure `PRAGMA foreign_keys=ON` is set before migration transactions begin.

**Execution note:** Start with migration tests for fresh, legacy, rerun, and partial-v1 databases before changing `connect()`.

**Patterns to follow:**
- `gallery/db.py` connection setup and `_lock` usage.
- `tests/conftest.py` `GALLERY_DATA_DIR` and `db.reset_connection()` isolation pattern.

**Test scenarios:**
- Happy path: fresh tmp DB connects and has `requests`, `variants`, `verdicts`, `streams`, and `posts`; `messages` is absent; `PRAGMA user_version` is 1.
- Happy path: hand-built pre-Portal DB with old `requests`, `variants`, and `verdicts` opens through `db.connect()` and gains all v1 tables/columns.
- Edge case: an already-migrated DB reconnects after `db.reset_connection()` with unchanged row counts and no duplicate-column error.
- Edge case: a partially-applied v1 DB with one new column or table already present and `user_version == 0` completes migration cleanly.
- Edge case: a forced migration exception rolls back the active migration, does not bump `user_version`, does not cache `_conn`, and allows a later `connect()` retry.
- Edge case: concurrent first `connect()` calls do not race into duplicate `ALTER TABLE` or leave multiple cached connections.
- Integration: existing request detail and latest-verdict reads still work after legacy upgrade.
- Integration: `PRAGMA foreign_key_check` reports no violations after fresh creation and legacy upgrade.

**Verification:**
- Schema inspection shows version 1, expected v1 columns/tables, and no `messages` table.
- Existing request, variant, and verdict rows are preserved byte-for-byte where practical and behaviorally through existing getters.

---

- U2. **Add stream and post DB helpers**

**Goal:** Provide the DB-layer operations Portal code will need for streams and posts.

**Requirements:** R7, R8, R10, R11, R12

**Dependencies:** U1

**Files:**
- Modify: `gallery/db.py`
- Test: `tests/test_db_migrations.py`

**Approach:**
- Add stream helpers for create, lookup by slug, close, and lazy ensure.
- Keep `slug` unique and immutable; do not rewrite existing stream title/kind from `ensure_stream`.
- Add post helpers for create, list by stream id, and get by post id.
- Use transaction-local internal helpers for shared stream/post insert behavior; public helper functions should own locking and committing only when they are top-level writes.
- Generate post ids in the same local style as `new_request_id`, using the `p_` prefix shown by the Portal envelope.
- Store post body through `body_json` and return parsed body data from helper reads.
- Order post lists by creation order with a deterministic tie-breaker if needed.
- If a stream has `closed_at`, make write helpers fail visibly rather than silently adding posts to a closed archive.

**Execution note:** Implement new helper behavior test-first because no callers exist yet to exercise it indirectly.

**Patterns to follow:**
- Existing `create_request`, `get_request`, and `get_latest_verdict` JSON serialization/deserialization style.
- Existing module-level `_lock` for write helpers.

**Test scenarios:**
- Happy path: `create_stream` followed by `get_stream` returns slug, kind, title, created timestamp, and null `closed_at`.
- Happy path: `ensure_stream` returns an existing stream without mutating its title/kind.
- Happy path: `ensure_stream` creates a missing stream with `kind='session'`.
- Happy path: `close_stream` sets `closed_at` and the closed stream remains readable.
- Happy path: `create_post`, `list_posts`, and `get_post` round-trip type, title, author, parsed body, and created timestamp.
- Edge case: repeated stream creation for the same slug fails or returns a visible uniqueness error; tests should assert the chosen behavior.
- Edge case: creating a post for a closed or missing stream fails visibly.

**Verification:**
- Helper tests pass without needing server, CLI, or client changes.
- Returned helper data is suitable for later route code without requiring callers to parse raw JSON.

---

- U3. **Bridge new legacy requests into Portal stream/posts**

**Goal:** Keep existing request creation compatible with Portal streams by writing stream linkage and a decision post in the same DB transaction.

**Requirements:** R2, R5, R6, R8, R10, R11, R12

**Dependencies:** U1, U2

**Files:**
- Modify: `gallery/db.py`
- Test: `tests/test_db_migrations.py`

**Approach:**
- Update `create_request` internally, without changing server/CLI/client call sites, so new requests are assigned a stream id.
- For requests with `project`, derive the stream slug as `proj-<project-slug>`; for requests without `project`, use `inbox`.
- Lazily create the target stream as `kind='session'` if missing.
- Use transaction-local internals for stream creation and post insertion while already inside `create_request`'s write transaction; do not call public helpers that would take `_lock` again or commit independently.
- Insert the request row, variants, request-stream linkage, and one `posts.type='decision'` row in one write transaction.
- Keep existing request ids, variant indices, verdict behavior, and request API-facing data intact.
- Do not synthesize posts for historical rows during migration v1.

**Execution note:** Add an atomicity test before changing `create_request`; the failure path is the main behavioral risk.

**Patterns to follow:**
- Existing `create_request` transaction shape and 1-based variant insertion.
- Portal spec section 4 legacy compatibility rules.

**Test scenarios:**
- Happy path: creating a request with `project='fabrika/find_the_dog'` creates or reuses the expected project stream, stores `requests.stream_id`, and writes one decision post pointing at the request.
- Happy path: creating a request with `project is None` uses the `inbox` stream.
- Happy path: existing API expectations still hold at DB level: request id format, variant count, variant indices, open status, and latest verdict behavior.
- Edge case: a simulated failure during variant or post insertion rolls back request, variant, stream-link, and post writes for that request, while preserving any pre-existing stream row as intentionally outside or inside the transaction according to the implementation's documented choice.
- Edge case: `create_request` does not deadlock when it needs to lazily create a stream and post while holding the module write lock.
- Edge case: before-media columns remain nullable and are not represented as variant index 0.

**Verification:**
- New request rows are visible through old request helpers and through new stream/post helpers.
- Existing tests remain green without edits to `server.py`, `cli.py`, or `client.py`.

---

- U4. **Add focused migration and helper test coverage**

**Goal:** Prove the acceptance criteria and protect the migration edge cases that `CREATE TABLE IF NOT EXISTS` cannot cover.

**Requirements:** R3, R4, R5, R6, R7, R8, R9, R10, R11

**Dependencies:** U1, U2, U3

**Files:**
- Create: `tests/test_db_migrations.py`
- Modify: `tests/conftest.py` only if strictly needed

**Approach:**
- Keep all new DB migration/helper coverage in `tests/test_db_migrations.py`.
- Reuse `GALLERY_DATA_DIR`, `config.init_config(force=True)`, and `db.reset_connection()` rather than adding global fixture behavior.
- For legacy upgrade tests, create an old `gallery.db` under the tmp data directory before calling `db.connect()`.
- Use direct sqlite inspection for schema/version assertions and public `db.py` helpers for behavior assertions.
- Keep existing tests untouched unless implementation reveals a real shared fixture issue.

**Patterns to follow:**
- `tests/conftest.py` data-dir fixture.
- Existing pytest style in `tests/test_api.py` and `tests/test_cli.py`.

**Test scenarios:**
- Fresh DB schema and `user_version == 1`.
- Legacy DB upgrade preserves open and decided request data, variants, and latest verdict revision.
- Already-migrated DB reconnect is a no-op.
- Partial-v1 DB completes missing pieces idempotently.
- Failed migration does not cache `_conn`, does not advance `user_version`, and can be retried successfully.
- Concurrent first-connect initialization is serialized.
- Foreign-key enforcement remains on and `PRAGMA foreign_key_check` is clean.
- Stream helper create/get/ensure/close behavior.
- Post helper JSON round-trip and list ordering.
- Legacy `create_request` dual-write to stream and decision post.
- Existing full test suite remains green.

**Verification:**
- `uv run pytest tests/test_db_migrations.py -q` passes.
- `uv run pytest -q` passes with only known pre-existing warnings.

---

## System-Wide Impact

- **Interaction graph:** `connect()` is the only schema entry point; every DB helper depends on its migration having completed. `create_request` becomes the only legacy path that writes both request and post rows.
- **Error propagation:** Migration failures should abort connection initialization and avoid caching `_conn`. Write-helper failures should rollback their transaction and surface an exception to the caller.
- **State lifecycle risks:** Partial migration, duplicate column attempts, and request/post dual-write partial commits are the main risks. The plan mitigates them with per-object idempotence checks and transaction tests.
- **Concurrency risks:** First connection initialization becomes higher risk once `ALTER TABLE` enters the flow; serialize initialization so concurrent first callers cannot run migrations twice.
- **API surface parity:** No HTTP, CLI, or client interfaces change on this card. Existing API routes should keep working because `create_request` call shape remains stable.
- **Integration coverage:** Legacy upgrade and `create_request` dual-write tests cover the cross-table state that unit-only helper tests would miss.
- **Unchanged invariants:** Variant indices remain 1-based; latest verdict wins; module-level connection and `_lock` model remain in place; `messages` remains absent.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Duplicate-column failures on rerun or partial migration | Check existing request columns before each `ALTER TABLE ADD COLUMN`, and test already-migrated plus partial-v1 DBs. |
| Migration commits only part of v1 | Run each migration in one explicit transaction and set `user_version` only after successful DDL. |
| Concurrent first callers race through migration | Guard connection initialization and migration with a dedicated init lock or equivalent double-checked locking before `_conn` assignment. |
| `executescript()` transaction behavior undermines atomic migration assumptions | Keep bootstrap schema and migration transaction boundaries separate; do not rely on `executescript()` as the migration batch transaction. |
| Existing request data is changed during upgrade | Upgrade tests insert old rows first and assert requests, variants, and verdicts remain readable after connect. |
| Legacy request dual-write creates partial rows or deadlocks | Use transaction-local internals inside `create_request`; keep request, variant, stream link, and decision post writes in one transaction with rollback and no-deadlock tests. |
| Project slug normalization surprises future URLs | Keep the algorithm simple, deterministic, and covered by tests; revisit before public URL sharing if product needs prettier slugs. |
| This plan overreaches beyond the stage | The current twf stage is planning-only; implementation belongs to the next worker/stage. |

---

## Alternative Approaches Considered

- Alembic or another migration framework: rejected by the card as overkill for a single-user SQLite tool.
- Keeping schema-only `CREATE TABLE IF NOT EXISTS`: rejected because it cannot add columns to existing `requests` tables.
- Backfilling all historical requests into streams/posts during v1: deferred because the spec only requires dual-write for requests created through existing paths, and acceptance criteria emphasize preserving existing rows.

---

## Documentation / Operational Notes

- No user-facing docs update is required for this DB-layer card.
- Existing installations should upgrade automatically on the next process connection to `gallery.db`.
- The implementation handoff should call out any migration test that was skipped or any fixture change needed beyond `tests/test_db_migrations.py`.

---

## Sources & References

- Origin card: `trello-card:4t1RKydd`
- Trello shortlink: https://trello.com/c/4t1RKydd
- Portal contract: `docs/portal-spec.md`
- DB implementation: `gallery/db.py`
- Test fixtures: `tests/conftest.py`
- Existing API tests: `tests/test_api.py`
- Existing CLI tests: `tests/test_cli.py`
- SQLite PRAGMA docs: https://www.sqlite.org/pragma.html
- SQLite ALTER TABLE docs: https://www.sqlite.org/lang_altertable.html
- SQLite transaction docs: https://www.sqlite.org/lang_transaction.html
- Python sqlite3 docs: https://docs.python.org/3/library/sqlite3.html
