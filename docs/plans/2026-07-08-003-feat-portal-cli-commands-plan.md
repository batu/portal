---
title: "feat: Add Portal CLI commands and gallery alias"
type: feat
status: active
date: 2026-07-08
origin: "trello-card:3Dlkoks2"
trello: "https://trello.com/c/3Dlkoks2"
spec: docs/portal-spec.md
---

# feat: Add Portal CLI commands and gallery alias

## Summary

Add the `portal` console script while keeping `gallery` as an alias, then extend the existing argparse CLI with Portal stream/report verbs and additive `post` flags. The implementation should stay as a thin wrapper over `gallery.client`, preserve old `gallery` command behavior, and use focused CLI tests to prove parser, upload field, and compatibility contracts.

---

## Problem Frame

The Portal HTTP and client helper work has landed, but the installable command is still only `gallery` and the CLI exposes only the legacy request verbs. Agents need the spec section 5 Portal command surface for streams, reports, and before/after decision requests without renaming the Python package or breaking old invocations.

---

## Assumptions

*This plan was authored in pipeline mode without synchronous user confirmation. The items below are agent inferences that fill gaps in the input and should be reviewed before implementation proceeds.*

- The Trello shortlink for frontmatter is `https://trello.com/c/3Dlkoks2`; this twf context exposed the short id but not a richer card URL.
- `gallery/client.py` stream helpers from the streams/posts API card are considered available and should be reused; only a missing thin helper for request posting should justify a `gallery/client.py` edit.
- `portal report` should use `author="portal"` unless implementation discovers an existing project convention for CLI authors; the spec requires an envelope author but the CLI syntax does not expose an `--author` flag.
- `portal stream new <slug>` without `--title` should use the slug as the title, because the API requires a title and the CLI syntax makes title optional.
- Current `gallery/server.py` in this worktree exposes before uploads on `/api/requests` and stream/report posts on `/api/streams/{slug}/posts`, but it does not accept a `stream` form field on `/api/requests`. To stay inside the scope fence, `post --stream` should use the existing two-step API shape: create the legacy request as today, then create a `decision` post in the explicit stream whose body references the returned request id.
- CLI tests may use monkeypatched client calls or a stub server for command-surface assertions, but at least one old-style `gallery post` path should still be exercised without `--stream` so compatibility is not only assumed.

---

## Requirements

### Packaging And Identity

- R1. Add `portal = "gallery.cli:main"` under `[project.scripts]` and keep `gallery = "gallery.cli:main"`.
- R2. Do not rename the `gallery/` package, imports, data directory helpers, or module names.
- R3. Make help text present the tool as `portal`, and ensure both `uv run portal --help` and `uv run gallery --help` exit 0 and list `stream`, `report`, and existing verbs.

### New Portal Commands

- R4. Add `portal stream new <slug> [--kind session|pinned] [--title ...]` as a thin wrapper over the stream-create client helper.
- R5. Add `portal stream close <slug>` as a thin wrapper over the stream-close client helper.
- R6. Add `portal report --stream <slug> --title ... <file.html> [assets...]` as a thin wrapper over stream post creation with `type='report'`.

### Decision Posting Additions

- R7. Extend `post` with optional `--stream <slug>` and optional `--before <img>` while preserving old invocations without those flags.
- R8. Send `--before` as the multipart field named `before`, not as a candidate variant file.
- R9. Add `before-after` to CLI post kind choices so the server-supported request kind is reachable.
- R10. When `post --stream <slug>` is supplied, create the request through the existing request API and then create a stream `decision` post in `<slug>` that references the request id.

### Compatibility And Verification

- R11. Keep `init`, `post`, `wait`, `status`, `list`, and `serve` command behavior compatible for old argument shapes.
- R12. Cover stream new/close, report, `post --stream`, `post --before`, help aliases, and old-style `gallery post` compatibility in `tests/test_cli.py` using the existing monkeypatch/stub style.
- R13. Verify with the full test suite and the explicit help command required by the card.

---

## Card Acceptance Criteria Trace

| Card acceptance criterion | Requirements | Units | Test scenario anchor |
|---|---|---|---|
| `uv run portal --help` and `uv run gallery --help` exit 0 and list new verbs | R1, R3 | U1, U4 | U4 help alias test plus final command verification |
| `stream new/close` covered by CLI tests | R4, R5, R12 | U2, U4 | U4 stream parser/client-call tests |
| `report` covered by CLI tests | R6, R12 | U2, U4 | U4 report multipart/client-call test |
| `post --stream` and `post --before` covered by CLI tests | R7, R8, R9, R10, R12 | U3, U4 | U4 post request plus stream-decision routing tests |
| Old-style `gallery post` without `--stream` still succeeds | R7, R11, R12 | U3, U4 | U4 compatibility test asserting no stream attach call happens |

---

## Scope Boundaries

- No rename of `gallery/`, Python imports, configuration module names, media paths, or data directories.
- No `server.py` changes on this card.
- No stream web pages, browser twin routes, note boxes, ask/pull, or phase-2 message behavior.
- No public auth, per-stream tokens, tunnel setup, launchd/deploy changes, or README edits.
- No broad CLI framework migration; keep `argparse`.
- No `requests` dependency or non-stdlib HTTP client.
- No speculative report schema beyond what the existing stream-post API accepts.

### Deferred to Follow-Up Work

- First-class explicit-stream request creation that avoids the current legacy dual-write side effect can be considered in a later server/API card; this CLI card should use the existing request-plus-decision-post API shape.
- Phase-2 `portal ask` and `portal pull` remain deferred per `docs/portal-spec.md`.
- Rich report author metadata or configurable author identity can be added later if a consumer needs it.

---

## Context & Research

### Relevant Code and Patterns

- `gallery/cli.py` uses plain `argparse`, one `cmd_*` function per verb, `config.client_config()` for URL/token, `client.GalleryClientError` handling, JSON to stdout, and stderr plus `sys.exit(1)` for client errors.
- `gallery/client.py` is stdlib-only `urllib`. It already has `create_stream`, `close_stream`, `get_stream`, `create_stream_post`, `get_stream_post`, and generic `post_multipart`.
- `gallery/client.py` `post_multipart` accepts both plain `Path` entries and `(field_name, Path)` entries, which is enough for `before` uploads and report files without adding a `requests` dependency.
- `pyproject.toml` currently exposes only `gallery = "gallery.cli:main"`.
- `tests/test_cli.py` uses `monkeypatch.setattr("sys.argv", ...)`, monkeypatched command handlers, and `pytest.raises(SystemExit)` for parser validation.
- `tests/test_streams_api.py` confirms stream helpers and report posts exist at the HTTP/client layer.
- `tests/test_api.py` confirms `/api/requests` accepts a `before` upload and keeps variants 1-based.
- Existing prior plans in `docs/plans/` use `origin: "trello-card:<shortid>"`, `trello: "https://trello.com/c/<shortid>"`, and `spec: docs/portal-spec.md` frontmatter for twf-sourced Portal work.

### Institutional Learnings

- No `docs/solutions/` directory or critical-pattern notes exist in this worktree.
- Board guidance says to run tests with `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q` because the sandbox denies writes to the default uv cache.
- The twf worker contract for this card is one stage only: create the planned-stage artifact, advance once, then hand off.

### External References

- External research is not needed. The plan follows project-local CLI, client, and test patterns plus `docs/portal-spec.md`.

---

## Key Technical Decisions

- Keep `portal` as a console-script alias only: This satisfies the rename decision while preserving the Python package and old `gallery` binary.
- Force argparse help to name the tool `portal`: The card explicitly wants help text to refer to Portal; `gallery --help` can still render `portal` usage while the alias remains executable.
- Use nested subparsers for `stream new` and `stream close`: This fits the spec grammar and avoids inventing flat command names such as `stream-new`.
- Keep CLI handlers thin: Commands should collect files/fields, call `gallery.client`, print the returned JSON, and leave validation beyond basic file existence to the API.
- Use existing multipart support for named uploads: `--before` should prepend or otherwise include `("before", before_path)` separately from candidate files, leaving candidate files on the `files` field.
- Do not map `--stream` to `--project`: That would produce `proj-<stream>` legacy streams and would not satisfy the explicit stream slug contract.
- Implement `post --stream` as a two-step client workflow: create the request through `/api/requests`, then create a `decision` post in the explicit stream with the returned request id. This uses the API card's existing stream-post contract without touching `server.py`.
- Preserve top-level request output for streamed posts: keep the request `id` available at the top level so agents can still pass it to `portal wait`; include stream-post metadata additively if useful.
- Keep `report` result printing as raw JSON: This preserves the current CLI style and ensures soft-cap warnings from the API are not hidden.

---

## Open Questions

### Resolved During Planning

- Should the Python package be renamed from `gallery` to `portal`? No. The card explicitly says binary rename only.
- Should the old `gallery` command be removed? No. It remains a compatibility alias.
- Should phase-2 `ask` and `pull` be included? No. The card only names stream, report, and post additions.
- Should `--before` become a selectable variant? No. It is sent as a separate multipart field and server storage keeps it outside variant rows.
- Should `portal report` crawl or import asset directories automatically? No. It posts only the explicit HTML file and explicit assets provided as arguments.

### Deferred to Implementation

- Exact JSON shape for `post --stream` output: Keep the request creation response fields, especially top-level `id`, and add stream-post details only in an additive way.
- Exact failure behavior if request creation succeeds but stream-post creation fails: Surface the client error and note that the request may already exist in the legacy inbox/project stream; do not attempt rollback through server internals.
- Exact helper factoring in `gallery/cli.py`: Keep it local and small; add a helper only if it reduces duplication between `post`, `report`, and stream commands.
- Exact test transport for CLI coverage: Prefer monkeypatched `gallery.client` calls for fast unit coverage; use `TestClient` only where it can prove the intended contract without forcing `server.py` changes.

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```text
pyproject.toml
  gallery -> gallery.cli:main
  portal  -> gallery.cli:main

gallery.cli main()
  argparse(prog="portal")
    init/post/wait/status/list/serve   existing verbs
    stream new/close                   new nested verbs
    report                             new stream report verb

handlers
  stream new/close -> gallery.client stream helpers -> JSON stdout
  report           -> create_stream_post(type="report") -> JSON stdout
  post             -> post_multipart("/api/requests", fields + files + optional before)
                  -> if --stream: create_stream_post(type="decision", body={request_id})
                  -> JSON stdout with request id preserved
```

The CLI should remain a transport shim. It should not duplicate server validation, mutate streams directly in the DB, or synthesize alternate project names to approximate stream routing.

---

## Implementation Units

- U1. **Add the Portal console-script alias and help identity**

**Goal:** Make `portal` executable while preserving `gallery`, and make help text present the consolidated tool name.

**Requirements:** R1, R2, R3, R11

**Dependencies:** None

**Files:**
- Modify: `pyproject.toml`
- Modify: `gallery/cli.py`
- Test: `tests/test_cli.py`

**Approach:**
- Add the `portal` script entry beside the existing `gallery` script.
- Keep `gallery.cli:main` as the entry point for both scripts.
- Change the top-level parser identity and description so help text refers to Portal rather than Gallery.
- Keep old subcommands registered with their current argument shapes.

**Patterns to follow:**
- Existing `[project.scripts]` formatting in `pyproject.toml`.
- Existing top-level `argparse.ArgumentParser` construction in `gallery/cli.py`.
- Existing `tests/test_cli.py` help/exit assertions.

**Test scenarios:**
- Happy path: invoking `cli.main()` with `sys.argv=["portal", "--help"]` exits 0 and prints `stream`, `report`, `post`, `wait`, `status`, `list`, and `serve`.
- Happy path: invoking `cli.main()` with `sys.argv=["gallery", "--help"]` exits 0 and prints the same Portal help surface.
- Compatibility: invoking `cli.main()` with no command still prints help and exits 1 as before.
- Packaging: `pyproject.toml` contains both `portal` and `gallery` scripts pointing to `gallery.cli:main`.

**Verification:**
- Both script names are available through `uv run` after the package metadata change.
- Help output names Portal and lists the new command surface.

---

- U2. **Add stream and report CLI commands**

**Goal:** Expose the non-decision Portal publishing verbs as thin wrappers over existing client helpers.

**Requirements:** R4, R5, R6, R11, R12

**Dependencies:** U1

**Files:**
- Modify: `gallery/cli.py`
- Test: `tests/test_cli.py`
- Modify only if a helper is unexpectedly absent: `gallery/client.py`

**Approach:**
- Add a `stream` subparser with `new` and `close` subcommands.
- For `stream new`, parse slug, `--kind` with choices `session`/`pinned`, and optional `--title`; default title to slug when omitted.
- For `stream close`, parse slug and call the close helper.
- Add a top-level `report` subcommand that requires `--stream` and `--title`, then accepts one HTML file plus zero or more asset paths.
- Reuse `_resolve_files` for report input validation so glob and missing-file behavior is consistent with `post`.
- Call `client.create_stream_post` with `type='report'`, title, `author='portal'`, an empty body unless implementation discovers a local convention, and all resolved files.
- Print returned client payloads as JSON, matching existing `post`, `wait`, `status`, and `list --json` behavior.
- Preserve existing client error handling style.

**Patterns to follow:**
- `cmd_post`, `cmd_status`, and `cmd_list` in `gallery/cli.py` for URL/token lookup, client errors, and JSON printing.
- Existing `gallery.client.create_stream`, `close_stream`, and `create_stream_post` helpers.
- `tests/test_streams_api.py` client-helper expectations for stream paths and multipart report uploads.

**Test scenarios:**
- Happy path: `portal stream new alpha --kind pinned --title Alpha` calls the client stream-create helper with slug `alpha`, kind `pinned`, and title `Alpha`.
- Happy path: `portal stream new alpha` defaults kind to `session` and title to `alpha`.
- Happy path: `portal stream close alpha` calls the client stream-close helper with slug `alpha`.
- Happy path: `portal report --stream alpha --title Report report.html asset.png` resolves both files and calls stream post creation with `type='report'`, title `Report`, author `portal`, and the resolved file list.
- Edge case: `portal stream new alpha --kind bogus` exits with argparse code 2.
- Edge case: `portal report --stream alpha --title Report missing.html` exits 1 with the existing missing-file stderr style.
- Error path: a `GalleryClientError` from any new command prints `error: ...` and exits 1.

**Verification:**
- New commands are reachable from the parser, use existing client helpers, and do not affect existing command dispatch.

---

- U3. **Extend `post` with stream, before, and before-after support**

**Goal:** Add Portal decision-request flags without changing old `gallery post` argument behavior.

**Requirements:** R7, R8, R9, R10, R11, R12

**Dependencies:** U1

**Files:**
- Modify: `gallery/cli.py`
- Test: `tests/test_cli.py`

**Approach:**
- Add optional `--stream <slug>` to `post`.
- Add optional `--before <img>` to `post`; validate it as a single existing file separate from candidate files.
- Add `before-after` to the `--kind` choices.
- Keep existing candidate file resolution through `_resolve_files(args.files)`.
- Build request multipart fields exactly as today for old invocations; do not add an inert `stream` form field to `/api/requests`.
- When `--stream` is supplied, first create the request through the existing request API, then call `client.create_stream_post` for the explicit stream with `type='decision'` and a body referencing the returned request id.
- Build multipart files so the before path is sent as `("before", before_path)` and candidate paths remain the normal `files` entries.
- Continue using `/api/requests` for request creation; use `/api/streams/{slug}/posts` only for the explicit stream attachment.
- Keep top-level request response fields in stdout so `id` remains easy for agents to consume; add stream-post details only as additive metadata.
- Preserve JSON stdout and existing client error handling.

**Execution note:** Start with characterization coverage for old-style `gallery post` field/file behavior before adding the new flags.

**Patterns to follow:**
- Existing `cmd_post` field construction and manifest loading in `gallery/cli.py`.
- `gallery/client.py` named multipart tuple support.
- `tests/test_api.py` before upload expectations: before image is not a variant and variants stay 1-based.

**Test scenarios:**
- Compatibility: `gallery post --title t --kind pick-one file.png` sends the same request fields as before, omits `before`, keeps candidate uploads on the `files` field, and does not call stream post creation.
- Happy path: `portal post --stream alpha --title t --kind pick-one file.png` creates the request normally, then creates a `decision` post in stream `alpha` whose body references the returned request id.
- Happy path: `portal post --before before.png --title t --kind before-after after.png` sends the before image as multipart field `before`, sends only `after.png` as a candidate file, and accepts `before-after` as a parser choice.
- Happy path: `portal post --stream alpha --before before.png --title t --kind before-after after.png` combines both additive flags without reordering candidates into variant index 0.
- Edge case: missing `--before` path exits 1 using the same missing-file style as missing candidate files.
- Edge case: invalid kind still exits with argparse code 2.
- Error path: if the client raises `GalleryClientError`, stderr and exit code match existing `post` behavior.
- Integration: a TestClient-backed or stubbed CLI test must prove the chosen real data flow: request creation returns an id and stream post creation receives that id for the explicit stream.

**Verification:**
- Old and new `post` forms are covered by tests.
- No server, DB, or template files are touched for stream routing.

---

- U4. **Consolidate CLI tests and final verification**

**Goal:** Prove the command surface and compatibility criteria with focused tests plus the card's explicit verification command.

**Requirements:** R3, R11, R12, R13

**Dependencies:** U1, U2, U3

**Files:**
- Modify: `tests/test_cli.py`

**Approach:**
- Extend the existing parser-focused test style rather than adding a separate CLI test harness.
- Monkeypatch command handlers where parser shape is the target and monkeypatch `gallery.client`/`config.client_config` where payload construction is the target.
- Keep tests deterministic and file-system-light with `tmp_path` for report/before/candidate files.
- Include one compatibility test for an old invocation that does not use `--stream`.
- Include one packaging/help verification that is strong enough to catch the missing `portal` script alias.

**Patterns to follow:**
- Existing `tests/test_cli.py` use of `monkeypatch.setattr("sys.argv", ...)`, `capsys`, and `pytest.raises(SystemExit)`.
- Existing TestClient style in `tests/test_api.py` only if a real API integration is needed and remains inside the scope fence.

**Test scenarios:**
- Happy path: both aliases expose the same help surface and exit cleanly when invoked with `--help`.
- Happy path: stream, report, and post parser shapes populate expected args.
- Happy path: new commands call expected client helpers and print returned JSON.
- Compatibility: old post invocation still reaches the same `/api/requests` path and candidate file field behavior, with no stream-post attach call.
- Error path: new command client errors produce the same stderr and exit behavior as old commands.

**Verification:**
- Run focused CLI tests first.
- Run `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q`.
- Run `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev portal --help >/dev/null`.
- Run `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev gallery --help >/dev/null`.

---

## System-Wide Impact

- **Interaction graph:** Changes start at console scripts and `gallery/cli.py`, then travel through `gallery.client` to existing HTTP endpoints. Server, DB, templates, and static files are intentionally out of active scope.
- **Error propagation:** New CLI commands should follow existing behavior: `GalleryClientError` becomes one stderr line and process exit 1; argparse validation remains exit 2.
- **State lifecycle risks:** `report` and `post` ultimately create server-side media and DB rows. For `post --stream`, request creation and stream-post attachment are two API calls, so a second-call failure can leave a request visible in the legacy inbox/project stream.
- **API surface parity:** Both `portal` and `gallery` binaries should expose the same verbs, with `gallery` retained only as a compatibility alias.
- **Integration coverage:** Parser/client tests cover CLI construction; a TestClient or stub-server check should cover the request-plus-stream-decision flow for `post --stream`.
- **Unchanged invariants:** Existing commands, old `gallery post` calls, package imports, and server behavior should remain unchanged except for additive flags and help text.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `post --stream` is a two-call workflow, so stream attachment can fail after request creation | Surface the second-call failure clearly, preserve the returned request id when possible, and document the partial-state risk in the implementation handoff. |
| `gallery --help` rendering `portal` usage surprises old users | The card explicitly requires help text to refer to Portal; keep the `gallery` executable alias so old automation still launches. |
| `--before` accidentally becomes a selectable variant | Send it as named multipart field `before` and add tests that candidate files remain separate. |
| Report command hides API warning output | Print raw JSON response like existing commands so warnings remain visible. |
| Parser refactor breaks old commands | Keep edits surgical and add compatibility coverage before broader command additions. |

---

## Documentation / Operational Notes

- No README update is required by this card. If packaging metadata is insufficient for `uv run portal`, record that as implementation friction or a follow-up instead of expanding the diff.
- The implementation handoff should explicitly mention whether the request-plus-stream-decision flow was verified with TestClient or only stubbed at the CLI boundary.

---

## Sources & References

- **Origin card:** [trello-card:3Dlkoks2](https://trello.com/c/3Dlkoks2)
- **Portal spec:** [docs/portal-spec.md](docs/portal-spec.md)
- **Prior API plan:** [docs/plans/2026-07-08-002-feat-streams-posts-http-api-plan.md](docs/plans/2026-07-08-002-feat-streams-posts-http-api-plan.md)
- Related code: [gallery/cli.py](gallery/cli.py)
- Related code: [gallery/client.py](gallery/client.py)
- Related tests: [tests/test_cli.py](tests/test_cli.py)
- Related tests: [tests/test_api.py](tests/test_api.py)
- Related tests: [tests/test_streams_api.py](tests/test_streams_api.py)
