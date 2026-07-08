# feat: provide a sandbox-aware browser proof runner

Source: `docs/evidence/2026-07-08-stream-web-pages/assets/playwright-launch-attempt.txt`;
Trello cards `A9oMiXGV`, `jAQ8bS6C`, and `oaxqoVgF`.
Status: Unscheduled draft; not on Trello; requires human conductor scheduling before implementation.

## Problem

Workers need browser evidence for visible changes, but local Chromium can fail
inside the macOS worker sandbox with Mach-port permission errors before app code
loads.

## Decided approach

Candidate approach for conductor review: provide a standard fallback path that
detects the known Chromium launch failure, captures the log, runs live HTTP
header/markup proxies, and requests conductor/InSitu browser proof without
repeated ad hoc debugging.

## Scope fence

Evidence tooling and pipeline guidance only. Do not weaken visual gates for
visible UI changes and do not treat TestClient/header proxies as full browser
proof.

## Acceptance criteria

- The runner detects the known Mach-port failure and saves a concise log.
- The fallback runs configured live HTTP/header checks when available.
- Handoff language clearly distinguishes environment-blocked browser runs from
  passed browser observations.
- The workflow still requires conductor/InSitu proof for visible UI gates.

## Verification

Run the proof runner in a sandboxed worker where Chromium launch is expected to
fail, then verify the saved log, HTTP artifacts, and handoff wording.
