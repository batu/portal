# feat: push verdicts back to the agent (decide-webhook / notify)

Source: 2026-07-16 marble-run-simplification iteration loop; docs/solutions/2026-07-16-iteration-chains-supersede-with-feedback.md.
Status: Scheduled — implementation started 2026-07-17 (this card tracks scope).

## Problem

When a human decides a request, the posting agent learns about it only by
polling `portal status` or blocking on `portal wait`. In a 22-version loop the
agent never reacted to a verdict in real time.

## Decided approach

Config-driven, best-effort notify hook on verdict creation: an optional
`notify_command` in `~/.gallery/config.json` executed fire-and-forget with the
request id/title/verdict/chain URL (env vars), so any transport works
(telegram-send, twf comment, webhook curl). Never blocks or fails a decide.
