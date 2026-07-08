---
title: "feat: Add before/after request review views"
type: feat
status: active
date: 2026-07-08
origin: "trello-card:jAQ8bS6C"
trello: "https://trello.com/c/jAQ8bS6C"
spec: docs/portal-spec.md
---

# feat: Add before/after request review views

## Summary

Add the human review UI for requests that carry an out-of-band before image: a side-by-side view with the before image pinned and unselectable, plus a toggle view that blinks a selected candidate against the before image in the same frame. The implementation should reuse the existing FastAPI/Jinja request page, vanilla `gallery/static/app.js`, and already-landed `before_media_*` request storage while preserving verdict indexing and unchanged rendering for requests without a before image.

---

## Problem Frame

The Portal spec defines optional before images for decision requests so a reviewer can compare a prior visual state with new candidates. Storage and basic alias handling are present in this worktree, but the request page still renders only selectable variants, so reviewers cannot distinguish the non-selectable before image or use the requested blink comparison interaction.

---

## Assumptions

*This plan was authored in pipeline mode without synchronous user confirmation. The items below are agent inferences that fill gaps in the input and should be reviewed before implementation proceeds.*

- The dependency work for request-row before storage has landed before implementation starts. In this worktree, `gallery/db.py` already has `before_media_path` and `before_media_type`, `db.KINDS` already includes `before-after`, and `gallery/server.py` already accepts a multipart `before` upload.
- The `before-after` kind should remain stored as `before-after` for display/context while sharing pick-one verdict semantics through existing selected-index validation.
- The default view can be expressed as template state and data attributes rather than a persisted user preference.
- Visual verification can be satisfied by `TestClient` markup assertions for this stage's acceptance criteria; a real-browser pass is useful if the implementation changes enough CSS/JS to create layout risk.

---

## Requirements

- R1. For requests with `before_media_path`, `/r/{req_id}` renders a visible BEFORE block whose media URL points at the request's before media.
- R2. The BEFORE block is visually distinct, pinned before candidates in side-by-side mode, carries no variant number, and is never selectable.
- R3. Candidate variants remain indexed 1..N exactly as today; verdict submission continues to accept only real variant indices.
- R4. The page provides a small view switcher with `side-by-side` and `toggle` options whenever before media exists.
- R5. Side-by-side view displays before media first and candidates in the normal candidate grid.
- R6. Toggle view lets the reviewer select a candidate and blink between that candidate and the before image in the same visual frame by tapping the selected candidate or pressing Space.
- R7. Toggle mode is keyboard accessible: the relevant controls are focusable, Space triggers the blink action, and focus state is visible.
- R8. Requests with kind `before-after` default the page to toggle view and keep pick-one verdict semantics.
- R9. Requests with before media and other accepted kinds default the page to side-by-side view.
- R10. Requests without `before_media_path` render the existing request page behavior and key markup unchanged.
- R11. Keep implementation inside the scope fence: `gallery/templates/request.html`, `gallery/static/`, `gallery/server.py` for validation/template context only, `gallery/db.py` only if a read helper is actually needed, and `tests/test_before_after.py`.
- R12. Do not change `/api/streams` handlers, verdict flow, variant indexing, media serving policy, CLI behavior, client helpers, schema migrations, or request creation semantics beyond any missing validation alias fallback discovered during implementation.

---

## Card Acceptance Criteria Trace

| Card acceptance criterion | Requirements | Units | Test scenario anchor |
|---|---|---|---|
| Request with before contains BEFORE block, toggle markup, and view switcher | R1, R4, R5, R6 | U1, U2, U3 | U2/U3 before-page markup tests |
| Before never appears as a selectable variant | R2, R3 | U1, U2, U3 | U2 selectable-variant and data-index tests |
| Verdict on variant 1..N still validates | R3, R8 | U4 | U4 web/API verdict tests |
| `kind='before-after'` accepted at creation, behaves as pick-one, defaults toggle | R8 | U1, U3, U4 | U4 before-after creation/default/verdict tests |
| Request without before renders unchanged | R10 | U2, U3, U4 | U4 no-before snapshot-ish markup test |

---

## Scope Boundaries

- No changes to stream API handlers, stream pages, stream post creation, or stream storage.
- No changes to request/variant/verdict table shape, migration versioning, or 1-based variant convention.
- No change that stores the before image as a variant row or submits it as a selected index.
- No changes to `gallery/cli.py`, `gallery/client.py`, README docs, deploy files, or dependency declarations.
- No external JavaScript libraries, frontend framework, or build step.
- No visual annotation, crop/pin tools, comment-flow changes, or new verdict schema.

### Deferred to Follow-Up Work

- Persisting a reviewer-specific view preference across page loads.
- Richer animation controls for blink timing or opacity beyond the minimal tap/Space flick needed for this card.
- CLI/help documentation for `--before` unless a later documentation card requests it.

---

## Context & Research

### Relevant Code and Patterns

- `docs/portal-spec.md` section 6 defines before images as out-of-band request-row media, not variants, with side-by-side and toggle review views.
- `gallery/server.py` owns request creation, `/r/{req_id}` template context, web auth, media URL conventions, and the web decide route.
- `gallery/db.py` currently includes `before_media_path`, `before_media_type`, and `before-after` in `KINDS`; `get_request()` returns the request row plus ordered variants and latest verdict.
- `gallery/templates/request.html` renders the current request detail page and variant grid; it already treats `before-after` like pick-one in the hint text.
- `gallery/static/app.js` owns client-side variant selection and already includes `before-after` in the pick-one kind map.
- `gallery/static/style.css` defines the existing compact mobile-first card, variant, button, focus-adjacent, and responsive media patterns to extend.
- `tests/test_api.py` already covers before upload persistence outside variants and basic before-after pick-one browser flow; this card needs focused UI/view tests in `tests/test_before_after.py`.
- `tests/conftest.py` isolates `GALLERY_DATA_DIR`, initializes config, and resets the DB connection for `TestClient` coverage.

### Institutional Learnings

- No repo-local `docs/solutions/` directory exists. Relevant institutional context is in `docs/portal-spec.md`, existing Portal plan files under `docs/plans/`, the current tests, and the twf worker instruction to use the board-specific pytest invocation with the uv cache override.

### External References

- External research is not needed. The feature follows existing FastAPI/Jinja/TestClient patterns and uses vanilla browser APIs already established in the repo.

---

## Key Technical Decisions

- Use a compact server-derived before-media view model for `request.html` rather than making the template infer URLs and defaults from raw row fields. This keeps Jinja branching small and makes tests assert the actual context-driven behavior.
- Keep `before-after` stored as a request kind alias with pick-one semantics instead of normalizing it to `pick-one` on read. The UI needs the original kind to default to toggle view and display the kind tag.
- Render the before image outside the selectable `.variant` set so existing JS selection and verdict submission cannot accidentally include it.
- Extend the existing vanilla JS selection layer instead of adding a separate app. The script should discover before-after markup only when present and leave no-before request pages on the current path.
- Use CSS classes and hidden states for mode switching. The page can include both side-by-side and toggle-specific markup when before media exists, with the active mode controlled by data attributes/classes.
- Make blink activation depend on an already selected candidate. Tapping an unselected candidate should select it first; tapping the selected candidate or pressing Space should flick the comparison.
- Keep all media URLs same-origin and consistent with existing `/media/{req_id}/{filename}` auth behavior; do not propagate new token handling or alter media serving.

---

## Open Questions

### Resolved During Planning

- Should the before image be stored or rendered as variant index 0? No. The spec and card explicitly reject this because variants are 1-based and selectable.
- Should `before-after` require a distinct verdict type? No. It behaves as pick-one for selected indices and latest-wins verdict flow.
- Should no-before requests get a view switcher? No. They should render as today.
- Should this card alter CLI or stream surfaces? No. The scope fence excludes them.

### Deferred to Implementation

- Exact template variable names for before media and default mode: choose small names that match local `server.py` view-model style.
- Exact blink duration and CSS class names: pick the simplest accessible implementation that makes the before/candidate difference visible without introducing timing controls.
- Whether `gallery/db.py` needs a read helper: use existing `get_request()` if practical; add a helper only if it materially simplifies template context without widening behavior.

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

| Request state | Initial UI | BEFORE media | Candidate selection | Verdict behavior |
|---|---|---|---|---|
| No `before_media_path` | Existing variant grid | Not rendered | Existing JS only | Existing behavior |
| Has before, kind `before-after` | Toggle view | Rendered as comparison baseline | Pick-one selection, tap/Space on selected candidate blinks | Selected index must be 1..N |
| Has before, other kind | Side-by-side view | Pinned before candidates, non-selectable | Existing kind-specific selection | Existing selected-index validation |

The request route should authenticate, load the request, derive whether before media exists, derive the default view mode from the kind, and pass that context to the template. The template renders no additional before-after structure for no-before requests. The script activates mode switching and blink behavior only when the before-after controls are present.

---

## Implementation Units

- U1. **Prepare request-page before media context**

**Goal:** Pass explicit before media URL/type/default-view context into `request.html` while preserving existing request-row and verdict behavior.

**Requirements:** R1, R3, R8, R9, R10, R11, R12

**Dependencies:** Landed before storage and kind alias from dependency cards

**Files:**
- Modify: `gallery/server.py`
- Test: `tests/test_before_after.py`

**Approach:**
- Extend the `/r/{req_id}` template context with a small before-media object only when the request row has `before_media_path`.
- Build the before media URL through the same media URL helper/path convention used elsewhere in `server.py`.
- Derive a default view mode of toggle for `kind == "before-after"` and side-by-side for all other kinds that have before media.
- Keep no-before context absent or falsey so existing template branches can preserve current markup.
- Confirm the request creation validation alias is already present. If it is missing in the execution worktree, add the minimal alias within `server.py`/`db.py` scope and report that divergence in SURPRISES.

**Execution note:** Start with focused route/template-context tests that create requests through the real multipart API and inspect rendered HTML.

**Patterns to follow:**
- `gallery/server.py` `web_request_detail` context assembly.
- `gallery/server.py` `_media_url` for same-origin media paths.
- Existing `tests/test_api.py` before upload and web request-page tests.

**Test scenarios:**
- Happy path: a request created with `before` renders a before media URL for `/media/<req_id>/__before.png`.
- Happy path: a `before-after` request renders an initial/default toggle view marker.
- Happy path: a `pick-one` request with before media renders an initial/default side-by-side marker.
- Edge case: a request without before media does not render before-media data attributes, view-switcher markup, or toggle-only markup.
- Integration: a request with before media still returns the same API variant indices `[1, 2, ...]` from `GET /api/requests/{req_id}`.

**Verification:**
- The route context exposes enough data for template/JS work without changing request creation, storage, or verdict contracts.

---

- U2. **Render side-by-side before/candidate markup and styles**

**Goal:** Add the visible BEFORE block, view switcher shell, and side-by-side layout while ensuring before media is not selectable.

**Requirements:** R1, R2, R3, R4, R5, R7, R9, R10, R11, R12

**Dependencies:** U1

**Files:**
- Modify: `gallery/templates/request.html`
- Modify: `gallery/static/style.css`
- Test: `tests/test_before_after.py`

**Approach:**
- When before media exists, render a compact view switcher above the comparison area with buttons for side-by-side and toggle.
- Render a labeled BEFORE block before the candidate variants in side-by-side mode.
- Keep candidate variants in the existing `.variant` structure and keep the before block outside `.variant` and without `data-idx`.
- Use existing media element conventions for image/video handling, with the before block using the request's before media type.
- Add styles that fit the current dark/light compact Gallery UI, maintain roughly 44px tap targets for switcher controls, and provide visible focus states.
- Avoid changing the no-before markup path except for harmless surrounding branches that do not emit markup.

**Execution note:** Keep this unit template/style focused; do not alter JS selection semantics beyond what is necessary for focusable controls.

**Patterns to follow:**
- `gallery/templates/request.html` variant grid/media markup.
- `gallery/static/style.css` `.variant-grid`, `.variant`, `.btn`, `.tag`, and responsive media patterns.

**Test scenarios:**
- Happy path: before requests render a visible `BEFORE` label and before media element before candidate markup in side-by-side mode.
- Happy path: the view switcher includes side-by-side and toggle controls with accessible button semantics.
- Edge case: the BEFORE block has no `data-idx`, no variant number, and is not counted by markup selectors used for selectable variants.
- Edge case: candidate variant cards keep their existing `data-idx="1"` through `data-idx="N"` values.
- Edge case: no-before request markup still includes the existing variant grid and does not include before-specific classes or labels.

**Verification:**
- A before request clearly separates the baseline from candidates, and no-before requests remain visually and structurally compatible with the existing page.

---

- U3. **Add toggle blink interaction in vanilla JS**

**Goal:** Implement the in-place blink comparison and mode switching without disturbing existing pick-one, pick-many, rank, approve, and comment behavior.

**Requirements:** R4, R6, R7, R8, R9, R10, R11, R12

**Dependencies:** U1, U2

**Files:**
- Modify: `gallery/static/app.js`
- Modify: `gallery/static/style.css`
- Modify: `gallery/templates/request.html`
- Test: `tests/test_before_after.py`

**Approach:**
- Detect before-after controls from request-page markup; if absent, keep the current script path.
- Wire the view switcher buttons to update the active mode and relevant `aria-pressed`/hidden state.
- In toggle mode, maintain the current selected candidate through the existing pick-one selection model.
- When the selected candidate is tapped again, or when it has focus and Space is pressed, briefly swap the comparison frame between before media and candidate media.
- Ensure Space does not submit the page or scroll unexpectedly when it is used for the comparison action.
- Leave Decide button behavior and payload construction unchanged so selected indices stay 1..N.
- Keep hidden toggle elements out of the accessibility tree when inactive.

**Execution note:** Prefer small DOM helpers around existing `variants`/`order` state instead of introducing a second selection model.

**Patterns to follow:**
- `gallery/static/app.js` existing no-build IIFE structure and `toggleVariant`/`renderSelection` flow.
- Existing button and focus styling in `gallery/static/style.css`.

**Test scenarios:**
- Happy path: generated markup and script expose the hooks needed for selecting a candidate and blinking against before media.
- Happy path: `before-after` remains in the pick-one kind map and only one selected candidate can be submitted.
- Edge case: Space behavior is attached only to relevant candidate/toggle controls and not to the before block.
- Edge case: no-before pages do not emit the before-after hooks that would activate mode switching.
- Accessibility: switcher buttons and candidate cards in toggle mode have focusable controls or keyboard handlers that can be asserted from markup.

**Verification:**
- The JS is additive for before requests and the existing request decision flow remains unchanged for all non-before pages.

---

- U4. **Add focused before/after request tests and run verification**

**Goal:** Cover the card acceptance criteria with `TestClient` and template assertions while reusing existing API coverage where appropriate.

**Requirements:** R1 through R12

**Dependencies:** U1, U2, U3

**Files:**
- Create: `tests/test_before_after.py`
- Modify: existing tests only if needed to keep duplicate coverage small

**Approach:**
- Add a dedicated test file for before/after view behavior rather than overloading stream or general API tests.
- Use real multipart request creation with a `before` upload and candidate uploads so the tests exercise request creation, media storage, route context, template rendering, and verdict submission together.
- Assert key markup rather than full HTML snapshots: BEFORE block, view switcher, default mode, selectable variant count/indices, toggle hooks, and absence of before-specific markup for no-before requests.
- Assert verdict submission through the web decide route or API route still accepts selected variant `1` and rejects a non-variant index.
- Include a snapshot-ish no-before assertion using stable key strings from the current page: request detail container, variant grid, first variant `data-idx`, Decide panel, and absence of view-switcher/BEFORE/toggle markup.

**Execution note:** Run the board-specific full pytest command with the uv cache override after focused tests pass.

**Patterns to follow:**
- `tests/test_api.py` helper style for `auth_headers`, `tiny_png_bytes`, and multipart request creation.
- `tests/test_web_streams.py` markup assertion style for server-rendered pages.

**Test scenarios:**
- Happy path: before request page contains a BEFORE block, before media URL, view switcher, side-by-side control, toggle control, and toggle comparison markup.
- Happy path: before request page exposes selectable variants exactly for indices 1..N and does not expose the before media as a selectable variant.
- Happy path: web verdict submission for a before request with `selected: [1]` succeeds and the request becomes decided.
- Error path: verdict submission with `selected: [0]` or another non-variant index is rejected.
- Happy path: `kind="before-after"` request creation succeeds and its request page defaults to toggle mode.
- Happy path: `kind="pick-one"` with before media defaults to side-by-side mode.
- Edge case: request without before media lacks BEFORE/view-switcher/toggle markup and retains existing variant grid and decision panel key markup.

**Verification:**
- Focused tests cover every acceptance criterion, and the full suite remains green with the required uv cache override.

---

## System-Wide Impact

- **Interaction graph:** `/api/requests` creates request and media rows; `/r/{req_id}` reads those rows and serves a Jinja page; `app.js` manages client-side selection; `/r/{req_id}/decide` and `/api/requests/{req_id}/verdict` record the verdict through shared validation.
- **Error propagation:** Missing or invalid web auth stays 401, missing request stays 404, missing media remains handled by `/media`, and invalid selected indices remain 400 from existing verdict validation.
- **State lifecycle risks:** This feature is read-only until the existing verdict submit action. It must not create, delete, renumber, or mutate variants while rendering comparison UI.
- **API surface parity:** Existing JSON request, verdict, stream, CLI, and media contracts should remain unchanged. The only user-visible addition is request-page UI for requests that already have before media.
- **Integration coverage:** Tests should exercise real request creation, template rendering, static JS content, and verdict submission rather than isolated helper functions only.
- **Unchanged invariants:** Before media is out-of-band; variants are 1-based; latest-wins verdicts still apply; no-before request pages stay on the current behavior path.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| The existing `before-after` alias may be present in this worktree but absent after dependency merge ordering changes. | Verify at implementation start; add only the minimal alias fallback within the scoped files if needed, and report the divergence in SURPRISES. |
| Template changes can accidentally make the before image selectable by existing `.variant` JS. | Keep the before block outside `.variant`, assert no `data-idx`, and test selectable variant counts/indices. |
| Toggle mode can fight existing pick-one tap behavior. | Reuse the existing selection state, make first tap select and second tap/Space blink, and keep Decide payload construction unchanged. |
| Keyboard support can regress mobile tap ergonomics or focus visibility. | Use real buttons for switcher controls, maintain 44px-ish tap targets, and add explicit focus-visible styling for new controls. |
| No-before request pages can change incidentally while adding branches. | Add snapshot-ish key markup assertions for no-before pages and keep branches falsey when no before media exists. |

---

## Documentation / Operational Notes

- No README or CLI documentation update is required in this card unless implementation discovers a user-facing behavior mismatch not covered by existing docs.
- The implementation handoff should mention whether `before-after` alias/storage was already present or had to be added in this branch.
- Verification should use the board-specific command with the uv cache override from the worker context.

---

## Sources & References

- **Origin:** Trello card `jAQ8bS6C`
- **Spec:** `docs/portal-spec.md`
- **Dependency plan:** `docs/plans/2026-07-08-002-feat-streams-posts-http-api-plan.md`
- **Related stream web plan:** `docs/plans/2026-07-08-003-feat-stream-web-pages-plan.md`
- Related code: `gallery/server.py`
- Related code: `gallery/db.py`
- Related template: `gallery/templates/request.html`
- Related styles/scripts: `gallery/static/style.css`, `gallery/static/app.js`
- Related tests: `tests/test_api.py`, `tests/test_web_streams.py`, `tests/conftest.py`
