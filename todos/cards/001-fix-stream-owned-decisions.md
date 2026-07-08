# fix: make explicit stream decisions stream-owned

Source: `docs/portal-spec.md` Review log; Trello card `GNGHjZ9y`.

## Problem

`portal post --stream <non-legacy>` mirrors a decision request into the explicit
stream, but the authoritative `requests.stream_id` still points at `inbox` or a
legacy `proj-*` stream. Closing the explicit stream therefore does not make that
request read-only.

## Decided approach

Candidate approach for conductor review: make `portal post --stream` set the
request's authoritative stream to the explicit stream while preserving legacy
project-stream compatibility for plain `gallery post` / `POST /api/requests`.

## Scope fence

Portal request creation, stream association, browser archived/read-only behavior,
and tests. Do not change phase-3 Trello watcher behavior on this card.

## Acceptance criteria

- A decision posted with `--stream custom-slug` has `requests.stream_id` for
  `custom-slug`.
- Closing `custom-slug` makes the request page read-only and rejects verdict
  revisions.
- Legacy `gallery post --project ...` still lands in the expected `proj-*`
  stream.
- Stream pages still show mirrored decision posts exactly once.

## Verification

Run focused request/stream tests and the full suite:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q tests/test_e2e_portal.py tests/test_web_streams.py tests/test_streams_api.py
UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q
```
