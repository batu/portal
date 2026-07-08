# Solution Lessons Index

This catalog stores durable lessons mined from the Portal board run. It is not
a backlog and it is not a substitute for tests; each entry below points at the
source that made the rule durable.

## Source Inventory

- Trello REST fetch on 2026-07-08: resolved card `Nj29W8GT` to board
  `gallery (scratch-1)`, fetched 731 `commentCard` actions, and checked the 7
  open cards for backlog dedupe.
- Structured Trello handoffs: searched `Done`, `Verified-how`, `Remaining`,
  `Surprises`, and `Plan-friction` fields across the board comments.
- Board lessons: `twf lesson list` returned lesson `3b565316` from card
  `8OEiwp9u` and lesson `825e8279` from card `jAQ8bS6C`.
- Evidence: checked `docs/evidence/2026-07-08-stream-web-pages/**` and
  `docs/evidence/2026-07-08-portal-phase1/**`.
- Spec: checked `docs/portal-spec.md` sections 3, 5, 6, 7, 11, 13, and the
  Review log.
- Dedupe anchors: open planned cards `08KM8i8Q` (Portal Trello watcher) and
  `hVtTtwRa` (phases 2+3 proof) were not duplicated in `todos/cards/`.

## Entries

| Entry | Rule | Key sources |
|---|---|---|
| [Iframe Report Rendering Needs Both Cookie Sandbox And Inline Media](2026-07-08-iframe-report-rendering-needs-cookie-sandbox-and-inline-media.md) | Iframed authenticated report HTML needs `sandbox="allow-same-origin"` and report-only inline media headers. | cards `A9oMiXGV`, `zKUB2Tnl`; stream web-pages and phase-1 evidence |
| [TestClient Needs Browser Header Proxies](2026-07-08-testclient-needs-browser-header-proxies.md) | When browser execution is unavailable, assert the markup and headers that browsers actually depend on. | card `zKUB2Tnl`; phase-1 evidence |
| [Run Uv With Sandbox Cache](2026-07-08-run-uv-with-sandbox-cache.md) | In sandboxed workers, run uv commands with `UV_CACHE_DIR=/private/tmp/uv-cache`. | `twf` lesson `3b565316`; card `8OEiwp9u` |
| [Plan Artifacts Need Porcelain Status](2026-07-08-plan-artifacts-need-porcelain-status.md) | `git diff --check` is not enough for plan-stage docs; verify no untracked files remain. | `twf` lesson `825e8279`; card `jAQ8bS6C` |
| [Project Stream Slugs Stay Visible And Routable](2026-07-08-project-stream-slugs-stay-visible-and-routable.md) | Legacy project streams keep a `proj-` slug contract with deterministic truncation. | card `GNGHjZ9y`; `docs/portal-spec.md` |
| [Browser Writes Need Cookie Twins](2026-07-08-browser-writes-need-cookie-twins.md) | Browser write actions need cookie-auth twin routes and token-free form/JS URLs. | card `oaxqoVgF`; `docs/portal-spec.md` |
| [Chromium Launch May Be Worker Sandbox Blocked](2026-07-08-chromium-launch-may-be-worker-sandbox-blocked.md) | Treat macOS Mach-port Chromium failures as environment limits, not app proof. | cards `A9oMiXGV`, `jAQ8bS6C`, `oaxqoVgF`; stream web-pages evidence |

## Omitted Candidates

- `launchd` / `launchctl` bootstrap over SSH was named in the card, but the
  Trello REST export had no matching `launchd`, `launchctl`, `LaunchAgents`,
  `install.sh`, or Mac mini deployment comments. It is not written as a
  solution entry here.
- Portal Trello watcher and phase 2+3 release proof are already represented by
  open planned cards `08KM8i8Q` and `hVtTtwRa`, so they were not duplicated as
  local idea drafts.
