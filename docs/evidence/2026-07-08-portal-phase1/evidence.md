---
status: passed
subject: Portal phase-1 E2E proof, evidence artifacts, and README docs
created: 2026-07-08
mode: pipeline
---

# Evidence: Portal phase-1 E2E proof, evidence artifacts, and README docs

## Verdict
Passed. The new public-route E2E test and the full pytest suite confirm Portal phase 1 works across report stream auto-create, inline report HTML, before/after decisions, verdicts, and archived read-only behavior.

## What Changed
- Added `tests/test_e2e_portal.py` with one TestClient-driven flow through report post, `/s/<slug>`, report media, before/after request, request page, verdict, stream close, and post-close verdict rejection.
- Added this evidence bundle with rendered HTML, media-header dumps, command outputs, and a reproducible artifact generator.
- Added a README Portal section covering permanent stream URLs, auto-create, CLI verbs, `post --before`, the `gallery` alias, the 200 MB soft cap, and phase-2/3 pointers.

## Commands Run
| Command | Output Artifact | Result |
|---|---|---|
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q tests/test_e2e_portal.py > docs/evidence/2026-07-08-portal-phase1/assets/e2e-pytest-output.txt 2>&1` | `assets/e2e-pytest-output.txt` | passed: 1 test, 1 known Starlette/httpx warning |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q > docs/evidence/2026-07-08-portal-phase1/assets/full-pytest-output.txt 2>&1` | `assets/full-pytest-output.txt` | passed: 94 tests, 1 known Starlette/httpx warning |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev python docs/evidence/2026-07-08-portal-phase1/generate_rendered_assets.py > docs/evidence/2026-07-08-portal-phase1/assets/rendered-artifacts-generation-output.txt 2>&1` | `assets/rendered-artifacts-generation-output.txt` | generated rendered HTML/header artifacts and asserted the temporary token was absent |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev portal --help > docs/evidence/2026-07-08-portal-phase1/assets/portal-help-output.txt 2>&1` | `assets/portal-help-output.txt` | captured top-level Portal verbs |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev gallery --help > docs/evidence/2026-07-08-portal-phase1/assets/gallery-help-output.txt 2>&1` | `assets/gallery-help-output.txt` | captured compatibility alias help; it prints the same `usage: portal ...` surface |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev portal post --help > docs/evidence/2026-07-08-portal-phase1/assets/portal-post-help-output.txt 2>&1` | `assets/portal-post-help-output.txt` | confirmed `--stream`, `--before`, and `before-after` syntax |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev portal report --help > docs/evidence/2026-07-08-portal-phase1/assets/portal-report-help-output.txt 2>&1` | `assets/portal-report-help-output.txt` | confirmed `portal report --stream STREAM --title TITLE file_html [assets ...]` |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev portal stream --help > docs/evidence/2026-07-08-portal-phase1/assets/portal-stream-help-output.txt 2>&1` | `assets/portal-stream-help-output.txt` | confirmed stream subcommands |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev portal stream new --help > docs/evidence/2026-07-08-portal-phase1/assets/portal-stream-new-help-output.txt 2>&1` | `assets/portal-stream-new-help-output.txt` | confirmed `slug`, `--kind`, and `--title` |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev portal stream close --help > docs/evidence/2026-07-08-portal-phase1/assets/portal-stream-close-help-output.txt 2>&1` | `assets/portal-stream-close-help-output.txt` | confirmed close syntax |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev portal wait --help > docs/evidence/2026-07-08-portal-phase1/assets/portal-wait-help-output.txt 2>&1` | `assets/portal-wait-help-output.txt` | confirmed wait timeout/interval syntax |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev portal status --help > docs/evidence/2026-07-08-portal-phase1/assets/portal-status-help-output.txt 2>&1` | `assets/portal-status-help-output.txt` | confirmed status syntax |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev portal list --help > docs/evidence/2026-07-08-portal-phase1/assets/portal-list-help-output.txt 2>&1` | `assets/portal-list-help-output.txt` | confirmed list flags |

## Token Scan
Command:

```bash
rg -n "redacted-token|token=[^\"'<> ]+" docs/evidence/2026-07-08-portal-phase1/assets
```

Result: no matches. `rg` exits 1 when no matches are found.

## Rendered Artifacts
| Artifact | What It Proves |
|---|---|
| `assets/stream-page.html` | `/s/proj-portal-phase1-e2e` shows the report iframe, decision links, and decided stream state |
| `assets/request-page.html` | `/r/<req_id>` includes before/after markup, toggle controls, and selectable candidate variants |
| `assets/archived-stream-page.html` | closed stream renders the archived read-only notice |
| `assets/archived-request-page.html` | request page renders the archived read-only notice after stream close |
| `assets/report-media.html` | report HTML body served through `/media/<post_id>/<file>` |
| `assets/report-media-headers.txt` | report-post HTML is inline: `text/html`, `nosniff`, CSP `sandbox allow-same-origin`, and no attachment disposition |
| `assets/request-variant-media-headers.txt` | request-variant HTML is attachment-only and has no report CSP |
| `assets/decision-post-media-headers.txt` | decision-post HTML from a `body.files` upload is attachment-only and has no report CSP |
| `assets/flow-summary.txt` | generated stream/request/post ids and post-close verdict revision rejection status |
| `generate_rendered_assets.py` | reproducible TestClient generator for the rendered HTML and header artifacts |

## Reviewer Assessments
| Reviewer | Status | Result |
|---|---|---|
| ce-code-review | passed after fixes | Review-stage findings were addressed in the allowed test/evidence scope: browser verdict route coverage, case-insensitive `Content-Disposition` assertions, deterministic evidence IDs, isolated temp data dir, raw-token fail-fast checks, and disabled Telegram side effects in the generator. |

## Gaps
- None.

## Next Action
None.

```json
{
  "skill": "ce-evidence",
  "status": "passed",
  "artifact_path": "docs/evidence/2026-07-08-portal-phase1/evidence.md",
  "verdict": "The Portal phase-1 E2E flow, full pytest suite, rendered HTML artifacts, media-header dumps, and CLI help captures passed.",
  "mode": "pipeline",
  "evidence": [
    {
      "type": "test",
      "label": "focused Portal E2E",
      "result": "passed: 1 test",
      "path": "docs/evidence/2026-07-08-portal-phase1/assets/e2e-pytest-output.txt",
      "url": null
    },
    {
      "type": "test",
      "label": "full pytest suite",
      "result": "passed: 94 tests",
      "path": "docs/evidence/2026-07-08-portal-phase1/assets/full-pytest-output.txt",
      "url": null
    },
    {
      "type": "rendered-html",
      "label": "stream and request pages",
      "result": "passed: stream/report/decision/before-after/archive markup captured",
      "path": "docs/evidence/2026-07-08-portal-phase1/assets/",
      "url": null
    },
    {
      "type": "headers",
      "label": "report inline and HTML attachment gates",
      "result": "passed: report HTML inline, request variant and decision-post HTML attachment-only",
      "path": "docs/evidence/2026-07-08-portal-phase1/assets/*headers.txt",
      "url": null
    },
    {
      "type": "cli-help",
      "label": "README command surface",
      "result": "passed: Portal and gallery alias help captured",
      "path": "docs/evidence/2026-07-08-portal-phase1/assets/*help-output.txt",
      "url": null
    }
  ],
  "reviewers": [
    {
      "name": "ce-code-review",
      "status": "passed_after_fixes",
      "result": "Review findings were fixed in tests/test_e2e_portal.py and docs/evidence/2026-07-08-portal-phase1/**."
    }
  ],
  "gaps": [],
  "next_action": null,
  "pr_updated": false
}
```
