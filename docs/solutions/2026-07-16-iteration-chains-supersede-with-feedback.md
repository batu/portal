---
title: "Iteration Chains: Supersede With Feedback, Share the /c/ Link"
date: "2026-07-16"
module: "portal"
problem_type: "workflow_issue"
component: "tooling"
severity: "medium"
applies_when:
  - "an agent posts a revised version of an existing decision request"
  - "a human wants one permanent link that always opens the latest version"
  - "reconstructing why each design version was retired"
tags: ["iteration-chains", "supersede", "feedback-trail", "chain-view", "portal-cli", "og-previews"]
---

# Iteration Chains: Supersede With Feedback, Share the /c/ Link

## Context

A 22-version design-iteration loop (marble-run visual simplification, requests v1→v22 in one afternoon) exposed how painful per-iteration portal posts are when each round mints a fresh URL: the human juggles stale links, feedback lives only in chat history, and the agent has to hand-stitch supersede relationships after the fact. The portal grew first-class iteration chains during that session; this doc captures the workflow so future loops use it from round one.

## Guidance

**Post every new version as a chain step, never as a standalone request:**

```bash
portal post --kind pick-one --title "Thing (v5)" --stream my-loop \
  --supersedes req_old \
  --feedback "the user's actual words that prompted this round" \
  --author "claude-fable-5" \
  out/*.png
# -> {"id":"req_new", ..., "supersedes":"req_old", "chain_url":"https://.../c/req_new"}
```

- `--supersedes` makes the post atomic: the CLI posts, then immediately supersedes the old request, and exits nonzero if the supersede step fails after the post (`gallery/cli.py:156-164`). Take the successor id from the post result — never from `portal list | head -1`.
- `--feedback` is recorded on the **retired** version (`gallery/db.py:1096`), so each old tab in the chain view shows the critique that killed it. Quote the human's actual words. `--feedback` without `--supersedes` is rejected (`gallery/cli.py:120-121`).
- `--author` stamps who produced the version (defaults to `$PORTAL_AUTHOR`); it renders as a chip on the request page.
- Share the `chain_url` printed by post (`gallery/cli.py:166`) **once**. `/c/<id>` resolves from any member of the chain (`gallery/db.py:1037` walks `superseded_by` links in both directions), shows one tab per version, and a plain refresh always opens the latest — the link never goes stale as the loop continues.

**Feedback can be attached or fixed retroactively**, even on superseded requests: `portal feedback <id> "text"`. `set_feedback` deliberately works on terminal requests because feedback is "an annotation about why a version was retired, not a lifecycle mutation" (`gallery/db.py:1015-1020`).

**Ops facts for iterating on the portal itself:**

- The server is an *editable* uv install: template and static-file edits serve live from disk, but **Python changes need a restart** — `launchctl kickstart -k user/$UID/com.appletolye.gallery` (the gui launchd domain rejects kickstart; use the user domain).
- Bump the asset query string (`style.css?v=N`, `app.js?v=N` in `gallery/templates/base.html`) whenever layout/JS changes ship, or the human's browser shows the old page and reports your fix as broken.
- Link-preview crawlers (WhatsApp/Slack/etc., matched by user-agent at `gallery/server.py:1680`) get a no-auth meta-tags-only page instead of the login redirect (`gallery/server.py:1796`), with `og:image` served from the public `/og/<req_id>` route (`gallery/server.py:1724`) — deliberately scoped to the request's *first image variant* only, so previews work without opening the portal up.

## Why This Matters

Two docs of the same design loop drift apart; twenty separate requests of the same design loop are unnavigable. The chain turns an iteration loop into a single artifact: one permanent URL for the whole story, per-version feedback preserved in place, authorship recorded, and the latest version always one refresh away. It also makes the agent's process auditable — a reviewer can walk v1→vN and see exactly which human critique produced each change.

## When to Apply

- Any portal decision loop expected to run more than one round (design variants, copy iterations, evidence re-captures).
- Retro-fitting: an existing pile of related requests can be chained after the fact with `portal supersede <old> --successor <new> --feedback "..."`.
- Not needed for genuine one-shot requests (a single approve/comment with no successor).

## Examples

A real chain from the originating session: `https://portal.basegamelab.com/c/req_9566e8` — 22 tabs, each superseded tab carrying the feedback that prompted the next version ("The sheen is pretty bad — remove that one…", "Crop so only the movement of the balls is there…"), ending at the shipped visual set.

Retro-fix of a mislinked round:

```bash
# posted v5 but forgot the chain step
portal supersede req_v4 --successor req_v5 --feedback "make it 2 rows of 5"
# blank feedback on an already-superseded tab
portal feedback req_v3 "dots need the same visual weight as the rings"
```

## Related

- [Browser writes need cookie twins](2026-07-08-browser-writes-need-cookie-twins.md) — the auth-surface contract the `/c/` chain page follows; the tokenless `/og/<id>` crawler route is a deliberate, scoped exception.
- [TestClient needs browser header proxies](2026-07-08-testclient-needs-browser-header-proxies.md) — testing pattern used for the chain-view and OG-preview routes.
- [Project stream slugs stay visible and routable](2026-07-08-project-stream-slugs-stay-visible-and-routable.md) — stream routing that chain pages link back to via breadcrumbs.
