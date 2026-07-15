# Secure editor hub evidence

Status: **PARTIAL — implementation and local authenticated rendering pass; production deployment and remote-route smoke remain.**

## Proven

- The authenticated `/editor-hub` renders stable GrapesJS and Phaser Editor
  entries while missing service URLs remain explicit disabled placeholders.
- Desktop (`1440 × 1000`) and mobile (`390 × 844`) authenticated renders are
  responsive and passed an independent aesthetics re-review with no remaining
  P1/P2 findings.
- Human entry uses the login/cookie path. External editor, preview, reference,
  and evidence URLs reject embedded credentials, secret query keys, unsupported
  schemes, malformed URLs, and userinfo.
- Uvicorn access logs redact common and encoded query-secret spellings before
  handlers emit them. The local capture log recorded only `[REDACTED]`.
- The full test suite passes: `359 passed`.
- Independent final code review found no remaining P1/P2 findings after
  malformed URL parsing was made fail-closed.

## Captures

- `desktop.png` — SHA-256
  `5a1f5ae0489ebf50867cf16e8b482ff8415caafaa40c3802d4fd030f9a6d5acf`
- `mobile.png` — SHA-256
  `01fe527195b9bf8115e1e81d555b87988d3726488eb71fbfa3ec5038b368234c`

## Claim boundary and release gate

The current production hostname returned HTTP 502 during this evidence run
because no backend was listening on port 8787 and the launchd job was not
loaded. This artifact does **not** claim a successful deployment or a usable
remote `/editor-hub` yet.

Before calling the Portal handoff complete:

1. land the reviewed branch through the authorized integration/main flow;
2. rotate the shared credential rather than revive the stale deployment;
3. install/restart the reviewed service and verify launchd PID equals the port
   8787 listener;
4. verify the HTTPS health, login, cookie, and `/editor-hub` routes remotely;
5. configure revision-specific editor/Preview/evidence links without secrets in
   their URLs.
