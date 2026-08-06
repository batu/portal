---
status: partial
subject: Portal exact-session agent conversations and release-preview hardening
created: 2026-08-06
mode: pipeline
---

# Evidence: Portal exact-session agent conversations

## Verdict

Passed for the local desktop interaction and delivery contract; partial overall.
Portal now has an Agents tab that submits comments to one exact live Agency
session and records durable transport receipts instead of leaving interactive
comments in the generic `queued` pull lane. The full Portal and Agency suites,
a real moved-pane tmux integration, a capability-boundary probe, and an atomic
browser recording pass. Physical mobile soft-keyboard behavior and target
clarity with multiple similar sessions remain unverified. Nothing was deployed.

## What Changed

- Added an Agents directory, exact-session composer, per-agent history, delivery
  attempt ledger, and explicit `pending`, `submitting`, `submitted`, `failed`,
  and `unknown` states.
- Kept generic queued notes and exact steering separate: targeted rows cannot be
  consumed by `portal pull`, while successful terminal submissions alone set
  `consumed_at`.
- Added browser-generated idempotency keys, atomic server reconciliation,
  once-only restart recovery, explicit confirmation before retrying ambiguous
  delivery, archived-stream read-only behavior, and focus restoration after a
  successful reload.
- Scoped executable producer views to request-specific HMAC capabilities. They
  can read declared media and submit their own verdict; they cannot inherit the
  Portal cookie or mutate Agents.
- Hardened Portal's game web-bundle rewrite to cover absolute paths inside
  JavaScript template literals, which the Find the Bird nested preview exposed.
- In Agency, added exact provider/session reply commands, foreground process and
  TTY validation, literal stdin delivery, stable-pane resolution, and honest
  `failed` versus `unknown` outcomes.

## Verification

- Portal: `uv run pytest -q` — 443 passed, 11 dependency deprecation warnings.
- Portal changed-file lint: `uv run ruff check gallery/server.py tests/test_games.py tests/test_web_agents.py` — passed.
- Agency: `uv run pytest -q` — 2053 passed, 21 subtests passed, 3 multiprocessing deprecation warnings.
- Agency: `uv run ruff check .` — passed.
- Real tmux integration: the reply followed a stable session after pane swap;
  the former-position shell received no input and foreground-shell delivery was
  rejected.
- Browser flow: two consecutive Enter submissions succeeded without another
  composer click; one exact message moved from `unknown` at one attempt to
  `submitted_to_terminal` at two attempts; the unrelated failed retry remained
  enabled.
- Mobile Chromium viewport: Agents and Games navigation targets measured 44 CSS
  pixels high at 390x844, with no visible clipping.
- Compound grounding: passed with no findings or omissions after the final
  ambiguous-write and archived-retry corrections.
- Secret scan over the report, solution, and evidence bundle found no credential
  material.

## Artifacts

- [`assets/agents-atomic-flow.webm`](assets/agents-atomic-flow.webm) — 5.36-second
  end-to-end interaction recording.
- [`assets/agents-atomic-flow-contact-sheet.png`](assets/agents-atomic-flow-contact-sheet.png)
  — consecutive recording frames showing focus and receipt changes.
- [`assets/agents-unknown-before-confirmation.png`](assets/agents-unknown-before-confirmation.png)
  and [`assets/agents-unknown-after-confirmation.png`](assets/agents-unknown-after-confirmation.png)
  — the same immutable message before and after confirmed retry.
- [`assets/agents-atomic-mobile.png`](assets/agents-atomic-mobile.png) — responsive
  390x844 Agents page.
- [`assets/view-capability-boundary.png`](assets/view-capability-boundary.png) —
  executable view can use its scoped verdict capability but not Agents authority.
- [`assets/agents-atomic-flow-trace.zip`](assets/agents-atomic-flow-trace.zip) —
  Playwright trace with the single composer click and subsequent focus checks.
- [`assets/ui-interaction-review.json`](assets/ui-interaction-review.json) and
  [`assets/compound-grounding.json`](assets/compound-grounding.json) — final
  reviewer outputs.
- [`assets/pre-fix-ce-review.json`](assets/pre-fix-ce-review.json) — frozen
  pre-fix review. Its `Not ready` verdict and 14 findings are preserved rather
  than rewritten; all 14 were applied and regression-tested afterward.

## Reviewer Assessments

- ce-code-review: pre-fix `Not ready`; 14 validated P0-P2 findings fixed. These
  included producer-view authority, foreground-shell delivery, response-loss
  duplication, restart recovery, bundle integrity, archive lifecycle, provider
  validation, Unicode separators, moved-pane coverage, and bridge exceptions.
- ce-compound grounding: passed after fixes, with no findings or omissions.
- UI interaction reviewer: partial, with no unresolved desktop/browser finding.
  Focus retention and 44-pixel mobile targets are resolved; physical soft
  keyboards and multiple similar targets are outside the supplied evidence.

## Known Limits

- Physical iOS Safari and Android Chrome soft-keyboard, safe-area, and visual
  viewport behavior have not been captured.
- The evidence fixture has one replyable agent, so two similar live session
  labels have not been visually disambiguated.
- Terminal keystrokes still have a narrow time-of-check/time-of-use window
  between the final process-identity check and tmux processing Enter. Eliminating
  it requires provider-owned IPC with acknowledgement, not more optimistic UI.
- The feature exists only on isolated local branches. No production Portal
  deployment, branch merge, push, or live-state mutation was performed.

## Next Action

After review, authorize the branch publication/deployment separately; then run
the restored-focus flow once on physical iOS Safari and Android Chrome and
capture a two-similar-agent fixture.

```json
{
  "skill": "ce-evidence",
  "status": "partial",
  "artifact_path": "docs/evidence/2026-08-06-agent-conversations/evidence.md",
  "verdict": "Exact-session steering is verified locally across Portal, Agency, real tmux, capability boundaries, and desktop/mobile-viewport browser evidence; physical mobile keyboards and similar-session target clarity remain open.",
  "mode": "pipeline",
  "evidence": [
    {
      "type": "test",
      "label": "Portal full suite",
      "result": "passed: 443 tests",
      "path": null,
      "url": null
    },
    {
      "type": "test",
      "label": "Agency full suite and real tmux integration",
      "result": "passed: 2053 tests and 21 subtests",
      "path": null,
      "url": null
    },
    {
      "type": "recording",
      "label": "atomic exact-session browser flow",
      "result": "passed for focus restoration, delivery-state transition, and retry independence",
      "path": "docs/evidence/2026-08-06-agent-conversations/assets/agents-atomic-flow.webm",
      "url": null
    },
    {
      "type": "security-boundary",
      "label": "request-scoped view capability",
      "result": "view verdict allowed; Agents mutation denied",
      "path": "docs/evidence/2026-08-06-agent-conversations/assets/view-capability-boundary.png",
      "url": null
    }
  ],
  "reviewers": [
    {
      "name": "ce-code-review",
      "status": "passed_after_fixes",
      "result": "All 14 validated pre-fix findings were applied and regression-tested; the frozen source review remains unchanged."
    },
    {
      "name": "ce-compound-grounding",
      "status": "passed",
      "result": "No findings or omissions."
    },
    {
      "name": "ui-interaction",
      "status": "partial",
      "result": "Browser findings resolved; physical mobile keyboard and similar-session evidence remain missing."
    }
  ],
  "gaps": [
    "Physical iOS and Android soft-keyboard behavior is unverified.",
    "Two similar live sessions have not been visually disambiguated.",
    "No production deployment or live Portal mutation was authorized."
  ],
  "next_action": "Review the isolated commits, then separately authorize publication or deployment before live verification.",
  "pr_updated": false
}
```
