# feat: add explicit ask/answer correlation

Source: `docs/portal-spec.md` Review log; Trello cards `GNGHjZ9y`,
`oaxqoVgF`, and `tHvZgqWB`.
Status: Unscheduled draft; not on Trello; requires human conductor scheduling before implementation.

## Problem

Answers and human steering notes currently share the unconsumed `to_agent`
message queue. That makes `portal ask` and `portal pull` hard to fully
disambiguate as usage grows.

## Decided approach

Candidate approach for conductor review: add an explicit linked reply model,
message kind, or correlation id so answers target a specific question while
general steering notes remain pullable.

## Scope fence

Message schema/API/client/web UI and migration tests only. Do not implement
full chat, presence, mid-turn injection, or phase-3 Trello watcher behavior.

## Acceptance criteria

- A browser answer can be linked to exactly one pending question.
- `portal ask` returns the correlated answer rather than an unrelated steering
  note.
- `portal pull` still returns unconsumed general steering notes.
- Existing v2 message databases migrate without data loss.

## Verification

Run message API, web-message, CLI, migration, and full tests:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q tests/test_messages_api.py tests/test_web_messages.py tests/test_cli.py tests/test_db_migrations.py
UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q
```
