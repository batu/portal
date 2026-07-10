---
title: "P5d Journey: native /g/<slug> game-journey page from a producer-posted journey doc - Plan"
type: feat
date: 2026-07-10
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: trello-card:YGFaO9P6
execution: code
origin: "trello-card:YGFaO9P6"
trello: "https://trello.com/c/YGFaO9P6"
spec: docs/portal-spec.md
---

# P5d Journey: native /g/<slug> game-journey page from a producer-posted journey doc - Plan

## Goal Capsule

| Field | Value |
|---|---|
| Objective | Add a **native Portal primitive** for game journeys: a producer-posted `journey` doc (ordered steps: title, summary, references to already-uploaded media, optional linked request) stored **update-in-place** under one stable slug, rendered at **`/g/<slug>`** with full Portal chrome — a deliberate vertical story spine where each step shows its media (video embedded, not re-uploaded), a link to the step's request page, and the request's **live** status/verdict pulled live from the DB. |
| Authority | Trello card `YGFaO9P6` first (Batu's verbatim ask + ratified direction), then the existing Portal db/server/cli/client/template/test patterns (esp. the just-landed P5b lifecycle vocabulary and P5c context-header/status-chip work), then `docs/portal-spec.md`. |
| Execution profile | Additive SQLite migration (v6) for a slug-keyed `journeys` table with upsert (update-in-place) semantics; a validated JSON journey doc; `PUT/GET/list` JSON API under bearer auth; CLI/client `journey` verb; a new `/g/<slug>` cookie-authed web route + `journey.html` template + journey CSS; an index link section; a real-density wool-crush fixture + seeded demo; and a `scripts/verify-journey.sh` (serve + Playwright screenshot at 1440x900). |
| Stop conditions | Files limited to `gallery/db.py`, `gallery/server.py`, `gallery/cli.py`, `gallery/client.py`, `gallery/templates/**`, `gallery/static/**`, `tests/**`, plus the card-authorized `scripts/verify-journey.sh` and the seed demo. DB changes additive only. The step vocabulary is **producer data** — nothing wool-crush-specific in Portal code. Media is **referenced, never re-uploaded** (the 32MB proxy video is referenced by its existing post id). If the baseline suite is red before any edit, report it and stop. |
| Completion signal | `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q` fully green, including: journey post + update-in-place replaces content at the same `/g/<slug>` URL; `/g/<slug>` renders ordered steps with each linked request's **live** sibling status; unknown slug → 404; auth applies (unauthenticated → login redirect / 401); and the wool-crush real-density fixture renders end-to-end. The desktop visual check runs via `scripts/verify-journey.sh` (conductor runs it if this sandbox cannot launch a browser). |

## Product Contract

### Summary

Batu (2026-07-09, verbatim): *"can you design a front end for the portal that is focused on collecting the steps that we go through for a game? … I want to be able to watch the video, that is the first step right? see the input, then see the references that we selected, then the design, then the style sheet etc."* The ratified direction (a generated single-file view was **rejected** — it cannot embed the 32MB video without re-upload, cannot read sibling requests' live status, cannot update in place) is a **native Portal primitive**: (1) a new doc kind `journey` — JSON of ordered steps `{slug, title, steps: [{title, summary, media: [refs to existing posts/media], request_id?}]}` — that a producer posts and re-posts via cli/client/API, **update-in-place by design** (one stable URL per game; re-post replaces content); (2) a route `/g/<slug>` that renders the journey with full Portal chrome (auth, breadcrumbs), per step showing title, summary, embedded/linked media (the video step references the already-uploaded proxy post — **no duplicate upload**), a link to the step's request page, and the step's **live** status/verdict pulled from the DB (the P5b vocabulary incl. closed/superseded); (3) an index that links existing journeys; and (4) a **generic substrate** — the step vocabulary is producer data, nothing wool-crush-specific in Portal code.

### Problem Frame

The producer pipeline produces a sequence of artifacts for a game — a proxy video, a frame-picker request, a style report, an asset sheet, a token-promotion request — but Portal today surfaces them only as scattered independent requests/posts/streams with no ordered narrative and no single stable place to *watch the whole game come together in order*. A journey is inherently **ordered** and **mutable at a stable URL** (steps get added/re-ordered as the game progresses), which neither an append-only stream (immutable posts) nor a generated single-file HTML (frozen, can't embed the big video, can't read live status) can express. So the journey needs its own primitive: a slug-keyed doc that is replaced in place on re-post, and a chrome-wrapped page that resolves references live at render time.

### Requirements

- R1. A producer can post a `journey` doc via CLI → client → JSON API. The doc is `{title, steps: [...]}` addressed by a URL-safe `slug`; each step is `{title, summary?, media?: [ref...], request_id?}`; each media ref is `{owner_id, filename, caption?}` pointing at an **already-uploaded** post/request media file (`/media/<owner_id>/<filename>`). The slug is the stable address.
- R2. **Update-in-place:** re-posting the same slug **replaces** the stored doc (title + steps) atomically; the URL `/g/<slug>` is stable and always serves the latest content. There is exactly one row per slug.
- R3. Route **`/g/<slug>`** renders the journey with full Portal chrome: it extends `base.html` (topbar + `/static` assets), shows a breadcrumb (`Index / <journey title>`) consistent with `/r` and `/s`, and lays the steps out as a **deliberate vertical story spine** (numbered, connected), desktop-first — not a stacked-default list.
- R4. Per step the page renders: the step **title**, the step **summary** (producer free text), each **media** ref (video → embedded `<video controls>`; image → `<img>`; HTML/other → a labeled link that opens the existing Portal media URL, since HTML media is served sandboxed and is not embedded inline), and — when `request_id` is present — a link to `/r/<request_id>` plus the request's **live** status pulled from the DB at render time, shown as a status chip in the P5b vocabulary (`open` / `decided` / `closed` / `superseded`), reusing the P5c status-chip color vocabulary.
- R5. The **video step is not re-uploaded**: its media ref points at the already-uploaded proxy post's media URL; Portal embeds that URL. No journey code copies or re-stores media bytes.
- R6. The index page (`/`) links to existing journeys (a Journeys section mirroring the Streams section), and `GET /api/journeys` lists them.
- R7. Unknown slug → **404**. Malformed slug → 400 (reusing the stream-slug shape). A journey referencing a `request_id` that does not exist renders the step without a live status chip (or a neutral "unknown" marker) rather than 500 — the page never crashes on a dangling reference.
- R8. **Auth applies** exactly like the other Portal web pages: `/g/<slug>` is cookie-first (unauthenticated → login redirect); `/media/...` it links to already enforces `web_token_ok`; the JSON API (`PUT/GET/list /api/journeys`) requires the bearer token.
- R9. **Generic substrate:** nothing wool-crush-specific lives in Portal code (db/server/cli/client/templates). All game-specific content (slug `wool-crush`, step titles, artifact ids) lives only in the **fixture/demo/seed**, which is data, not Portal logic.
- R10. A **real-density fixture + seeded demo** exists: a wool-crush journey doc built from today's real artifacts (the uploaded proxy video post, the frame-picker request, style report `p_f6d5b8`, asset sheet `p_d7b881`, token-promotion request `req_ffb283`) so the page is verified against real content, not lorem ipsum. A `scripts/verify-journey.sh` serves the app and takes a Playwright screenshot at 1440x900.
- R11. Existing green behavior — requests, streams, posts, messages, before/after, view verdicts, P5b lifecycle, P5c context header, breadcrumbs, media serving — is unchanged.

### Acceptance Examples

- AE1. Given `portal journey post --slug wool-crush --title "Wool Crush" --doc journey.json` where `journey.json` holds ordered steps, when it runs, then a journey row exists for `wool-crush` and `GET /api/journeys/wool-crush` returns `{slug, title, steps}`.
- AE2. Given a journey posted at slug `s`, when the same slug is posted again with a different title and steps, then `GET /api/journeys/s` returns the **new** content, there is still exactly one row for `s`, and `/g/s` serves the new content at the same URL (update-in-place).
- AE3. Given a journey whose step references a media file `{owner_id: <video_post_id>, filename: <video>}` and a step with `request_id: <open request>`, when `GET /g/s` renders (authenticated), then the page contains an embedded `<video>` whose `src` is `/media/<video_post_id>/<video>`, a link to `/r/<request_id>`, and a status chip reading `open`.
- AE4. Given the referenced request is then decided (or closed/superseded) out-of-band, when `/g/s` is re-rendered, then the step's status chip reflects the **new** status — proving status is pulled live, not snapshotted into the doc.
- AE5. Given `GET /g/does-not-exist`, when rendered (authenticated), then the response is 404. Given `GET /g/s` **without** a valid token/cookie, then the response is a redirect to `/login` (parity with `/r`, `/s`).
- AE6. Given the index page `/`, when it renders and a journey exists, then it contains a link to `/g/<slug>` for that journey.
- AE7. Given a step whose `request_id` points at a non-existent request, when `/g/s` renders, then the page renders the step with no live chip (or a neutral marker) and does **not** 500.
- AE8. Given the wool-crush fixture (real artifacts seeded), when `/g/wool-crush` renders, then all five steps render in order with the video embedded, the frame-picker and token-promotion request links present with live status chips, and the style/asset report links present.
- AE9. Given the full suite, when `pytest -q` runs, then it is green including the update-in-place, live-status, 404, auth, and fixture-render tests.

### Scope Boundaries

- Only `gallery/db.py`, `gallery/server.py`, `gallery/cli.py`, `gallery/client.py`, `gallery/templates/**`, `gallery/static/**`, and `tests/**` change, **plus** the card-authorized `scripts/verify-journey.sh` and a seed-demo entry point (the polish bar mandates the verify script and a seeded demo; these are the only additions outside the file list, and they are data/tooling, not Portal logic).
- DB changes additive only — a **new** `journeys` table; no destructive change to `requests`/`streams`/`posts`/`messages`/`verdicts`.
- No re-upload of media. Journey media is referenced by existing `/media/<owner_id>/<filename>` URLs; the doc never carries bytes.
- No wool-crush vocabulary in Portal code (R9). The generic doc shape is the only contract.
- No new auth mechanism — reuse `web_token_ok` (cookie-first) for the page and `require_api_token` (bearer) for the API.
- HTML/interactive media is **linked**, not embedded inline on the journey page (it is served sandboxed with its own CSP + P5c context header); only video/image are embedded. Keeps the journey page's own CSP simple and avoids nested-sandbox surprises.
- No editing UI in-browser; journeys are posted/re-posted by the producer via CLI/API (matches the "producer posts and re-posts it" contract).

## Planning Contract

### Assumptions

- P5b + P5c landed: `requests` is at `user_version == 5`, status vocabulary is `open` / `decided` / `closed` / `superseded`, `db.TERMINAL_STATUSES == ("closed", "superseded")`, and `server.py` already holds `_STATUS_CHIP_STYLES` / `_STATUS_CHIP_DEFAULT_STYLE` (the P5c chip vocabulary the journey page reuses). Verified in `gallery/db.py` and `gallery/server.py` at spawn.
- Posts are **append-only and immutable** (`create_post` inserts; there is no update path) and streams are append logs — neither supports the update-in-place-at-a-stable-URL contract R2 demands. A dedicated slug-keyed table with upsert is therefore the correct primitive, not a post type. (Stated as a decision, not a silent assumption.)
- `db.connect()` / `_lock` / `_run_migrations` / `_add_column_if_missing` / `_validate_schema_version` are the established migration idiom; migration v6 mirrors v4/v5 exactly but creates a table (like `_migrate_v1`/`_migrate_v2` create tables) rather than adding columns.
- `Jinja2Templates` autoescapes `.html`, so producer-supplied step titles/summaries/captions rendered through `journey.html` are HTML-escaped — the deterministic, non-LLM way to keep producer text from injecting markup. The journey page is a normal Portal template (loads `/static/style.css`), unlike the sandboxed producer HTML, so it can rely on `style.css`.
- `_media_url(owner_id, filename)`, `_media_type_for(filename)`, `_safe_media_filename(filename)`, `SAFE_SEGMENT_RE`, `STREAM_SLUG_RE`, `_bounded_text` / `_bounded_optional_text`, `_validate_json_response_safe`, `_validate_slug`, and `MAX_BODY_JSON_BYTES` already exist in `server.py` and are reused for validation/URL-building rather than reinvented.
- The wool-crush artifact ids named on the card (`p_f6d5b8`, `p_d7b881`, `req_ffb283`, the proxy video post, the frame-picker request) are **real production ids** but are not present in a fresh test DB. The **test fixture** therefore *creates* stand-in artifacts (a video post, an HTML report post, requests) in the temp DB and posts a journey referencing them, so the render path is exercised at real structural density; the **seed demo** script posts the journey against a running Portal using whatever real ids exist there. The fixture proves the code; the seed reproduces the real page. This split is called out explicitly (Surprise-worthy — see Surprises guidance for the worker).

### Key Technical Decisions

- KTD1. **Migration v6 creates a `journeys` table**, keyed by a unique `slug`, via a new `_migrate_v6` appended to `MIGRATIONS` as `(6, _migrate_v6)`, plus `_validate_v6_schema` and a `version >= 6` branch in `_validate_schema_version`. Columns: `slug TEXT PRIMARY KEY`, `title TEXT NOT NULL`, `doc_json TEXT NOT NULL`, `created_at TEXT NOT NULL`, `updated_at TEXT NOT NULL`. Add the same `CREATE TABLE IF NOT EXISTS journeys (...)` to the base `SCHEMA` so fresh DBs are born with it (still reaching v6 via the migration/`user_version` path, mirroring how `_migrate_v1` both creates tables and the base schema pre-declares nothing conflicting). `slug` as PRIMARY KEY makes upsert a single `INSERT ... ON CONFLICT(slug) DO UPDATE`.
- KTD2. **`db.upsert_journey(slug, title, doc, *, created_at=None) -> dict`** performs the update-in-place: `INSERT INTO journeys (slug, title, doc_json, created_at, updated_at) VALUES (...) ON CONFLICT(slug) DO UPDATE SET title=excluded.title, doc_json=excluded.doc_json, updated_at=excluded.updated_at` (created_at preserved on conflict). `doc` is the full validated dict; `doc_json = json.dumps(doc)`. Add `db.get_journey(slug) -> dict | None` (returns `{slug, title, doc, created_at, updated_at}` with `doc = json.loads(doc_json)`, mirroring `_post_from_row`) and `db.list_journeys() -> list[dict]` (slug, title, updated_at, step_count derived from the doc, ordered by `updated_at DESC`). All under `connect()` + `_lock`, matching the module's transaction idiom.
- KTD3. **Doc validation is deterministic and lives in `server.py`** (`_validate_journey_doc(payload) -> dict`), not the DB. It enforces: `steps` is a list (bounded, e.g. ≤ `MAX_JOURNEY_STEPS = 100`); each step is an object with a bounded `title` (`_bounded_text`), optional bounded `summary` (`_bounded_optional_text`, larger cap e.g. `MAX_MESSAGE_TEXT_LENGTH`), optional `media` list (bounded, e.g. ≤ `MAX_STEP_MEDIA = 30`) whose refs each have `owner_id` matching `SAFE_SEGMENT_RE` and `filename` passing `_safe_media_filename` (+ optional bounded `caption`), and optional `request_id` matching `SAFE_SEGMENT_RE`. The whole serialized doc is bounded by `MAX_BODY_JSON_BYTES` and passed through `_validate_json_response_safe`. Invalid → `HTTPException(400)`. This is the "deterministic code for deterministic work" rule: structural validation by schema, not by LLM.
- KTD4. **API is three endpoints under bearer auth.** `PUT /api/journeys/{slug}` (or `POST` — choose `PUT` for idempotent update-in-place semantics; document the choice): `require_api_token`, `_validate_slug(slug)`, parse JSON object body, `title = _bounded_text(...)`, `doc = _validate_journey_doc(body)`, then `db.upsert_journey(slug, title, {"steps": ...})`, return the stored journey. `GET /api/journeys/{slug}`: bearer, 404 if absent. `GET /api/journeys`: bearer, returns `db.list_journeys()`. Slug validation reuses `_validate_slug` (same `STREAM_SLUG_RE` shape) so journeys and streams share one slug grammar.
- KTD5. **Web route `/g/{slug}` mirrors `/r` and `/s`.** `@app.get("/g/{slug}", response_class=HTMLResponse)`: `if not web_token_ok(request): return _login_redirect(request)`; `_validate_slug(slug)`; `journey = db.get_journey(slug)`; `if journey is None: raise HTTPException(404)`. Build a render context by resolving each step server-side (`_journey_step_context`): for each media ref, `url = _media_url(ref["owner_id"], ref["filename"])`, `media_type = _media_type_for(ref["filename"])` (→ `video` / `image` / `html`), `embed = media_type in {"video","image"}`; for `request_id`, one batched status lookup (see KTD6) yielding `{href: /r/<id>, status, exists}`. Render `journey.html`. Set `_maybe_set_cookie`. Add a `Referrer-Policy: no-referrer` header like `/s`.
- KTD6. **Live status is a single batched read**, not per-step queries. Collect all `request_id`s across steps, then one `SELECT id, title, status FROM requests WHERE id IN (...)` under `db._lock` (exact pattern of the existing `_request_summaries_for_posts`), producing `{id: {status, title}}`. Steps whose id is absent get `exists=False` and render without a chip (R7/AE7). Because this reads at render time, status is always live (AE4). Reuse `_STATUS_CHIP_STYLES` for the chip color; render the chip inline in the template with the P5c vocabulary.
- KTD7. **`journey.html` extends `base.html`** and renders the vertical story spine: a breadcrumb (`<a href="/">Index</a> / <span aria-current="page">{{ journey.title }}</span>`) matching `request.html`; an `<ol class="journey-spine">` where each `<li class="journey-step">` shows a step number node on a connecting rail, the step title, summary, a media block (looping refs: `<video controls>` / `<img>` / a media link), and — if the step has a request — a `/r/<id>` link with a status chip. Autoescape covers all producer text. New CSS in `gallery/static/style.css` (append a `journey-*` block; do not restyle existing classes) implements the spine: a left rail with numbered nodes, generous desktop spacing, media framed to a max width, picker-v3 polish. Desktop-first per the card (Portal is web/PC-first).
- KTD8. **CLI/client add a `journey` verb.** `client.upsert_journey(base_url, token, slug, title, doc) -> dict` = `_request("PUT", f"/api/journeys/{slug}", _auth_headers(token), json.dumps({"title": title, **doc}).encode())` (or a small `put_json` helper mirroring `post_json`). `client.get_journey` / `client.list_journeys` mirror `get_json`. CLI: `sub.add_parser("journey", ...)` with a subcommand `post` taking `--slug` (via `_stream_slug` type for shape parity), `--title`, and `--doc <path>` (a JSON file holding `{"steps":[...]}`; read + `json.loads`), calling `client.upsert_journey`; print the JSON result. Follows the exact shape of `cmd_stream` / `cmd_report`.
- KTD9. **Fixture + seed are data, not logic.** A pytest fixture (`tests/test_journeys.py` or a conftest helper) builds real-structure artifacts in the temp DB — a video post (upload a tiny mp4-typed file), an HTML report post, a frame-picker request, a token-promotion request — then posts a wool-crush journey doc referencing them, and asserts the `/g/wool-crush` render. A `scripts/seed_journey_demo.py` (or a `journey seed` behavior) posts the same doc shape against a running Portal using real ids passed as args/env, for the human demo. `scripts/verify-journey.sh` boots the server, hits `/g/wool-crush` (or the demo slug) in headless Playwright at 1440x900, and writes a screenshot artifact; the handoff states the conductor runs it if this sandbox cannot launch a browser (no unverified visual claim).

### Relevant Code and Patterns

- `gallery/db.py`: `SCHEMA`, `MIGRATIONS`, `_migrate_v1`/`_migrate_v2` (table-creating migrations), `_migrate_v5`/`_validate_v5_schema` (the additive idiom to mirror for `_validate_v6_schema`), `_validate_schema_version`, `_post_from_row` (JSON round-trip pattern for `doc_json`), `connect`/`_lock`/`now_iso`, `get_stream_by_id`/`get_post` (connection+lock idiom for the new `upsert_journey`/`get_journey`/`list_journeys`).
- `gallery/server.py`: `_STATUS_CHIP_STYLES`/`_STATUS_CHIP_DEFAULT_STYLE` (P5c chip vocabulary to reuse), `_request_summaries_for_posts` (the batched `WHERE id IN (...)` status read to mirror in KTD6), `_media_url`, `_media_type_for`, `_safe_media_filename`, `SAFE_SEGMENT_RE`, `_validate_slug`/`STREAM_SLUG_RE`, `_bounded_text`/`_bounded_optional_text`/`_validate_json_response_safe`/`_parse_body_field`/`MAX_BODY_JSON_BYTES`, `require_api_token`, `web_token_ok`/`_login_redirect`/`_maybe_set_cookie`, `web_index` (add the Journeys section context), `web_stream_detail`/`web_request_detail` (the cookie-first web-route shape to copy for `/g/{slug}`), `_list_stream_summaries` (mirror for a `_list_journey_summaries`).
- `gallery/client.py`: `_request`/`_auth_headers`/`get_json`/`post_json`/`post_multipart` — add `put_json` + `upsert_journey`/`get_journey`/`list_journeys` in the same thin style.
- `gallery/cli.py`: `cmd_stream`/`cmd_report` + their `add_parser`/`add_argument` blocks (mirror for `cmd_journey` and the `journey` subparser), `_stream_slug` type, `config.client_config()`, `_exit_client_error`.
- `gallery/templates/`: `base.html` (extend), `request.html`/`stream.html` (breadcrumb + section markup to match), `index.html` (Streams section to mirror for a Journeys section); new `journey.html`.
- `gallery/static/style.css` + `app.js`: append `journey-*` styles; no JS required (static render). Reference `request-list`/`stream-card` styling for visual consistency.
- `tests/conftest.py` (`data_dir`/`client`/`token` fixtures), `tests/test_web_streams.py` (`auth_headers`, `tiny_png_bytes`, `_create_request`, media-dir seeding helpers to reuse for building journey-referenced artifacts), `tests/test_view_requests.py`/`tests/test_api.py`/`tests/test_cli.py` (API/CLI/web test shapes), `tests/test_db_migrations.py` (v5 round-trip + `user_version` asserts to extend to v6).
- Board lessons: run tests as `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q`; after writing this plan doc, confirm it is committed (`git status --porcelain` empty) before handoff.

## Implementation Units

### U1. Migration v6 — `journeys` table

- **Goal:** A slug-keyed store for journey docs, created additively.
- **Requirements:** R1, R2; supports AE1, AE2.
- **Dependencies:** None.
- **Files:** Modify `gallery/db.py`; Test `tests/test_db_migrations.py`.
- **Approach:** Add `_migrate_v6` creating `journeys (slug TEXT PRIMARY KEY, title TEXT NOT NULL, doc_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)` (via `CREATE TABLE IF NOT EXISTS`). Add `_validate_v6_schema` asserting the table + its columns exist. Extend `_validate_schema_version` with `if version >= 6: _validate_v6_schema(conn)`. Append `(6, _migrate_v6)` to `MIGRATIONS`. Add the same `CREATE TABLE IF NOT EXISTS journeys (...)` to base `SCHEMA`.
- **Patterns to follow:** `_migrate_v1`/`_migrate_v2` (table creation), `_validate_v5_schema` (validator shape).
- **Test scenarios:** Legacy v5 db upgrades to `user_version == 6` with prior rows preserved and a usable `journeys` table; fresh db reports `user_version == 6` with `journeys` present; existing `user_version == 5` assertions updated to 6.
- **Verification:** Migration tests pass; `db._user_version` is 6 after connect.

### U2. db journey CRUD — upsert / get / list

- **Goal:** Update-in-place storage and reads for journeys.
- **Requirements:** R1, R2, R6; supports AE1, AE2, AE6.
- **Dependencies:** U1.
- **Files:** Modify `gallery/db.py`; Test `tests/test_journeys.py` (new) or a focused db test.
- **Approach:** `upsert_journey(slug, title, doc, *, created_at=None)` → `INSERT INTO journeys (...) VALUES (...) ON CONFLICT(slug) DO UPDATE SET title=excluded.title, doc_json=excluded.doc_json, updated_at=excluded.updated_at`, then return `get_journey(slug)`. `get_journey(slug)` → row → `{slug, title, doc: json.loads(doc_json), created_at, updated_at}` or `None`. `list_journeys()` → `SELECT slug, title, doc_json, updated_at FROM journeys ORDER BY updated_at DESC` mapped to `{slug, title, step_count: len(doc.get("steps", [])), updated_at}`. All under `connect()` + `_lock`, commit/rollback like `create_post`.
- **Patterns to follow:** `_post_from_row` JSON round-trip; `create_post`/`get_stream_by_id` lock+commit idiom.
- **Test scenarios:** upsert then get returns the doc; re-upsert same slug replaces title+steps and preserves `created_at`, exactly one row (`SELECT COUNT(*)==1`); `list_journeys` orders by recency with correct `step_count`; `get_journey` of unknown slug is `None`.
- **Verification:** db/journey tests pass; update-in-place is row-count-verified.

### U3. Doc validation + JSON API (PUT/GET/list)

- **Goal:** Bearer-authed journey post (update-in-place) + reads, with deterministic structural validation.
- **Requirements:** R1, R2, R6, R7 (400 on bad slug/doc), R8, R9; covers AE1, AE2.
- **Dependencies:** U2.
- **Files:** Modify `gallery/server.py`; Test `tests/test_journeys.py`.
- **Approach:** Add `MAX_JOURNEY_STEPS`, `MAX_STEP_MEDIA`, and `_validate_journey_doc(payload) -> dict` per KTD3 (bounds steps/media; validates each ref's `owner_id`/`filename`, optional `request_id`, `caption`; bounds sizes; `_validate_json_response_safe`). Add `PUT /api/journeys/{slug}` (`require_api_token`, `_validate_slug`, `_json_object_body`, `title=_bounded_text(...)`, `doc=_validate_journey_doc(body)`, `db.upsert_journey`), `GET /api/journeys/{slug}` (404 if absent), `GET /api/journeys` (list). Return the stored journey dict.
- **Patterns to follow:** `create_stream`/`create_stream_post` validation + `require_api_token`; `_parse_body_field`/`_validate_json_response_safe`; `_validate_slug`.
- **Test scenarios:** valid PUT stores + returns the doc; second PUT same slug replaces (GET shows new); GET unknown → 404; list returns posted journeys; malformed slug → 400; over-long doc / bad media ref (`owner_id` with `/`, unsafe filename) / non-list steps → 400; missing bearer → 401.
- **Verification:** API tests pass.

### U4. CLI + client `journey` verb

- **Goal:** Producers post/re-post and read journeys from the CLI.
- **Requirements:** R1, R2; covers AE1, AE2.
- **Dependencies:** U3.
- **Files:** Modify `gallery/cli.py`, `gallery/client.py`; Test `tests/test_cli.py`.
- **Approach:** `client`: add `put_json` (mirror `post_json` with `PUT`) and `upsert_journey(base_url, token, slug, title, doc)`, `get_journey`, `list_journeys`. `cli`: add `cmd_journey` + a `journey` subparser with a `post` subcommand (`--slug` via `_stream_slug`, `--title` required, `--doc` path to a JSON file → `json.loads`), calling `client.upsert_journey` and printing the result; `_exit_client_error` on failure. (Optional `list`/`get` subcommands if cheap; keep minimal.)
- **Patterns to follow:** `cmd_stream`/`cmd_report` + their parser registration; `config.client_config()`.
- **Test scenarios:** `journey post --slug s --title T --doc file.json` produces a journey whose API view shows the steps; re-posting replaces; follows the server-injection/fixture pattern `tests/test_cli.py` already uses.
- **Verification:** CLI tests pass.

### U5. `/g/{slug}` web route + step/status resolution

- **Goal:** Render the journey with chrome, live status, embedded video, and safe links.
- **Requirements:** R3, R4, R5, R7, R8, R11; covers AE3, AE4, AE5, AE7.
- **Dependencies:** U2.
- **Files:** Modify `gallery/server.py`; Add `gallery/templates/journey.html`; Test `tests/test_journeys.py`.
- **Approach:** Add `_journey_status_map(step_request_ids) -> dict` (batched `WHERE id IN (...)`, KTD6) and `_journey_step_context(step, status_map)` (resolve media refs → `{url, media_type, embed, caption, label}`; resolve `request_id` → `{href, status, exists}`). Add `@app.get("/g/{slug}")` per KTD5 (cookie-first, `_validate_slug`, 404 on missing, render `journey.html`, `_maybe_set_cookie`, `Referrer-Policy: no-referrer`).
- **Patterns to follow:** `web_stream_detail`/`web_request_detail` route shape; `_request_summaries_for_posts` batched read; `_media_url`/`_media_type_for`.
- **Test scenarios:** authed `/g/s` renders steps in order with embedded `<video>` `src=/media/<owner>/<file>`, `/r/<id>` link, live status chip; changing the request's status then re-GET shows the new chip (live); unknown slug → 404; unauth → login redirect; dangling `request_id` renders without a chip and no 500.
- **Verification:** Web/route tests pass; live-status test flips status and re-asserts.

### U6. `journey.html` template + journey CSS (vertical story spine)

- **Goal:** Deliberate desktop-first vertical spine at picker-v3 polish.
- **Requirements:** R3, R4, R6; covers AE3, AE6, AE8.
- **Dependencies:** U5.
- **Files:** Add `gallery/templates/journey.html`; Modify `gallery/static/style.css`; Modify `gallery/templates/index.html` (Journeys section) and `web_index` context.
- **Approach:** `journey.html` extends `base.html`: breadcrumb (`Index / <title>`), `<h1>{{ journey.title }}</h1>`, `<ol class="journey-spine">` of `<li class="journey-step">` (number node + rail, title, summary, media loop with `<video controls>`/`<img>`/media link, optional `/r/<id>` link + status chip using `_STATUS_CHIP_STYLES` inline or a CSS class per status). Append a `journey-*` CSS block to `style.css` (left rail, numbered nodes, spacing, framed media, max content width). `index.html`: add a Journeys section mirroring Streams, driven by a new `journeys` context key from `web_index` (`_list_journey_summaries()` → slug/title/step_count/updated_at, linking `/g/<slug>`).
- **Patterns to follow:** `request.html` breadcrumb + `data-*` sections; `index.html` Streams section; existing `request-list`/`stream-card` CSS for consistency.
- **Test scenarios:** rendered `/g/s` HTML contains the spine markup, ordered step titles, embedded video, and status chips; `/` contains a `/g/<slug>` link when a journey exists (AE6); autoescape proven by a step title containing `<script>` rendering escaped.
- **Verification:** Template tests pass; index-link test passes.

### U7. Real-density fixture, seeded demo, and verify script

- **Goal:** Verify the page against real content and provide the mandated visual check.
- **Requirements:** R9, R10; covers AE8.
- **Dependencies:** U5, U6.
- **Files:** Add `tests/test_journeys.py` fixture (or conftest helper); Add `scripts/seed_journey_demo.py` (or a CLI `journey seed`); Add `scripts/verify-journey.sh`.
- **Approach:** Fixture: build real-structure artifacts in the temp DB (a video-typed post via `create_stream_post` with an mp4 upload, an HTML report post, a frame-picker request and a token-promotion request via `/api/requests`), then PUT a wool-crush journey doc referencing their ids/filenames, and assert `/g/wool-crush` renders all steps (video embedded, both request links with live chips, both report links). Seed demo: a script that posts the same doc shape to a running Portal using real ids from args/env (no wool-crush constants baked into Portal code — the constants live only in the script/fixture, R9). `scripts/verify-journey.sh`: start uvicorn on a temp port with a seeded demo journey, run headless Playwright to screenshot `/g/<slug>` at 1440x900 into an artifact path, and exit non-zero on failure; document that the conductor runs it if this sandbox cannot launch a browser.
- **Patterns to follow:** `tests/test_web_streams.py` artifact-seeding helpers; `tiny_png_bytes`; `config.media_dir()` layout.
- **Test scenarios:** fixture render asserts five ordered steps + embedded video + live chips (AE8); the seed script is import-clean and parametric (no hard-coded server assumptions beyond args/env).
- **Verification:** `tests/test_journeys.py` green; `scripts/verify-journey.sh` present and executable; handoff states whether the visual check was actually run here or is deferred to the conductor.

## Verification Contract

| Gate | Applies to | Done signal |
|---|---|---|
| Migration round-trip | U1 | Legacy v5 db upgrades to `user_version == 6`, prior rows preserved, `journeys` present. |
| Journey CRUD + update-in-place | U2, U3, U4 | upsert/get/list work; re-post same slug replaces content with exactly one row; `created_at` preserved. |
| API validation + auth | U3 | valid PUT stored; bad slug/doc/media-ref → 400; unknown GET → 404; missing bearer → 401. |
| Page render + live status | U5, U6 | authed `/g/<slug>` renders ordered steps, embedded video (referenced, not re-uploaded), `/r/<id>` links, and **live** status chips that change when the request status changes. |
| Auth + 404 | U5 | unauth `/g/<slug>` → login redirect; unknown slug → 404; dangling `request_id` renders without a chip, no 500. |
| Index link | U6 | `/` links to `/g/<slug>` for existing journeys. |
| Real-density fixture | U7 | wool-crush fixture renders all five real-structure steps end-to-end. |
| Desktop visual check | U7 | `scripts/verify-journey.sh` produces a 1440x900 screenshot; run here if a browser is available, else explicitly deferred to the conductor in the handoff (no unverified visual claim). |
| Generic substrate | all | No wool-crush string/constant in `gallery/**`; game-specific content only in `tests/**` + `scripts/**`. |
| Full suite | all | `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q` fully green. |
| Diff boundary | all | Changes limited to `gallery/db.py`, `gallery/server.py`, `gallery/cli.py`, `gallery/client.py`, `gallery/templates/**`, `gallery/static/**`, `tests/**`, `scripts/verify-journey.sh`, and the seed-demo script. |

## Definition of Done

- Migration v6 is additive, creates the `journeys` table, mirrors the v1/v5 patterns, and `test_db_migrations.py` proves the v5→v6 round-trip and `user_version == 6`.
- `db.upsert_journey` / `get_journey` / `list_journeys` implement update-in-place (one row per slug, `created_at` preserved on re-post) with JSON round-trip.
- `PUT/GET/list /api/journeys` are bearer-authed, deterministically validate the doc structure and media/request refs, and reject malformed input with 400 / absent with 404.
- `gallery/cli.py` exposes a `journey post` verb (`--slug`/`--title`/`--doc`) over `client.upsert_journey`, following the existing verb shape.
- `/g/<slug>` renders the journey with full Portal chrome (auth, breadcrumbs) as a deliberate desktop-first vertical story spine: per step title, summary, embedded/linked media (video **referenced**, not re-uploaded), a `/r/<id>` link, and the request's **live** status chip in the P5b vocabulary; unknown slug → 404; unauth → login redirect; dangling refs never 500.
- The index links existing journeys; `GET /api/journeys` lists them.
- Nothing wool-crush-specific lives in Portal code; the real-density fixture + seed + `scripts/verify-journey.sh` (1440x900) verify the page against real content, with the visual check either run here or explicitly deferred to the conductor.
- The full pytest command passes with the `UV_CACHE_DIR` override, and the diff stays within the allowed files.
