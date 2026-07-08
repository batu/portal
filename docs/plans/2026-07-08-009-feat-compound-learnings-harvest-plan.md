---
title: "feat: Harvest compound learnings and backlog"
type: feat
status: active
date: 2026-07-08
origin: "trello-card:Nj29W8GT"
trello: "https://trello.com/c/Nj29W8GT"
spec: docs/portal-spec.md
---

# feat: Harvest compound learnings and backlog

## Summary

Create a source-backed knowledge harvest for the Gallery/Portal board run: bootstrap `docs/solutions/` with indexed durable lessons, then capture follow-up improvement ideas as unscheduled markdown card drafts under `todos/cards/`. The implementation is docs-only and must prove it did not touch product code.

---

## Problem Frame

The Portal phase work produced recurring operational and product lessons, but the most useful knowledge is currently split across Trello handoffs/comments, board lessons, evidence bundles, and the spec Review log. Without a durable repo-local catalog and a separate improvement backlog, future workers will rediscover the same sandbox, evidence, media-rendering, and twf-process failures.

---

## Assumptions

*This plan was authored in pipeline mode without synchronous user confirmation. The items below are unvalidated planning bets that should be reviewed before implementation proceeds.*

- This planned-stage worker should only create the plan artifact. The next worker owns the actual source harvest and docs/backlog edits.
- The card description is the origin input; there is no upstream brainstorm document under `docs/brainstorms/`.
- `docs/solutions/` and `todos/cards/` are new in this repo, so the implementation should define the smallest local formats needed instead of importing a broad external taxonomy.
- The candidate lessons named on the card are not authoritative. Each entry must be verified against Trello comments/handoffs, `twf lesson list` or `.twf/lessons.jsonl`, committed evidence, or `docs/portal-spec.md` before it is written.
- The current worktree has no local `.twf/` directory, but `twf lesson list` resolves the board-local lessons and the main checkout has a `.twf/lessons.jsonl` store. The implementation should prefer repo-relative references in committed docs and cite card short IDs rather than absolute local paths.
- Trello REST credentials are required to satisfy the "all card comments/handoffs" source requirement. If `TRELLO_API_KEY` or `TRELLO_TOKEN` is unavailable, the implementation should stop and report the blocker rather than producing a final harvest from local sources only.
- Backlog idea files are intentionally not Trello cards. The human conductor decides what, if anything, is scheduled later.

---

## Requirements

- R1. Harvest candidate lessons from all required source classes: Trello comments and handoffs on this board via Trello REST, structured `twf handoff` fields in those comments (`Done`, `Verified-how`, `Remaining`, `Surprises`, `Plan-friction`), `twf lesson list` or `.twf/lessons.jsonl`, `docs/evidence/*`, and the `docs/portal-spec.md` Review log.
- R2. Treat Trello board comments/handoffs as required. If Trello REST credentials or access are unavailable, stop and report the blocker rather than producing final docs; for non-Trello source gaps, record the gap and omit unsupported lessons.
- R3. Create `docs/solutions/INDEX.md` plus 4-8 dated lesson entries under `docs/solutions/`.
- R4. Each solution entry must include these sections: Problem, Root cause, Rule, How to verify, and Sources. Every entry must cite at least one concrete source by card short ID, evidence path, `twf lesson` source card, or spec section/log entry.
- R5. Candidate solution topics may include iframe sandbox plus media disposition blank-rendering, TestClient versus real-browser coverage gaps, plan-stage untracked-file checks, sandbox uv cache redirection, launchd bootstrap over SSH retry behavior, and visible `proj-<slug>` naming decisions, but only topics with verified sources may become entries.
- R6. Avoid raw secrets, tokens, private URLs, and unnecessary local absolute paths in durable docs. Summarize sensitive Trello or evidence material when needed.
- R7. Create `todos/cards/README.md` explaining that files in `todos/cards/` are not on the Trello board and must not be implemented directly.
- R8. Create 3-8 idea card markdown files under `todos/cards/`, each following the agency card template with a title prefix `idea:`, `fix:`, or `feat:`, and sections for Problem, Decided approach, Scope fence, Acceptance criteria, and Verification. When a source does not record a decided implementation shape, the `Decided approach` section should explicitly say it is a candidate approach for conductor review.
- R9. Harvest backlog ideas from plan-friction scores and SURPRISES fields in structured Trello handoff comments, plus integration-review proposed-card items, then dedupe against live/planned board cards before writing files.
- R10. Do not post the idea cards to Trello, create pull requests, merge branches, or do conductor duties.
- R11. Keep the implementation diff inside `docs/solutions/**`, `todos/cards/**`, and at most one README pointer line. No `gallery/**`, `tests/**`, `docs/evidence/**`, `docs/portal-spec.md`, `.twf/**`, or generated artifact changes.
- R12. Verify the final implementation with the board-required full suite command using `UV_CACHE_DIR=/private/tmp/uv-cache`, plus docs/scope checks that prove only allowed paths changed.
- R13. If source verification and dedupe leave fewer than 4 solution entries or fewer than 3 idea files, do not pad with weak items. Stop and report the count shortfall as a blocker or SURPRISES item.

---

## Card Acceptance Criteria Trace

| Card acceptance criterion | Requirements | Units | Verification anchor |
|---|---|---|---|
| `INDEX.md` lists every entry | R3, R4 | U1, U2 | Index review confirms all created entry files are linked |
| 4-8 entries with citations | R1-R6 | U1, U2 | Entry checklist confirms Problem, Root cause, Rule, How to verify, Sources |
| 3-8 idea card files plus README | R7-R10 | U3 | `todos/cards/README.md` and file count/template review |
| No `gallery/` diffs | R11, R12 | U4 | Changed-file scope check before handoff |
| Full suite stays green | R12 | U4 | `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q` |

---

## Scope Boundaries

- No product code, tests, templates, static assets, migrations, deployment scripts, or CLI changes.
- No edits to `docs/evidence/**` or `docs/portal-spec.md`; those are sources, not outputs for this card.
- No Trello card creation or scheduling from the harvested backlog.
- No pull requests, merges, default-branch work, or conductor duties.
- No broad README rewrite. If a README pointer is useful, it is one line maximum.
- No uncited "lessons learned" prose. Unverified candidate lessons are omitted or recorded as implementation surprises.
- No copying sensitive Trello/evidence details verbatim when a source citation plus summary is enough.

### Deferred to Follow-Up Work

- Implementing any `todos/cards/` draft on the board.
- Promoting solution rules into automated `twf lesson promote` checks.
- Building a reusable Trello-harvest script or Portal/Trello watcher beyond the docs needed here. A planned board card already exists for Portal Trello watcher work (`08KM8i8Q`).
- Phase 2+3 E2E proof and deploy documentation. A planned board card already exists for that release proof (`hVtTtwRa`).

---

## Context & Research

### Relevant Code and Patterns

- Existing plan files live in `docs/plans/YYYY-MM-DD-NNN-<type>-<slug>-plan.md` and Trello-sourced plans use frontmatter such as `origin: "trello-card:<shortid>"`, `trello: "https://trello.com/c/<shortid>"`, and `spec: docs/portal-spec.md`.
- `README.md` describes Gallery/Portal as a FastAPI plus SQLite service with `portal` and `gallery` CLI aliases. The Development section uses `uv run pytest`, and board lessons require the `/private/tmp/uv-cache` override.
- Evidence bundles under `docs/evidence/2026-07-08-stream-web-pages/` and `docs/evidence/2026-07-08-portal-phase1/` use frontmatter, Verdict, What Changed, command/artifact tables, gaps, and next action sections.
- `docs/portal-spec.md` has a Review log beginning at the Review log section with accepted implementation decisions and proposed follow-up cards.
- `twf lesson list` currently returns two board lessons: source card `8OEiwp9u` for uv cache redirection and source card `jAQ8bS6C` for plan-stage `git status --porcelain` verification.
- `twf sitrep --json` shows two planned cards that should be treated as duplicate-avoidance anchors for backlog ideas: `08KM8i8Q` for Portal Trello watcher work and `hVtTtwRa` for phases 2+3 proof.

### Institutional Learnings

- No formal `docs/solutions/` catalog exists in this repo yet.
- Prior planning notes repeatedly mention the absence of `docs/solutions/`, so this card should bootstrap the catalog rather than assume a pre-existing schema.
- The strongest local durable sources are the committed evidence bundles, `twf lesson list`, and `docs/portal-spec.md` Review log. Trello comments/handoffs remain required for complete board coverage.

### External References

- External web research is not needed. This task is a repo-local docs and backlog harvest over committed artifacts plus Trello board data.

---

## Key Technical Decisions

- Use a minimal solution-entry schema: title/frontmatter optional, then `Problem`, `Root cause`, `Rule`, `How to verify`, and `Sources`. This matches the card exactly and avoids over-designing the first catalog pass.
- Put dated solution entries directly under `docs/solutions/` rather than introducing subdirectories on the first pass. The `INDEX.md` can group or tag entries if needed.
- Treat `docs/solutions/INDEX.md` as both the table of contents and the source-inventory summary, so future workers can see which source classes were checked and which were unavailable.
- Use `todos/cards/` for unscheduled idea drafts only. File names should be stable and readable, for example `001-fix-stream-owned-decisions.md`, while the first heading carries the required `fix:`/`feat:`/`idea:` prefix.
- Dedupe backlog ideas against a fresh read of all non-archived board cards before writing files. Known planned cards `08KM8i8Q` and `hVtTtwRa` are examples of duplicates to avoid, not the complete duplicate list.
- Prefer source-backed specificity over filling the maximum counts. Four strong solution entries are better than eight weak or uncited entries; three strong idea drafts are better than eight duplicates.

---

## Open Questions

### Resolved During Planning

- Should this stage implement the docs and backlog? No. The `planned` checklist requires a plan artifact; implementation belongs to the next worker.
- Is there a local `docs/solutions/` convention to follow? No. The plan defines a minimal repo-local convention.
- Should the card post idea cards to Trello? No. The card explicitly says not to post them.
- Should the implementation run pytest even though the diff is docs-only? Yes. The card explicitly requires the full suite command to prove no product code was disturbed.

### Deferred to Implementation

- Exact list of Trello cards/comments/handoffs on the board and which of them produce valid solution citations.
- Whether the launchd bootstrap-over-SSH candidate has enough source support on this board to become a solution entry.
- Exact final 4-8 solution entry topics after source verification and dedupe, or the blocker if fewer than 4 can be cited.
- Exact final 3-8 backlog idea files after deduping against current and planned Trello cards, or the blocker if fewer than 3 remain.
- Where to place the optional one-line README pointer, if any. If it would exceed one line or feel noisy, skip it.

---

## Output Structure

The implementation should create this shape, with counts determined by verified sources:

```text
docs/solutions/
  INDEX.md
  2026-07-08-<lesson-slug>.md
  ...
todos/cards/
  README.md
  001-<prefix>-<idea-slug>.md
  ...
README.md  # optional one-line pointer only
```

---

## Implementation Units

- U1. **Harvest and classify source material**

**Goal:** Build the source inventory and candidate list before writing durable lessons or idea cards.

**Requirements:** R1, R2, R5, R6, R9, R13

**Dependencies:** None

**Files:**
- Create: `docs/solutions/INDEX.md`
- Test: none

**Approach:**
- Use Trello REST with `TRELLO_API_KEY` and `TRELLO_TOKEN` to resolve `idBoard` from card `Nj29W8GT`, then fetch and page board `commentCard` actions. Capture source card short IDs and comment/action identifiers for citations.
- Classify structured handoff comments by the canonical field labels `Done`, `Verified-how`, `Remaining`, `Surprises`, and `Plan-friction`; record counts checked and useful items found in `docs/solutions/INDEX.md`.
- Use `twf lesson list` and, if available, the board-local `.twf/lessons.jsonl` to identify board lessons and their source card IDs.
- Read committed evidence under `docs/evidence/2026-07-08-stream-web-pages/` and `docs/evidence/2026-07-08-portal-phase1/` for rendered-media, browser/runtime, TestClient, CLI-help, and full-suite proof.
- Read the `docs/portal-spec.md` Review log for accepted decisions and proposed follow-up items.
- Use `twf sitrep --json` or an equivalent board read to dedupe backlog ideas against planned cards.
- Record the source classes checked in `docs/solutions/INDEX.md`, including any unavailable required source class.

**Execution note:** Do source harvesting before writing entries. If Trello REST credentials or access are missing, stop or hand off the blocker rather than completing a partial harvest silently.

**Patterns to follow:**
- `docs/evidence/2026-07-08-portal-phase1/evidence.md` for concise evidence-source summaries.
- `docs/portal-spec.md` Review log for durable decision wording.
- Existing Trello plan frontmatter style in `docs/plans/2026-07-08-008-fix-integration-review-spec-drift-plan.md`.

**Test scenarios:**
- Test expectation: none - source harvest and classification are docs-only, but the next units should be reviewable against this inventory.

**Verification:**
- `docs/solutions/INDEX.md` identifies each source class checked and does not claim complete Trello coverage unless Trello REST succeeded.
- Candidate lessons and backlog ideas are traceable to source IDs or paths before any entry files are created.

---

- U2. **Write cited solution entries**

**Goal:** Turn verified recurring lessons into durable `docs/solutions/` entries and link every entry from the index.

**Requirements:** R2, R3, R4, R5, R6, R13

**Dependencies:** U1

**Files:**
- Modify: `docs/solutions/INDEX.md`
- Create: `docs/solutions/2026-07-08-<lesson-slug>.md`
- Test: none

**Approach:**
- Write 4-8 entries only from verified sources. Use the card's candidate list as a search queue, not a required output list.
- If fewer than 4 verified solution topics remain after source review, stop and report the blocker instead of padding the catalog.
- For each entry, include `Problem`, `Root cause`, `Rule`, `How to verify`, and `Sources`.
- Use source citations such as `card 8OEiwp9u`, `card jAQ8bS6C`, `docs/evidence/2026-07-08-stream-web-pages/evidence.md`, `docs/evidence/2026-07-08-portal-phase1/evidence.md`, or `docs/portal-spec.md Review log`.
- Keep rules actionable and general enough to apply beyond a single card, but keep verification concrete enough for future workers.
- Update `docs/solutions/INDEX.md` so every created entry is listed exactly once with a short rule summary and source pointer.

**Patterns to follow:**
- Evidence summaries in `docs/evidence/2026-07-08-stream-web-pages/evidence.md` for the iframe/media proof.
- `twf lesson list` output for board-level process lessons.
- `docs/portal-spec.md` Review log for stream naming and follow-up decisions.

**Test scenarios:**
- Docs review: every entry has all five required sections.
- Docs review: every entry has at least one citation to a concrete source.
- Edge case: a candidate lesson with no source support is not written as a solution entry.
- Security: raw tokens, private URLs, and unnecessary absolute paths are absent from committed docs.

**Verification:**
- Entry count is between 4 and 8.
- `docs/solutions/INDEX.md` links every entry and no missing entry files remain unlisted.
- Each entry can be traced back to the source inventory from U1.

---

- U3. **Draft unscheduled improvement cards**

**Goal:** Convert recurring friction and integration-review follow-ups into local markdown card drafts without scheduling them on Trello.

**Requirements:** R7, R8, R9, R10, R11, R13

**Dependencies:** U1

**Files:**
- Create: `todos/cards/README.md`
- Create: `todos/cards/001-<prefix>-<idea-slug>.md`
- Test: none

**Approach:**
- Create `todos/cards/README.md` first, stating that these files are not on the board, are not approved for direct implementation, and need conductor scheduling.
- Harvest 3-8 idea files from verified Plan-friction and SURPRISES fields in Trello handoff comments, plus `docs/portal-spec.md` proposed follow-up sources.
- Dedupe against a fresh read of all non-archived board cards before writing files. Avoid duplicating `08KM8i8Q` Portal Trello watcher and `hVtTtwRa` phases 2+3 proof, but do not treat those two IDs as the whole duplicate set.
- Use the required template in each file: title prefix `idea:`, `fix:`, or `feat:`, then Problem, Decided approach, Scope fence, Acceptance criteria, and Verification.
- In the `Decided approach` section, distinguish source-decided approach from candidate approach. If the source only proves friction, write that the approach is a candidate for conductor review.
- Include source citations or a short "Source" line in each idea card so the conductor can decide whether to schedule it.
- If fewer than 3 non-duplicate, source-backed ideas remain, stop and report the blocker instead of creating filler.

**Patterns to follow:**
- The "proposed follow-up card" entries in `docs/portal-spec.md` Review log.
- Card language in existing Trello-sourced plans: explicit scope fence, acceptance criteria, and verification.

**Test scenarios:**
- Docs review: `todos/cards/README.md` clearly says the drafts are not scheduled Trello cards.
- Docs review: every idea file has the required template sections.
- Edge case: candidate backlog ideas already represented by planned board cards are omitted or explicitly noted as duplicates rather than copied.

**Verification:**
- Idea file count is between 3 and 8.
- No Trello cards were created.
- Every idea file has enough acceptance and verification detail for a conductor to schedule later without re-mining the source.

---

- U4. **Apply optional README pointer and verify scope**

**Goal:** Add only the allowed README pointer if useful, then prove the implementation is docs-only and the full suite stays green.

**Requirements:** R10, R11, R12, R13

**Dependencies:** U2, U3

**Files:**
- Modify: `README.md` (optional, one-line pointer only)
- Test: none

**Approach:**
- Add at most one README line pointing future readers to `docs/solutions/` and/or `todos/cards/`, only if it improves discoverability.
- If the README pointer would require explanatory prose longer than one line, skip it and leave discoverability to the new index/README files.
- Run docs checks for changed-file scope, markdown whitespace, entry/index consistency, idea-card count/template consistency, and README one-line limit. Concrete checks should include `git diff --check`, `git status --porcelain --untracked-files=all`, an allowlist check for changed paths, count checks for solution entries and idea files, required-heading checks, index-link checks, and a README added-line count if README changes.
- Run the board-required full pytest command with the uv cache override.
- If pytest fails with this docs-only diff, capture the failure as a blocker or SURPRISES item and do not edit product code or tests.

**Patterns to follow:**
- README's existing concise section style.
- Board lessons requiring `UV_CACHE_DIR=/private/tmp/uv-cache`.

**Test scenarios:**
- Scope: changed files are limited to `docs/solutions/**`, `todos/cards/**`, and optionally `README.md`.
- Scope: no `gallery/**`, `tests/**`, `docs/evidence/**`, `docs/portal-spec.md`, or `.twf/**` changes exist.
- Scope: `git status --porcelain --untracked-files=all` has no untracked/generated files outside the allowed paths before commit and is empty before handoff.
- Docs review: README diff is zero or one added pointer line.
- Regression: the full pytest suite passes with the board-required uv cache override.

**Verification:**
- Final diff stays inside the card scope fence.
- `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q` passes.
- `git status --porcelain --untracked-files=all` is checked before handoff so untracked docs are not missed.

---

## System-Wide Impact

- **Interaction graph:** This is documentation-only. No FastAPI routes, SQLite helpers, CLI commands, templates, static assets, deployment scripts, or tests should execute different behavior because of this card.
- **Error propagation:** Missing Trello credentials or inaccessible comments are blockers or SURPRISES, not silent partial success.
- **State lifecycle risks:** The only persistent state is committed markdown. No database, media, config, or Trello state should be mutated.
- **API surface parity:** No API, web, or CLI surface changes.
- **Integration coverage:** The card still requires the full pytest suite to prove the product tree was not disturbed.
- **Unchanged invariants:** Portal remains push-only; this card does not make the service crawl evidence folders or publish backlog drafts to Trello.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Trello REST credentials are missing or fail | Stop or report the blocker; do not claim complete board-comment coverage from local files alone |
| Candidate lessons become invented lore | Require concrete citations in every entry and omit unverified candidates |
| Backlog drafts duplicate live/planned cards | Check live board state before writing and avoid known planned cards `08KM8i8Q` and `hVtTtwRa` |
| Trello comments or evidence contain sensitive tokens/private details | Summarize and cite rather than copying raw secrets, tokens, or private URLs |
| README edit expands beyond the scope fence | Keep it to one pointer line or skip it entirely |
| Docs-only change tempts product cleanup | Keep product drift in `todos/cards/` or SURPRISES; no `gallery/**` edits |
| Source-backed minimum counts cannot be met | Stop and report the shortfall instead of padding weak solution entries or idea drafts |
| Full pytest fails despite a docs-only diff | Capture the failure as a blocker/SURPRISES item; do not patch product code or tests on this card |

---

## Documentation / Operational Notes

- The implementation handoff should list the exact solution entry files and idea card files created.
- The handoff should name any source classes that were inaccessible or any candidate lessons intentionally omitted for lack of source support.
- If the full pytest suite still emits the known Starlette/httpx warning, report it as pre-existing rather than as a new failure.

---

## Sources & References

- **Origin card:** `Nj29W8GT` - `https://trello.com/c/Nj29W8GT`
- **Board lessons:** `twf lesson list`; source cards `8OEiwp9u` and `jAQ8bS6C`
- **Spec:** `docs/portal-spec.md` Review log
- **Evidence:** `docs/evidence/2026-07-08-stream-web-pages/evidence.md`
- **Evidence:** `docs/evidence/2026-07-08-portal-phase1/evidence.md`
- **Prior plan style:** `docs/plans/2026-07-08-008-fix-integration-review-spec-drift-plan.md`
- **Current board dedupe anchors:** `twf sitrep --json` planned cards `08KM8i8Q` and `hVtTtwRa`
