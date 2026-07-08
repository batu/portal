---
title: "Run Uv With Sandbox Cache"
date: "2026-07-08"
module: "workflow"
problem_type: "sandbox-cache"
tags: ["uv", "sandbox", "verification", "workflow"]
---

# Run Uv With Sandbox Cache

## Problem

Workers repeatedly hit sandbox failures when `uv` tried to write under the
default user cache path.

## Root cause

The worker filesystem sandbox allows writes to `/private/tmp` and the worktree,
but denies writes to the default `~/.cache/uv` location.

## Rule

Run project test and CLI verification commands with an explicit writable uv
cache:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q
```

Use the same prefix for `uv run portal ...`, `uv run gallery ...`, or focused
test commands unless the command is known not to invoke uv.

## How to verify

Before handoff, run the required full suite exactly with the cache override:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q
```

If a bare `uv run ...` was accidentally used and failed with a cache write
error, rerun with `UV_CACHE_DIR=/private/tmp/uv-cache` and cite both the failure
and the corrected command in the handoff.

## Sources

- `twf lesson list`: lesson `3b565316`, source card `8OEiwp9u`, "Sandbox
  denies writes to ~/.cache/uv".
- Main Gallery checkout `.twf/lessons.jsonl`: same lesson fired 32 times by the
  time card `Nj29W8GT` was spawned.
- Trello card `8OEiwp9u`, 2026-07-08 worked-stage handoff: `uv` initially used
  an unwritable user cache and the worker reran with the explicit cache.
- Trello card `tHvZgqWB`, 2026-07-08 worked-stage handoff: bare `uv run portal
  ask/pull --help` hit the known cache denial, then passed with the cache
  override.
