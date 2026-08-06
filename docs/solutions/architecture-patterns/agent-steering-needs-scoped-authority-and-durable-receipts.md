---
title: "Agent Steering Needs Scoped Authority and Durable Receipts"
date: "2026-08-06"
category: "architecture-patterns"
module: "Portal agent steering"
problem_type: "architecture_pattern"
component: "authentication"
severity: "high"
applies_when:
  - "A human sends an interactive comment to one live agent session"
  - "An external side effect may succeed even when the HTTP response is lost"
  - "Executable producer content shares a service with operator-only actions"
tags: ["agent-steering", "capability-security", "delivery-receipts", "idempotency", "tmux", "portal"]
---

# Agent Steering Needs Scoped Authority and Durable Receipts

## Context

Portal's original `to_agent` messages were a durable pull queue. A note became
`picked up` only after some agent polled and consumed it. That contract is useful
for unattended consumers, but it is not interactive steering: a comment aimed at
one live agent could remain `queued` forever, and the operator could not tell
whether terminal delivery had been attempted.

Direct steering crosses three authorities that should not be collapsed:

- Portal authenticates the operator and owns durable intent and presentation.
- Agency Fleet knows which provider session is live and owns terminal mutation.
- An uploaded `view` owns only its media and verdict, never operator-wide Portal
  authority.

A successful web request cannot honestly stand in for all three. The transport
may time out after input was written; a tmux pane may move; a provider may yield
its foreground terminal to a shell; or Portal may restart while a delivery is in
flight.

## Guidance

### Keep queue delivery and exact steering as separate products

An untargeted note remains a pull-queue row. A targeted message binds immutable
text to one authoritative `(provider, stable_session_id)` pair and is excluded
from generic `portal pull` queries. Do not let the two consumers race over the
same row.

The Portal-to-Agency contract is deliberately narrow:

```text
directory: agency fleet --reply-targets --json
delivery:  agency fleet --provider PROVIDER --reply SID --json
message:   stdin, never argv
result:    submitted_to_terminal | failed | unknown
```

Portal accepts only curated display fields from the directory. It does not
receive pane IDs, TTYs, PIDs, filesystem paths, transcripts, or message text in
the result. See `gallery/agents.py` and the Fleet HUD reply path in the sibling
Agency repository.

### Persist intent before invoking the external transport

Create the targeted row in `pending`, then use a compare-and-set claim to move it
to `submitting` before calling Agency. Every attempt is appended with its time,
outcome, and sanitized detail. Only `submitted_to_terminal` sets `consumed_at`.

The delivery states mean exactly this:

- `pending`: durable intent exists; no process owns delivery yet.
- `submitting`: one process claimed the attempt; the side effect is in flight.
- `submitted_to_terminal`: literal text and Enter were sent to the revalidated
  terminal target. This is not a read or completion receipt.
- `failed`: the system knows submission did not complete; the same immutable
  target may be retried while its owning stream remains open.
- `unknown`: submission may have occurred. Inspect the terminal before an
  explicit confirmed retry; archived streams remain read-only.

`gallery/db.py` implements the state transitions and append-only attempt ledger.
`gallery/server.py` turns bridge exceptions into durable `unknown`, rather than
optimistically labeling them failed.

### Make response-loss retries reconciliation, not resubmission

The browser generates and persists a cryptographically random submission key
before its first `fetch`. The server binds that key to the immutable tuple of
stream, text, provider, and session. A repeated request with the same key returns
the existing row and state; it does not invoke Agency again. Reusing the key for
different intent is a conflict.

Keep mutable controls locked after an ambiguous browser transport failure and
offer the same submit action as a reconciliation request. A fresh key is a new
intent, even when its text happens to match an older comment. See the submission
helpers in `gallery/static/app.js` and `create_or_get_targeted_message()` in
`gallery/db.py`.

On startup, transactionally convert crash-stranded `submitting` rows to
`unknown` and append one `portal_restart_interrupted` attempt. The recovery must
be idempotent and roll back as a unit.

### Resolve identity at the mutation boundary

Display labels and pane positions are navigation hints, not authorization.
Agency resolves the selected stable session to the current tmux `%pane_id`, then
requires the recorded provider PID to be alive, recognizable, on the pane TTY,
non-stopped, non-zombie, and the owner of that TTY's foreground process group.
It rechecks the same identity after writing literal text and before sending Enter.

This prevents known moved-pane and foreground-shell failures. It does not make
terminal keystrokes atomic: a narrow time-of-check/time-of-use window remains
between the last identity check and tmux processing Enter. Provider-owned IPC
with message acknowledgements is the route to eliminating that residual risk.

### Give executable views capabilities, not cookies

Active producer HTML runs in an opaque sandbox without `allow-same-origin`.
Portal derives an HMAC capability scoped to one request's declared media and
verdict endpoint; the injected fetch bridge removes the global token and omits
credentials. That capability cannot authenticate `/agents`, access another
request's media, or become a general Portal session.

This is intentionally different from trusted, scriptless report HTML, which may
use the cookie sandbox carve-out documented in
[`2026-07-08-iframe-report-rendering-needs-cookie-sandbox-and-inline-media.md`](../2026-07-08-iframe-report-rendering-needs-cookie-sandbox-and-inline-media.md).

## Why This Matters

The design separates five facts that operators otherwise conflate: human intent,
transport attempt, terminal submission, agent acknowledgement, and task
completion. Each fact belongs to a different authority and time boundary.
Collapsing them produces the two worst failure modes in an operator console:
comments that appear permanently queued despite an expected immediate action,
and optimistic success labels that invite unsafe duplicate retries.

Least-authority adapters also keep the presentation service from becoming a
second process supervisor. Portal records what was requested and what Agency
reported; Agency remains responsible for proving which live process owns the
terminal.

## When to Apply

- A web console mutates a live agent, shell, deployment, device, or other
  external system where the HTTP response can be lost independently of the
  side effect.
- A target can move while retaining a stable logical identity.
- Retrying an ambiguous operation can duplicate work or affect the wrong target.
- User-supplied executable artifacts need one narrow callback without inheriting
  the operator's ambient session.

## Verification

Use different evidence for each boundary:

- Database tests for compare-and-set claims, append-only attempts, generic-pull
  isolation, concurrent duplicate requests, idempotency conflicts, and
  once-only restart recovery.
- Web tests for cookie authentication, key persistence, archived controls,
  bridge exceptions, and explicit confirmation before retrying `unknown`.
- Capability tests proving a view can submit its own verdict but receives 401
  from Agents mutations and 404 for unowned media.
- A real disposable tmux integration test that swaps pane positions, delivers to
  the stable target only, and proves a foreground shell receives no input.
- Browser screenshots or recordings for the operator-visible state labels and
  retry affordances. Unit tests cannot prove that a receipt is readable.

## Related

- [`2026-07-08-browser-writes-need-cookie-twins.md`](../2026-07-08-browser-writes-need-cookie-twins.md) — operator browser writes without bearer-token leakage.
- [`2026-07-08-testclient-needs-browser-header-proxies.md`](../2026-07-08-testclient-needs-browser-header-proxies.md) — policy checks are useful but do not replace rendered evidence.
- `docs/plans/2026-08-05-portal-agent-conversations-and-game-release-plan.html` — feature-specific implementation plan.
- `docs/plans/2026-07-08-007-feat-stream-message-web-ui-plan.md` — the preserved generic pull-queue predecessor.
