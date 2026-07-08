# feat: make uv verification commands sandbox-aware

Source: `twf` lesson `3b565316` from card `8OEiwp9u`; Trello structured
handoff `Surprises` and `Plan-friction` rows on cards `8OEiwp9u` and
`tHvZgqWB`.
Status: Unscheduled draft; not on Trello; requires human conductor scheduling before implementation.

## Problem

Workers keep rediscovering that bare `uv run ...` can fail when uv writes to
`~/.cache/uv`, even though the corrected command is stable.

## Decided approach

Candidate approach for conductor review: add pipeline guidance or a tiny command
wrapper that injects `UV_CACHE_DIR=/private/tmp/uv-cache` for Gallery worker
test and CLI verification commands.

## Scope fence

Pipeline tooling, worker prompt generation, or docs only. Do not change uv
itself and do not hide non-cache test failures.

## Acceptance criteria

- Worker prompts/checklists show the cache-prefixed command for Gallery tests.
- If a wrapper is added, it preserves exit codes and streams command output.
- The cache override is visible in handoffs so failures remain reproducible.

## Verification

Run a representative command through the new guidance/wrapper:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q
```

Also verify a failing pytest still exits nonzero through any wrapper.
