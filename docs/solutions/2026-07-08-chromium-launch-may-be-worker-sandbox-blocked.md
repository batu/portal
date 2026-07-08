# Chromium Launch May Be Worker Sandbox Blocked

## Problem

Workers sometimes cannot run local Chromium/Playwright even when the app and
tests are healthy.

## Root cause

On macOS inside this worker sandbox, Chromium can fail before app code loads
with a Mach-port `bootstrap_check_in` permission denial. That failure does not
prove anything about the web app, but ignoring it can leave visible UI without
browser evidence.

## Rule

If Chromium dies with the known Mach-port sandbox failure, stop trying to tune
the app or browser flags. Capture the launch log, run the strongest non-browser
proxies available, and cite a conductor/InSitu browser run when visual proof is
required. Do not call a browser-blocked worker run a passed visual gate by
itself.

## How to verify

Check the launch error for `MachPortRendezvousServer` or `bootstrap_check_in`
permission denial. Then pair the log with:

- focused and full pytest;
- live HTTP headers and rendered HTML artifacts;
- a real browser observation from conductor/InSitu when the change is visible.

## Sources

- `docs/evidence/2026-07-08-stream-web-pages/assets/playwright-launch-attempt.txt`.
- `docs/evidence/2026-07-08-stream-web-pages/evidence.md`, environment note and
  recorded conductor/InSitu browser observations.
- Trello card `A9oMiXGV`, 2026-07-08 evidence-stage handoff: local Chromium
  launch was blocked, but live HTTP proof and conductor/InSitu browser evidence
  covered the gate.
- Trello card `jAQ8bS6C`, 2026-07-08 reviewed-stage handoff: live Playwright
  rerun was blocked by the same macOS sandbox permission denial.
- Trello card `oaxqoVgF`, 2026-07-08 worked-stage handoff: browser visual
  capture was blocked locally, then InSitu verified the live worktree server.
