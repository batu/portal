# Portal — spec (v1.1)

Date: 2026-07-08
Status: reviewed draft (scope + feasibility reviews applied)
Owner: Batu
Scope: evolves the existing `gallery` service into the **Portal** — the single
web/phone surface where agents (any runtime: Claude Code, pi, codex, local
models) publish results and receive human feedback.

## 1. Purpose and principles

Today: fabrikav2 produces rich evidence (`panel.json` + `grid.html` in dated
run dirs) with no delivery; gallery delivers decision requests but sees nothing
else; twf state is terminal-only; the inbound phone path (ccbot/cc-gateway) is
dead. The Portal consolidates these into one protocol.

Principles, in priority order:

1. **Model-agnostic.** The agent side of the protocol is plain HTTP + a thin
   CLI shim. Nothing assumes Claude Code. A local model loop implements the
   whole contract with two HTTP calls.
2. **Push-only producers.** The Portal never crawls repos or evidence folders.
   Anything visible was explicitly `POST`ed to it (same seam gallery has now).
3. **Permanent links.** A stream URL never changes and never dies. Session
   streams become archives when closed; nothing is deleted.
4. **No full chat.** Human↔agent interaction is exactly two patterns:
   agent-asks/human-answers (blocking) and human-steers/agent-pulls
   (turn-boundary pickup). No streaming, no presence, no live-conversation UX.
5. **Tailnet now, public later.** v1 stays Tailscale-only, but streams and
   auth are shaped so a Cloudflare tunnel + per-user tokens can be added
   without schema rework (see §9).

## 2. Concepts

- **Stream** — a named, permanent container of posts.
  - `kind: session` — opened at (or before) an agent session's start; the
    session's reports, decision requests, and messages accrue here. Closed
    explicitly (`portal stream close`, manual or via a session-end hook —
    never a TTL); a closed stream is a read-only archive.
  - `kind: pinned` — long-lived doc collections ("docs I like"). Same
    machinery, no implied end.
  - URL: `/s/<slug>`. Slug chosen at creation (`ftd-menu-redesign-0708`),
    unique, immutable.
- **Post** — one durable item in the stream timeline. Shipped v1.1 stores
  `report` and `decision` entries in `posts`; phase-2 `message` entries are
  stream-scoped queue records in `messages`, rendered on the stream page but
  not accepted through the post-envelope endpoint. Two post-envelope types:
  - `report` (one-way): a self-contained HTML file or media bundle. Rendered
    inline / linked from the stream page.
  - `decision` (two-way): today's gallery request — kinds `pick-one`,
    `pick-many`, `rank`, `approve`, `comment`, plus new **`before-after`**
    (§6). Carries variants, blocks on a verdict.
- **Message** (two-way, phase 2): text notes in either direction — the
  steering inbox and agent questions (§7). Messages are stream-scoped but stay
  in the `messages` queue table/API until a consumer needs full post-envelope
  unification.
- **Verdict** — unchanged from gallery: `{selected, ratings?, comment?}`,
  latest-wins revision, now attached to a decision post.

## 3. Envelope

Every report/decision post shares one envelope; type-specific payload nests under `body`.
Deliberately minimal in v1 — fields are added only when something consumes
them (per scope review: no `tags`, no typed author object yet).

```json
{
  "id": "p_8f3a2c",
  "stream": "ftd-menu-redesign-0708",
  "type": "report | decision",
  "title": "Menu tile spacing pass 3",
  "author": "claude-fable-5 @ fabrikav2",
  "created_at": "2026-07-08T14:12:03Z",
  "body": { ...type-specific... }
}
```

`author` is a free-text display string. A typed author model and per-user
identity arrive with coworker auth (phase 3), when something actually reads
them. `tags` likewise deferred until a filter/search consumer exists.

Messages use the smaller `{id, stream_id, direction, text, created_at,
consumed_at}` shape in §4 rather than this post envelope.

## 4. Data model and migration

SQLite. New tables (safe under `db.py`'s existing `CREATE TABLE IF NOT
EXISTS` pattern):

```
streams(id, slug UNIQUE, kind, title, created_at, closed_at NULL)
posts(id, stream_id, type, title, author, body_json, created_at)
messages(id, stream_id, direction 'to_agent'|'to_human', text,
         created_at, consumed_at NULL)
```

`messages` is created in the **phase-2 migration**, not phase 1 — no table
ships before its consumer. Messages are intentionally not dual-written into
`posts` in v1.1; the queue semantics for ask/pull are separate from report and
decision post rendering.

**Migration mechanism (new — required).** `db.py` today applies schema via
`executescript` of `CREATE TABLE IF NOT EXISTS` on every connect; that cannot
add columns to existing tables. Phase 1 adds a minimal migration step in
`connect()`: a `PRAGMA user_version`-gated list of idempotent migrations, each
a function that may `ALTER TABLE`. Version 1 adds to `requests`:
`stream_id` (nullable FK), `before_media_path` (nullable), `before_media_type`
(nullable). No framework — a numbered list of Python functions.

**Legacy compatibility (defined precisely).** For requests created through the
existing `POST /api/requests` / `gallery post` path:

- If `project` is set: the request lands in stream `proj-<project-slug>`
  (kind `session`), lazily created on first use. `project-slug` is the
  lowercased project with non-`[a-z0-9]` runs replaced by `-`, edge hyphens
  stripped, and `project` used if normalization is empty. The full route slug
  remains capped at 128 characters including the five-character `proj-` prefix;
  overlong normalized project slugs keep the leading stem plus `-` and the
  first 8 hex characters of `sha256(project-slug)`.
- If `project` is `None`: it lands in the lazily-created stream `inbox`.
- If a non-empty `stream` form field is supplied to `POST /api/requests`
  (CLI: `portal post --stream <slug>`): that slug takes precedence over the
  `project`-derived resolution above and becomes the request's authoritative
  `stream_id`. The slug is validated against the route slug contract (`400`
  on mismatch; empty/whitespace values mean "absent") and the stream is
  lazily created (kind `session`, title = slug) if missing. Closing that
  stream makes the request read-only (decide returns `409`).
- `create_request` writes the `requests`/`variants` rows **and** a `posts`
  row (type `decision`, `body_json` pointing at the request id) in the same
  transaction, so legacy requests appear in stream pages. Without the dual
  write, legacy requests would be invisible to the Portal view.

Report media and HTML land in the existing media dir scheme:
`media/<post_id>/…`, served at `/media/<post_id>/<file>` (the existing
`get_media` handler is generic over the leading path segment, verified).
Reports are stored self-contained (single HTML file + sibling assets); the
stream page iframes or links them.

## 5. API and CLI

Existing endpoints stay. New JSON API (bearer-token, agent-facing):

```
POST /api/streams                {slug, kind, title}
POST /api/streams/{slug}/close
GET  /api/streams/{slug}         stream + post index
POST /api/streams/{slug}/posts   multipart: envelope fields + files
GET  /api/streams/{slug}/posts/{id}
POST /api/streams/{slug}/messages           {direction, text}      (phase 2)
GET  /api/streams/{slug}/messages?since=&direction=&unconsumed=1   (phase 2)
POST /api/messages/{id}/consume                                    (phase 2)
```

Mutation status semantics in v1.1: missing/invalid bearer or web token returns
`401`; missing streams/posts/messages/requests return `404`; closed-stream
mutations return `409`. There is no shipped `403` state in the single-token v1
model; forbidden-vs-authenticated distinctions arrive with §9's future
per-stream auth.

**Browser twins (required, per feasibility review).** The stream page's own
JS cannot send a bearer header; gallery already solves this once with the
cookie-authed `POST /r/{req_id}/decide` twin of the verdict API. Every
endpoint invoked from the page follows the same pattern: cookie-authed
`POST /s/{slug}/note` (steering note box) and `POST /s/{slug}/answer`
(reply to an agent question) wrap the corresponding `/api/...` logic.

CLI (extends the current tool; command surface is the whole agent-side
protocol; binary is named `portal`, with `gallery` kept as an alias — see §13):

```
portal stream new <slug> [--kind session|pinned] [--title ...]
portal stream close <slug>
portal report  --stream <slug> --title ... <file.html> [assets...]
portal post    --stream <slug> ...            # decision flow + --before <img>; --stream sets the owning stream (created if missing)
portal wait    <request-id>                   # existing, unchanged
portal ask     --stream <slug> "question" [--timeout 1800]   # phase 2
portal pull    --stream <slug> [--timeout 0]                 # phase 2
```

`ask` = post a `message` (direction `to_human`), Telegram doorbell, then
**client-side interval polling** for a reply — same pattern as today's
`wait` (`cli.py` sleeps between plain GETs). Explicitly **not** a server-side
long poll: route handlers must never block on the module-level sqlite
lock, or they'd stall unrelated requests under FastAPI's sync thread pool.
`pull` = fetch-and-consume the oldest unconsumed `to_agent` message
(steering note); non-blocking by default so agent loops can check between
turns. These are ccbot's verbs re-homed onto the Portal; the filesystem
queue and cc-gateway are retired.

Agent-side message creation follows the same push convenience as reports:
`POST /api/streams/{slug}/messages` auto-creates a missing session stream.
Read paths (`GET .../messages`, `portal pull`) and browser twins require an
existing stream and return `404` for a missing slug.

## 6. Before/after decisions

Any decision request may carry one optional **before** image
(`--before <img>`). Stored **out-of-band on the request row**
(`before_media_path`/`before_media_type`), *not* as a `variants` row —
variants are 1-based throughout the codebase and the before image is never
selectable, so it must not occupy an index. UI on the request page offers two
views over the same data:

- **Side-by-side**: before pinned left/top, candidates in the normal grid —
  for taste calls between different designs.
- **Toggle (blink)**: tap/space flicks the selected candidate and the before
  image in place — makes small visual diffs pop.

No new request kind is strictly required, but `kind: before-after` is accepted
as an alias of `pick-one` that defaults the UI to toggle view.

## 7. Steering and questions (phase 2)

- **Human → agent (steering):** stream page gets a note box (cookie-authed
  twin route, §5). Notes queue as `to_agent` messages. Whatever loop is
  running polls `portal pull` (or the raw GET) at turn boundaries and folds
  notes in. No mid-turn delivery, ever; that is a documented non-goal.
- **Agent → human (questions):** `portal ask` posts the question, rings
  Telegram, polls for the answer. Human answers from the stream page (or
  anywhere the web UI loads — phone included). Timeout behavior mirrors
  ccbot's `ask` (default 1800 s, agent proceeds with a stated assumption on
  timeout).
- Claude Code convenience (optional, later): a Stop/turn hook that runs
  `portal pull` automatically. Not part of the protocol.

## 8. Notifications

Reuse `notify.py` (Telegram doorbell). Shipped v1.1 has a fixed policy:
decisions and `ask`/`to_human` messages ring by default; reports and
human-to-agent steering notes are silent. `config.json` holds Telegram
credentials only for now; configurable per-type/per-stream policy is deferred
until there is a real settings consumer. Message text links straight to the
stream URL.

## 9. Access (designed-for, not built in v1)

v1: Tailscale-only, single bearer token, exactly as today. Auth failures are
authentication failures (`401`), not authorization failures (`403`), because
there is no user or per-stream permission state yet. The design keeps public
exposure cheap later: streams are the sharing unit (a future
`stream_tokens` table grants per-stream read or read+verdict access), and all
media auth already flows through one place (`_maybe_set_cookie` / bearer
check). Public exposure would be Cloudflare Tunnel or Tailscale Funnel in
front of the same service — no schema change anticipated.

## 10. Producers to wire up (after core lands)

- **fabrikav2 evidence**: at promotion time, also `portal report --stream
  <session> docs/evidence/<run>/grid.html`. Evidence folders remain the source
  of truth; the Portal is the delivery copy.
- **twf**: `twf handoff` and `twf sitrep` gain an optional `--portal <stream>`
  that posts the same text as a `report`. Backlog card 11 (Telegram event
  notifications) is subsumed by §8.
- **Future (not planned yet):** a read-only fleet/HUD page summarizing live
  sessions could sit inside the Portal, fed by the agency fleet-bus JSONL —
  same push-only seam. Noted here only so naming/URL choices don't preclude
  it.

## 11. Phases

1. **Portal core (PC speedup):** migration step + streams + `report` posts +
   stream page + `--before` with side-by-side/toggle views + legacy
   compatibility dual-write. Ship, then dogfood on real game-design feedback.
2. **Inbox:** `messages` table (phase-2 migration), `ask`/`pull`, stream note
   box + answer twin routes, Telegram on `ask`. Retire ccbot's filesystem
   queue.
3. **Coworker Trello→TWF:** watcher spawns `twf run-card` on cards entering a
   trigger column, posts results back to the card and to a per-card stream.
   Forces the first real auth decision (coworker on tailnet vs. tunnel).

## 12. Deferred / explicitly not now

- **Visual annotation** (pins/boxes on images): deferred pending dogfooding of
  phase 1. If "where"-descriptions prove to be the typing bottleneck, build the
  minimal version only: tap → pin → note, server auto-crops around the pin and
  the verdict carries crop image + note (agents consume crops well;
  coordinate→code mapping is fragile). Boxes/freehand only if pins fail.
- **design-sheets overlap**: parked until dogfooded; pins-with-autocrop keeps
  the door open either way.
- **Full chat / presence / mid-turn injection**: non-goals, permanently.
- **Portal crawling evidence folders**: non-goal; producers push.

## 13. Resolved questions

1. **Stream auto-creation — decided: automatic.** The agent creates the
   stream at session start and invents the slug (Batu: "the names aren't that
   important... I might forget it"). Mechanically: `portal report`/`portal
   post` with `--stream <slug>` and `portal ask --stream <slug>`
   **auto-create the stream if it doesn't exist** (kind `session`), so no
   separate `stream new` call is required in the common push path; `portal
   stream new` remains for explicit/pinned streams. Browser note/answer twins
   and read/pull paths do not auto-create.
2. **Report size limits — decided:** 200 MB/post soft cap; warn, never
   reject.
3. ~~Naming~~ **Decided 2026-07-08: the name is `portal`** (two-way
   connotation). `hud` was considered and reserved for a possible future
   read-only fleet page *inside* the Portal; `bridge`/`console` rejected.
   The old `gallery` binary name stays as a compatibility alias until
   producers are migrated.

## Review log

- 2026-07-08 scope review: trimmed `tags`/typed-author from envelope; legacy
  project→stream mapping defined; `messages` migration moved to phase 2;
  stream close write path added. Rejected: dropping `pinned` streams (explicit
  user goal), demoting model-agnostic principle (explicit user goal).
- 2026-07-08 decisions: name consolidated on **portal** (`gallery` remains a
  compat alias). Implementation happens on a git worktree off the gallery
  repo, not on the main checkout.
- 2026-07-08 feasibility review: added `PRAGMA user_version` migration step
  (CREATE-IF-NOT-EXISTS can't ALTER `requests`); compat dual-write into
  `posts` specified incl. `project=None → inbox`; cookie-authed browser twin
  routes specified (`/r/{id}/decide` precedent); `ask`/`pull` pinned to
  client-side polling (no server-side long poll on the single locked sqlite
  connection); before image stored out-of-band on `requests`, not as a
  0-indexed variant (variants are 1-based).
- 2026-07-08 integration review: accepted shipped message storage as a
  separate `messages` queue table/API rather than forcing immediate
  post-envelope unification; §2-§5 now state that `posts` carries
  report/decision entries while messages remain stream-scoped queue records.
- 2026-07-08 integration review: accepted v1 single-token access semantics:
  auth failures are `401`, missing resources are `404`, closed-stream
  mutations are `409`, and no `403` state exists until per-stream/user auth.
- 2026-07-08 integration review: accepted fixed notification policy for v1.1
  (decisions and `to_human` ask messages ring; reports and steering notes are
  silent) and deferred configurable per-type/per-stream policy.
- 2026-07-08 integration review: documented that agent-side message creation
  auto-creates missing session streams, while read/pull and browser twin routes
  require an existing stream.
- 2026-07-08 integration review: fixed legacy project-derived stream slugs so
  long project names remain within the route slug contract, keep a
  deterministic hash suffix when truncated, and are routable via `/s/<slug>`
  and `/api/streams/{slug}`.
- 2026-07-08 integration review: fixed notification/config failure paths so
  legacy decision request creation does not fail after persistence when the
  doorbell thread cannot start or config would otherwise be reloaded for the
  notification URL.
- 2026-07-08 integration review: fixed message `since` cursor precision so
  fast `portal ask` replies in the same wall-clock second are not skipped by
  truncating timestamps to seconds.
- 2026-07-08 integration review / RESOLVED 2026-07-10 (card DP0kxrKz): explicit
  `portal post --stream <slug>` now sets the authoritative `requests.stream_id`
  to that stream (created if missing), and the single "decision" mirror post is
  created by `create_request` in the owning stream — so ownership and the feed
  agree by construction. Closing that stream now makes the request read-only
  (`POST /api/requests/{id}/verdict` → 409; `/r/{id}` shows the archived
  read-only banner and the back-link points at the owning stream). When
  `--stream` is absent the legacy project-derived `stream_id`
  (`inbox`/`proj-*`) is unchanged. The CLI no longer makes a second
  `create_stream_post` call (which would double-post). No schema migration:
  rows created before this fix keep their legacy `stream_id` — an accepted
  historical inconsistency, intentionally not rewritten.
- 2026-07-08 integration review: proposed follow-up card for ask/answer
  correlation; answers and human steering notes currently share the
  unconsumed `to_agent` queue, so a linked reply model or message kind is
  needed before `portal ask` and `portal pull` can be fully disambiguated.
