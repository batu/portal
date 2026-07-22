---
status: blocked
subject: Browser-playable game-build aesthetics review
created: 2026-07-20
mode: pipeline
---

# Evidence: Browser-playable game-build aesthetics review

## Verdict

Blocked: the real Marble Run Vite bundle publishes and serves through Portal, but this worker sandbox cannot launch or attach to a browser, so the required playthrough, four frames, and aesthetics reviewer report cannot be produced.

## What Changed

- No product code changed during this evidence pass.
- A disposable Portal dataset outside the repository was populated with the latest Marble Run `dist/` bundle and both preview-enabled and APK-only releases.

## Evidence Captured

| Type | Artifact / Command | Result |
|------|--------------------|--------|
| runtime | `GALLERY_DATA_DIR=<temp>/data uv run portal serve` | passed; Uvicorn served `http://127.0.0.1:8797` |
| publish | `portal game publish ... --web <temp>/marble-run-dist.zip` | passed; returned the permanent game, download, and preview URLs |
| compatibility | second `portal game publish` without `--web` | passed; returned `preview_url: null` |
| page probe | `curl -fsS http://127.0.0.1:8797/games/marble-run` | passed; page contained browser-preview, no-preview, and device-preset content |
| browser | `agent-browser ... open http://127.0.0.1:8797/games/marble-run` | blocked; Chrome exited before writing `DevToolsActivePort` |
| browser fallback | Playwright headless shell with remote debugging | blocked; macOS `MachPortRendezvous` bootstrap failed with `Permission denied (1100)` |
| attach fallback | probes of local CDP ports 9222, 9229, and 9515 | blocked; no endpoint was available |

## Reviewer Assessments

| Reviewer | Status | Result |
|----------|--------|--------|
| game-aesthetics-reviewer | blocked | Not spawned because the required four real PNG frames do not exist; the TWF contract treats missing frames as unavailable evidence. |

## Analysis

The application-level path is healthy: Portal accepted the current FabrikaV2 Marble Run bundle from `/Users/base/dev/appletolye/fabrikav2/games/marble_run/dist`, extracted it, returned a browser-preview URL, served the game page, and preserved the older release without a preview. Rendering failed below the application layer. Both `agent-browser` and the installed Playwright Chromium binary terminate during macOS browser bootstrap, and there is no running CDP browser to attach to. Without a real 3–8 second render, sampling synthetic or blank frames would not satisfy the aesthetics gate.

## Gaps

- Required 3–8 second browser playthrough recording.
- Four sampled PNG frames covering opening, first interaction, mid-play, and end state.
- Canonical game-aesthetics-reviewer report based on those frames.

## Next Action

Re-run the aesthetics stage in a host execution context permitted to launch Chromium (or expose an existing browser CDP endpoint), capture the playthrough and four frames, then run the canonical reviewer and advance only with zero P1 findings.
