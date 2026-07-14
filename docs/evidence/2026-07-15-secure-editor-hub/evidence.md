---
status: passed
subject: Secure durable editor-test hub
created: 2026-07-15
mode: pipeline
---

# Evidence: Secure durable editor-test hub

## Verdict

Focused and full-suite evidence confirms token redaction, HTTPS-aware cookies,
hardened link handling, durable Marble placeholders, and the local rendered hub
contract without deploying or restarting the public service.

## What Changed

- Added an authenticated editor hub with two fixed Marble editor entries,
  separate revision previews, reference/evidence links, reset/baseline text, and
  apply-request status.
- Prevented access-log and outbound-link credential leakage, including encoded
  and legacy semicolon-delimited query keys.
- Set `Secure` cookies for direct or proxy-reported HTTPS while preserving local
  HTTP development.
- Corrected the public threat-boundary documentation and made launchd validation
  require the launchd PID to own the backend listener.

## Evidence Captured

| Type | Artifact / Command | Result |
|------|--------------------|--------|
| focused tests | `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q tests/test_editor_hub.py tests/test_web_login.py tests/test_cli.py::test_init_does_not_print_token_in_url` | 32 passed |
| full tests | `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q` | 358 passed; one pre-existing Starlette deprecation warning |
| rendered view | TestClient-rendered `/editor-hub` response | two disabled Marble placeholders, all required status/reset/reference/apply fields, and no editor link until configured |
| diff hygiene | `git diff --check` | passed |

## Reviewer Assessments

| Reviewer | Status | Result |
|----------|--------|--------|
| correctness/security/adversarial | passed after fixes | preserved partial/malformed placeholders and closed encoded/semicolon secret-query bypasses |
| testing/API/standards | passed | no actionable defects remained |

## Gaps

- Production launchd restart, listener-PID comparison, Caddy behavior, and the
  public health request were not run because this worker is explicitly
  forbidden from deploying or restarting the service.
- The rendered HTML and browser-enforced headers were verified through
  TestClient; a real-browser visual observation remains a conductor smoke check.

## Next Action

None for the worker implementation. The conductor must approve and perform the
live launchd install/restart and production smoke checks after merge.
