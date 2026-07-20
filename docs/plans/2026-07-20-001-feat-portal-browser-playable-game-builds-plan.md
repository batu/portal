---
title: "feat(portal): browser-playable game builds with device previews - Plan"
type: feat
date: 2026-07-20
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: trello-card:6gSFRYWc
execution: code
origin: "trello-card:6gSFRYWc"
trello: "https://trello.com/c/6gSFRYWc"
---

# feat(portal): browser-playable game builds with device previews - Plan

## Goal Capsule

| Field | Value |
|---|---|
| Objective | Let a published game release optionally carry a **self-contained web bundle** (the same Vite `dist/` that Capacitor wraps) so `/games/<slug>` can launch the actual game inside a sandboxed iframe on its version tab, with device-preset and orientation controls that change the real preview viewport. Native APK download, video, poster, changelog, and permanent links stay exactly as they are. |
| Authority | Trello card `6gSFRYWc` first. Then the named seams: `gallery/server.py` (`publish_game_build`, `_write_game_upload`, `_resolve_game_release_path`, `_game_file_response`, `_game_page_context`), `gallery/db.py` (`game_builds` schema + `MIGRATIONS` + `create_game_build`), `gallery/client.py` (`publish_game_build`), `gallery/cli.py` (`cmd_game` / `game publish` parser), `gallery/templates/game.html`, `gallery/static/app.js` (build-tab controller, `app.js:481-520`), `gallery/static/style.css`, `tests/test_games.py`, `README.md`. |
| Execution profile | Additive: one nullable-by-default schema column (`_migrate_v11`), one optional multipart field on the existing publish endpoint, one new public static-serving route, one new UI block on the game page. No new dependency (`zipfile` is stdlib). No change to the behavior of any existing release. |
| Stop conditions | Portal repo only — do **not** touch fabrikav2 (card scope fence); if a publisher-side command is needed there, record a follow-up card. Do not add Appetize/BrowserStack/paid emulation. Do not change the existing artifact/video/poster contract or download URLs. Do not make the preview iframe same-origin. Commit on the card branch; the conductor lands it — no PR. |
| Completion signal | `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q` fully green (existing + new tests), `uv run ruff check .` clean, and browser screenshots of `/games/<slug>` showing the preview playing at ≥2 device presets in both orientations plus a preview-less release rendering normally. |

---

## Product Contract

### Summary

Portal already stores each game release as an immutable directory `data/games/<slug>/<version>/` holding an APK/zip artifact, an MP4, and a JPEG poster, with rows in `game_builds` and a tabbed release page (`gallery/templates/game.html`, tab controller in `gallery/static/app.js:481-520`). This card adds a **fourth, optional** artifact per release: a web bundle.

Publisher passes `--web <bundle.zip>` to `portal game publish`. The server extracts it into `<release_dir>/web/` under strict containment rules and records the entry file in a new `web_preview_path` column (empty string = no preview, which is every existing row). The game page then renders, above the video, a **play surface**: a sandboxed iframe pointed at a new public route, wrapped in a device frame whose CSS width/height come from a preset selector plus a portrait/landscape toggle.

One focused device at a time (card's chosen play-first workflow). Version tabs remain the history selector; each tab owns its own play surface.

### Problem Frame

Reviewing a gameplay change today means either watching a recorded MP4 (no interaction) or installing an APK on a physical device (slow, and gated on the Mac mini build pipeline). Designers need a permanent link that lets them *touch* the current build in seconds. Physical Pixel/iPhone runs stay the release gate; this is a rapid design-review surface and must say so on the page.

### Decisions (with rationale)

1. **Bundle format = zip of the Vite `dist/` directory, entry `index.html`.** Vite output is already relative-path-friendly when built with `base: './'`; a zip keeps one upload field and reuses the existing `_stream_upload` size cap. If the built bundle uses absolute `/assets/...` paths, the preview 404s — the plan handles this by serving the bundle from a directory route and documenting the `base: './'` requirement in README, and by treating a fabrikav2-side build-config change as the follow-up card, not this diff.
2. **Sandboxed cross-origin-ish isolation, not same-origin.** The iframe gets `sandbox="allow-scripts"` **without** `allow-same-origin`, which gives the bundle an opaque origin: it cannot read Portal cookies/localStorage, cannot reach `document.parent`, and cannot use Portal's auth. Responses from the preview route additionally carry `Content-Security-Policy: sandbox allow-scripts`, `X-Content-Type-Options: nosniff`, and `Referrer-Policy: no-referrer` so a direct hit on the URL is inert too. This is the same defensive posture as the existing interactive-view handling — verify that claim during implementation and report divergence in SURPRISES.
3. **Public read, authenticated publish.** Preview files are served by a `public-` style route with no token, matching `public_download_game_build` / `public_watch_game_build`. Publishing still requires `require_api_token`.
4. **Device presets change the real viewport.** The iframe element's CSS `width`/`height` are set in device-independent pixels from the preset table; the game's own media queries / `window.innerWidth` react for real. Orientation swaps the two numbers.
5. **Safe-area is shown as a guide overlay, not injected into the game.** Real `env(safe-area-inset-*)` inside the iframe would require the game to be built with viewport-fit cover and Portal to inject CSS into an untrusted bundle — an injection seam we will not open. Instead the device frame draws notch/home-indicator inset guides at the preset's real inset values, so a designer can see what the OS will cover. Genuine in-frame safe-area emulation is a **follow-up card in fabrikav2** (the game reads the insets), explicitly out of this diff. This is a deliberate narrowing of the card's "safe-area context" wording — call it out in the handoff.
6. **Mouse works because nothing intercepts it.** A normal iframe forwards mouse down/move/up; games written against Pointer Events get drag for free. The only requirement is that the device chrome must not overlay the play area with a click-catching element — the inset guides use `pointer-events: none`.

### Presets

| Preset | Portrait CSS px | Class |
|---|---|---|
| iPhone SE | 375 × 667 | compact iPhone |
| iPhone 15 Pro | 393 × 852 | standard iPhone Pro |
| iPhone 15 Pro Max | 430 × 932 | Pro Max |
| Pixel 8 | 412 × 915 | Pixel |
| iPad (10.9") | 820 × 1180 | tablet |

Default: iPhone 15 Pro, portrait. Landscape swaps dimensions.

### Explicit states

- **Absent** — release has no `web_preview_path`: render no play surface, instead a one-line note ("No browser preview for this build — download the native build below"). No orphaned/disabled controls.
- **Loading** — skeleton + "Starting build…" until the iframe's `load` event.
- **Failure** — iframe fails to load or a ~15s timeout elapses without `load`: replace the surface with an error state naming the release and offering the download link.
- **Always** — a persistent label: "Browser preview — rapid design review. Not native-device or performance proof; verify on a real device before release."

---

## Implementation

### Step 1 — Schema (`gallery/db.py`)

- Add `_migrate_v11(conn)`: `_add_column_if_missing(conn, "game_builds", "web_preview_path", "web_preview_path TEXT NOT NULL DEFAULT ''")`, plus the post-condition guard the v10 migration uses (`raise RuntimeError("schema v11 missing game_builds column: web_preview_path")`).
- Register `(11, _migrate_v11)` in `MIGRATIONS`; add `web_preview_path` to the `game_builds` column set in the schema-assertion dict (`db.py:359`) and to the `CREATE TABLE` body for fresh databases.
- `create_game_build(...)`: new keyword-only `web_preview_path: str = ""`, threaded into the INSERT.
- Nothing else changes — `get_game`, `list_games`, delete/trash all use `SELECT *` / directory moves and pick the new column up for free. **Verify** `delete_game_build`'s `shutil.move` of the release dir carries `web/` along (it moves the whole directory, so it should).

### Step 2 — Publish endpoint (`gallery/server.py`)

- Add module constants near the existing `GAME_*` ones: `GAME_WEB_DIR = "web"`, `GAME_WEB_ENTRY = "index.html"`, `MAX_GAME_WEB_FILES = 2000`, `MAX_GAME_WEB_UNCOMPRESSED_BYTES` (start at 256 MB), and an allowed-extension set for extracted members (`.html .htm .js .mjs .css .json .wasm .png .jpg .jpeg .webp .gif .svg .ico .mp3 .ogg .wav .m4a .woff .woff2 .ttf .txt .map`).
- `publish_game_build` gains `web: UploadFile | None = File(None)`. When present:
  1. Stream it to `release_dir / "_web.zip"` via the existing `_write_game_upload` (reuses the size cap).
  2. Extract with a new `_extract_game_web_bundle(zip_path: Path, dest: Path) -> str` helper.
  3. `unlink` the zip; store the returned entry-relative path (`"web/index.html"`, or `"web/<sub>/index.html"` when the zip has a single top-level directory) in `web_preview_path`.
- The existing `except Exception: shutil.rmtree(release_dir)` wrapper already gives atomic cleanup — keep the new work inside it.
- `_extract_game_web_bundle` rules (each a `HTTPException(400, ...)` with a specific detail):
  - reject members whose name is absolute, contains `..` segments, or whose resolved path escapes `dest` (zip-slip);
  - reject symlink / non-regular members (check `ZipInfo.external_attr >> 16 & 0o170000`);
  - reject > `MAX_GAME_WEB_FILES` members or a summed `file_size` over the uncompressed cap (checked from the central directory *before* extracting, defeating zip bombs);
  - reject unlisted extensions;
  - require an `index.html` at the bundle root or at the single common top-level directory; return its path relative to the release dir.
- Response dict gains `"preview_url"`: `f"/games/{slug}/builds/{quote(version, safe='')}/play/"` when a preview exists, else `None`.

### Step 3 — Serving route (`gallery/server.py`)

```
@app.get("/games/{slug}/builds/{version}/play/{path:path}")
def public_play_game_build(slug: str, version: str, path: str = "")
```

- `_validate_game_release_ref`; load the build; 404 if `web_preview_path` is empty.
- Empty `path` → serve the recorded entry file; otherwise resolve `Path(build["web_preview_path"]).parent / path` through the **existing** `_resolve_game_release_path`, which already does the `relative_to(release_root)` containment check and `is_file()` guard. Do not write a second containment implementation.
- Serve via `_game_file_response(..., public=True, download=False, fallback_media_type="application/octet-stream")`, then add the isolation headers on the returned response: `Content-Security-Policy: sandbox allow-scripts`, `X-Content-Type-Options: nosniff`, `X-Frame-Options` **omitted** (the page must frame it; rely on CSP sandbox + iframe sandbox instead). Prefer adding an optional `extra_headers` kwarg to `_game_file_response` over mutating the response at the call site, matching how that helper already centralizes headers.
- Note the trailing-slash contract: the page frames `.../play/` so that relative asset URLs inside `index.html` resolve against the play directory.

### Step 4 — Page context + template

- `_game_page_context`: for each build, set `build["preview_url"] = f"/games/{slug}/builds/{encoded_version}/play/" if build["web_preview_path"] else None` (mirroring the existing `download_url` / `video_url` construction at `server.py:1826-1836`).
- `game.html`: inside each release panel, above `.release-media`, render `{% if build.preview_url %}` a `<section class="play-surface" data-play-surface>` containing:
  - the preset `<select data-device-preset>` and an orientation toggle `<button data-orientation-toggle>`;
  - `<div class="device-frame" data-device-frame>` with the inset guide elements (`pointer-events: none`) and
    `<iframe data-play-frame data-src="{{ build.preview_url }}" sandbox="allow-scripts" allow="autoplay; gamepad" loading="lazy" title="Browser preview of {{ game.title }} {{ build.version }}"></iframe>`;
  - loading / error / disclaimer nodes.
  - `{% else %}` the "no browser preview" note.
- Lazy-load exactly like the video does today: only the first (active) panel gets a real `src`; other panels keep `data-src` until their tab is selected. This also stops five hidden games from all running at once.

### Step 5 — `gallery/static/app.js`

- Extend the existing build-tab `select()` (app.js:486-506): when activating a panel, promote its `data-src` to `src` on `[data-play-frame]`; when deactivating, **clear `src`** so the previously-focused game stops running.
- New `initPlaySurface(surface)` per `[data-play-surface]`: preset table (the five entries above), reads `select` + orientation state, writes `--device-w` / `--device-h` CSS custom properties on the `.device-frame`, and applies the preset's inset values to the guide elements. Persist the chosen preset+orientation in `localStorage` so it survives tab switches and reloads (one key for the whole page, not per build).
- Loading/error: hide the skeleton on the iframe `load` event; a 15s `setTimeout` armed at `src` assignment and cleared on `load` flips to the error state.
- Match the file's existing style: `var`, no optional chaining, `Array.prototype.slice.call(...)` — it is deliberately ES5-flavored.

### Step 6 — `gallery/static/style.css`

`.device-frame { width: var(--device-w); height: var(--device-h); }` with the iframe filling it at `border: 0; width: 100%; height: 100%; display: block;`, a `max-width: 100%` + `transform: scale()`-free fallback for narrow viewports (prefer letting the frame scroll horizontally over scaling, so px measurements stay honest), plus the loading/error/disclaimer styling. Follow existing tokens in the file rather than introducing new colors.

### Step 7 — client + CLI

- `client.publish_game_build`: optional `web_path: str | None = None`; when set, append to the `files` list as field `web`. Read the existing multipart helper (`post_multipart`, client.py:64) before editing to match its file-tuple shape.
- `cli.py`: `gp.add_argument("--web", help="Zip of the built Vite web bundle (dist/) for the browser preview")` on the `game publish` parser; pass through in `cmd_game`; print the returned `preview_url` (absolutized like `game_url` already is) when non-null.

### Step 8 — README

A short subsection under the games/publishing docs: what `--web` expects (a zip of `dist/`, built with Vite `base: './'`), that the preview is design review only, the device presets available, and that releases without `--web` are unchanged.

---

## Verification

New tests in `tests/test_games.py` (reuse the existing publish fixtures/helpers — read them first):

1. Publish with `--web`/`web=` → 200, response `preview_url` non-null, `GET .../play/` returns the entry HTML with `Content-Security-Policy` containing `sandbox`.
2. Asset fetch: `GET .../play/assets/app.js` returns the file with a JS content type.
3. **Containment:** a zip containing `../evil.txt` is rejected 400 and writes nothing outside the release dir; `GET .../play/../../../etc/passwd` (and a URL-encoded variant) 404s.
4. Zip-bomb / count caps reject with 400.
5. Disallowed member extension (e.g. `.sh`) rejected 400.
6. Publish **without** `web` → `web_preview_path == ""`, `preview_url is None`, `GET .../play/` 404s, and the page still renders with the download button (assert on the "No browser preview" copy).
7. Migration: an existing v10 DB with a build row opens and reads back with `web_preview_path == ""`.
8. Delete: removing a release with a preview moves `web/` to trash and makes `/play/` 404.
9. Public access: `/play/` works with no auth cookie; `POST /api/games/.../builds` without a token still 401s.

Commands: `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q tests/test_games.py` then the full `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q`; `uv run ruff check .`.

**Visual gate (evidence stage, not this stage):** publish a real Marble Run release with a web bundle; screenshot `/games/marble-run` showing the game running at iPhone SE portrait, iPhone 15 Pro Max landscape, and iPad; screenshot an older preview-less release; and install/launch the same release's APK on Pixel 6a `27091JEGR22183` to confirm the native path is untouched.

---

## Risks & Open Questions

- **Q1 — Vite `base`.** If fabrikav2's build emits absolute `/assets/...` URLs, the preview will 404 on assets even though extraction succeeded. Detection: test 2 above against a realistic bundle. Remedy inside this card's fence: document the `base: './'` requirement; the fabrikav2 build-config change is a follow-up card.
- **Q2 — Capacitor runtime.** A Vite game that calls Capacitor plugins (haptics, status bar) will throw in a bare browser. The preview is explicitly "the web layer only"; the failure state and disclaimer copy should not promise plugin parity. Worth confirming with Batu whether Marble Run touches any plugin at boot.
- **Q3 — Bundle size.** The web bundle rides the existing `POST_UPLOAD_SOFT_CAP_BYTES` used by `_write_game_upload`; check what that cap actually is before assuming it is generous enough for a game with audio.
- **Q4 — Storage growth.** Every release now keeps a full `dist/` forever. Acceptable for the immutable model; flag if `data/games` growth becomes a real problem.
- **R1 — Untrusted bundle.** Mitigated by opaque-origin sandboxing (no `allow-same-origin`), CSP sandbox on direct hits, extension allowlist, and the existing containment helper. The residual risk is a bundle that phones out over the network; accepted, since the same code already ships inside the APK.
