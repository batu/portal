---
status: passed
subject: stream web pages /s/<slug> and streams index section
created: 2026-07-08
mode: pipeline
contract: visual-runtime
---

# Evidence: stream web pages /s/<slug> and streams index section

## Verdict
Passed. Focused tests, the full test suite, live-server HTTP evidence, and exact recorded Chromium/InSitu observations confirm that stream pages render reports and decision links, the streams index appears on the home page, and report HTML media is browser-renderable without attachment disposition.

## What Changed
- Added authenticated server-rendered stream detail pages at `/s/{slug}` with newest-first report and decision posts.
- Added a home-page Streams section with slug, title, kind, post count, latest activity, and archived state.
- Made report HTML media render inline for report posts only, while keeping non-report HTML media as attachments.
- Kept report iframes sandboxed with `allow-same-origin` for the auth cookie and without `allow-scripts`.

## Evidence Captured
| Type | Artifact / Command | Result |
|------|--------------------|--------|
| test | `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q tests/test_web_streams.py tests/test_streams_api.py::test_media_serves_html_variants_as_attachment` | passed: 10 tests, 1 known Starlette/httpx warning |
| test | `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q` | passed: 60 tests, 1 known Starlette/httpx warning |
| live HTTP | `assets/live-stream-page.html`, `assets/live-page-headers.txt` | stream page returned 200, set the web auth cookie, emitted `sandbox="allow-same-origin"`, and did not leak `token=` into rendered links |
| live HTTP | `assets/live-media-headers.txt`, `assets/live-report.html` | report HTML media returned 200, `text/html`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: sandbox allow-same-origin`, and no attachment disposition |
| browser observation | Trello card comments 10 and 11 | conductor/InSitu live Chromium verified phone viewport rendering, visible report iframe content, cookie auth, inline media, home/stream/project pages, and no remaining visual gate |
| environment note | `assets/playwright-launch-attempt.txt` | this worker installed ephemeral Playwright, but local Chromium launch was blocked by macOS sandbox Mach-port permissions |

## Reviewer Assessments
| Reviewer | Status | Result |
|----------|--------|--------|
| conductor aesthetics review | passed | live Chromium 390x844 verified report iframe content and stream/home/project page visuals |
| InSitu browser check | passed | live Chromium via Playwright verified cookie auth, inline media 200, and visible iframe content |

## Gaps
- None for the release gate. This worker could not relaunch Chromium inside its sandbox, but the card already contains exact, recent browser-runtime proof from conductor and InSitu checks. The local live-server HTTP proof verifies the headers and markup that fixed the prior iframe blank states.

## Next Action
None.

```json
{
  "skill": "ce-evidence",
  "status": "passed",
  "artifact_path": "docs/evidence/2026-07-08-stream-web-pages/evidence.md",
  "verdict": "Focused tests, full-suite tests, live-server HTTP evidence, and exact recorded Chromium/InSitu observations confirm the stream web pages and report iframe/media path.",
  "mode": "pipeline",
  "contract": "visual-runtime",
  "evidence": [
    {
      "type": "test",
      "label": "focused stream/media regressions",
      "result": "passed: 10 tests",
      "path": null,
      "url": null
    },
    {
      "type": "test",
      "label": "full pytest suite",
      "result": "passed: 60 tests",
      "path": null,
      "url": null
    },
    {
      "type": "live-http",
      "label": "stream page and report media headers",
      "result": "passed: auth cookie, iframe sandbox, inline report HTML, CSP sandbox, nosniff, no attachment",
      "path": "docs/evidence/2026-07-08-stream-web-pages/assets/",
      "url": null
    },
    {
      "type": "browser-observation",
      "label": "recorded conductor/InSitu Chromium checks",
      "result": "passed: visible iframe content and phone viewport stream UI verified on card comments 10 and 11",
      "path": null,
      "url": null
    }
  ],
  "reviewers": [
    {
      "name": "conductor aesthetics review",
      "status": "passed",
      "summary": "Live Chromium 390x844 verified the report iframe rendered inline and the stream/home/project pages looked correct."
    },
    {
      "name": "InSitu browser check",
      "status": "passed",
      "summary": "Live Chromium via Playwright verified cookie auth, media 200 inline, and visible iframe content."
    }
  ],
  "gaps": [],
  "next_action": null,
  "pr_updated": false
}
```
