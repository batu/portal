---
status: passed
subject: Portal phase-2/3 Inbox and Trello watcher E2E proof
created: 2026-07-08
mode: pipeline
---

# Evidence: Portal phase-2/3 Inbox and Trello watcher E2E proof

## Verdict
Passed. The new E2E tests, rendered stream artifacts, watcher transcript, CLI help captures, and full pytest suite confirm the shipped phase-2 Inbox and phase-3 Trello watcher behavior.

## What Changed
- Added `tests/test_e2e_inbox.py` with a TestClient-backed CLI flow for `portal ask` and `portal pull`, browser cookie twin answer/note routes, rendered message states, closed-stream rejections, and media header regressions.
- Added `tests/test_e2e_watch.py` with fake Trello, fake Portal, fake runner, and real watcher state transitions for pickup, one-stage run, max-stage stop, and idempotence.
- Updated `README.md` with Inbox semantics, exit codes, note/answer browser paths, watcher foreground usage, stop conditions, and spec pointers.
- Added this evidence bundle with generated stream HTML, media-header dumps, help captures, focused/full test outputs, and a fake watcher transcript.

## Requirements Cited
- `docs/portal-spec.md` section 7 defines steering notes and agent questions: human notes queue as `to_agent`, `portal ask` posts `to_human`, and polling is client-side.
- `docs/portal-spec.md` section 11 phase 3 defines the Trello watcher slice.
- `docs/evidence/2026-07-08-portal-phase1/evidence.md` is the phase-1 proof shape mirrored here.
- `docs/solutions/2026-07-08-browser-writes-need-cookie-twins.md` and `docs/solutions/2026-07-08-testclient-needs-browser-header-proxies.md` are regression-locked by the inbox E2E and header assets.

## Commands Run
| Command | Output Artifact | Result |
|---|---|---|
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q tests/test_e2e_inbox.py > docs/evidence/2026-07-08-portal-phase2-3/assets/e2e-inbox-pytest-output.txt 2>&1` | `assets/e2e-inbox-pytest-output.txt` | passed: 2 tests, 1 known Starlette/httpx warning |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q tests/test_e2e_watch.py > docs/evidence/2026-07-08-portal-phase2-3/assets/e2e-watch-pytest-output.txt 2>&1` | `assets/e2e-watch-pytest-output.txt` | passed: 1 test, 1 known Starlette/httpx warning |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q > docs/evidence/2026-07-08-portal-phase2-3/assets/full-pytest-output.txt 2>&1` | `assets/full-pytest-output.txt` | passed: 190 tests, 1 known Starlette/httpx warning |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev python docs/evidence/2026-07-08-portal-phase2-3/generate_rendered_assets.py > docs/evidence/2026-07-08-portal-phase2-3/assets/rendered-artifacts-generation-output.txt 2>&1` | `assets/rendered-artifacts-generation-output.txt` | generated stream HTML, media headers, and watcher transcript |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev portal --help > docs/evidence/2026-07-08-portal-phase2-3/assets/portal-help-output.txt 2>&1` | `assets/portal-help-output.txt` | captured top-level verbs |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev gallery --help > docs/evidence/2026-07-08-portal-phase2-3/assets/gallery-help-output.txt 2>&1` | `assets/gallery-help-output.txt` | captured compatibility alias help |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev portal ask --help > docs/evidence/2026-07-08-portal-phase2-3/assets/portal-ask-help-output.txt 2>&1` | `assets/portal-ask-help-output.txt` | captured `ask` syntax and exit/stdout contract |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev portal pull --help > docs/evidence/2026-07-08-portal-phase2-3/assets/portal-pull-help-output.txt 2>&1` | `assets/portal-pull-help-output.txt` | captured `pull` syntax and exit/stdout contract |
| `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev portal trello-watch --help > docs/evidence/2026-07-08-portal-phase2-3/assets/portal-trello-watch-help-output.txt 2>&1` | `assets/portal-trello-watch-help-output.txt` | captured watcher flags and one-shot exit behavior |
| `rg -n "(https?://[^[:space:]\"'<>]+[?&]token=[A-Za-z0-9_-]{12,}\|Authorization:[[:space:]]*Bearer[[:space:]]+[A-Za-z0-9._~-]{8,}\|TRELLO_API_KEY=[A-Za-z0-9]\|TRELLO_TOKEN=[A-Za-z0-9])" README.md tests/test_e2e_inbox.py tests/test_e2e_watch.py docs/evidence/2026-07-08-portal-phase2-3` | `assets/token-scan-output.txt` | passed: no matches |

## Rendered Artifacts
| Artifact | What It Proves |
|---|---|
| `assets/stream-unanswered-question.html` | stream page renders an unanswered agent question, answer form, note box, and no tokenized form URL |
| `assets/stream-answered-question-queued-answer.html` | browser answer twin consumes the question and queues a `to_agent` answer |
| `assets/stream-picked-up-answer.html` | API/CLI consumption renders the answer as picked up |
| `assets/stream-queued-note.html` | browser note twin queues a human steering note |
| `assets/stream-picked-up-note.html` | API/CLI consumption renders the note as picked up |
| `assets/stream-archived.html` | closed streams remain readable and hide note/answer forms |
| `assets/report-media-headers.txt` | report HTML is inline with `text/html`, `nosniff`, CSP `sandbox allow-same-origin`, and no attachment disposition |
| `assets/request-variant-media-headers.txt` | request-variant HTML is attachment-only and has no report CSP |
| `assets/decision-post-media-headers.txt` | decision-post HTML is attachment-only and has no report CSP |
| `assets/watch-transcript.json` | fake watcher pickup, one-stage run, handoff report, tokenless Trello comment, max-stage `to_human` stop, and idempotent later poll |
| `assets/flow-summary.txt` | normalized generated ids and closed-stream report rejection status |
| `generate_rendered_assets.py` | reproducible TestClient/fake-watcher generator for the rendered artifacts |

## Token Scan
Command:

```bash
rg -n "(https?://[^[:space:]\"'<>]+[?&]token=[A-Za-z0-9_-]{12,}|Authorization:[[:space:]]*Bearer[[:space:]]+[A-Za-z0-9._~-]{8,}|TRELLO_API_KEY=[A-Za-z0-9]|TRELLO_TOKEN=[A-Za-z0-9])" README.md tests/test_e2e_inbox.py tests/test_e2e_watch.py docs/evidence/2026-07-08-portal-phase2-3
```

Result: `assets/token-scan-output.txt` contains `no matches`. This scan rejects raw tokenized URLs, bearer headers, and concrete Trello credential assignments while allowing harmless source assertions and docs that mention `token=` without a secret value.

## Reviewer Assessments
| Reviewer | Status | Result |
|---|---|---|
| Reviewed-stage agents | passed after fixes | Correctness, testing, project-standards, security, CLI-readiness clean; maintainability, reliability, and API-contract findings were fixed in the reviewed stage. |

## Gaps
- `portal ask` and `portal pull` intentionally share the unconsumed `to_agent`
  queue in the shipped protocol. This proof sequences the ask answer before the
  separate steering note, and README documents the concurrency caveat.
  Correlation-aware replies remain follow-up work.

## Next Action
None.

```json
{
  "skill": "ce-evidence",
  "status": "passed",
  "artifact_path": "docs/evidence/2026-07-08-portal-phase2-3/evidence.md",
  "verdict": "The phase-2 Inbox and phase-3 Trello watcher E2Es, full suite, rendered artifacts, media headers, help captures, and token scan passed.",
  "mode": "pipeline",
  "evidence": [
    {
      "type": "test",
      "label": "focused Inbox E2E",
      "result": "passed: 2 tests",
      "path": "docs/evidence/2026-07-08-portal-phase2-3/assets/e2e-inbox-pytest-output.txt",
      "url": null
    },
    {
      "type": "test",
      "label": "focused Trello watcher E2E",
      "result": "passed: 1 test",
      "path": "docs/evidence/2026-07-08-portal-phase2-3/assets/e2e-watch-pytest-output.txt",
      "url": null
    },
    {
      "type": "test",
      "label": "full pytest suite",
      "result": "passed: 190 tests",
      "path": "docs/evidence/2026-07-08-portal-phase2-3/assets/full-pytest-output.txt",
      "url": null
    },
    {
      "type": "rendered-html",
      "label": "Inbox stream message states",
      "result": "passed: unanswered, answered, queued, picked-up, and archived states captured",
      "path": "docs/evidence/2026-07-08-portal-phase2-3/assets/stream-*.html",
      "url": null
    },
    {
      "type": "headers",
      "label": "HTML media policy",
      "result": "passed: report HTML inline; request variant and decision-post HTML attachment-only",
      "path": "docs/evidence/2026-07-08-portal-phase2-3/assets/*headers.txt",
      "url": null
    },
    {
      "type": "transcript",
      "label": "fake Trello watcher lifecycle",
      "result": "passed: pickup, one stage, handoff, max-stage stop, idempotent poll",
      "path": "docs/evidence/2026-07-08-portal-phase2-3/assets/watch-transcript.json",
      "url": null
    }
  ],
  "reviewers": [
    {
      "status": "passed after fixes",
      "result": "Reviewed-stage agents found no unresolved findings after README, E2E, evidence, and generator fixes."
    }
  ],
  "gaps": [
    "portal ask and portal pull share the shipped unconsumed to_agent queue; this proof sequences ask answer consumption before separate steering-note consumption and documents the caveat in README."
  ],
  "next_action": null,
  "pr_updated": false
}
```
