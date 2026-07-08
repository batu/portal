---
title: "Project Stream Slugs Stay Visible And Routable"
date: "2026-07-08"
module: "portal"
problem_type: "stream-routing"
tags: ["streams", "legacy-compatibility", "slugs", "portal"]
---

# Project Stream Slugs Stay Visible And Routable

## Problem

Legacy `gallery post --project ...` requests need to appear in stable Portal
streams without hiding the project identity or creating unroutable overlong
slugs.

## Root cause

The implementation briefly drifted between the visible `proj-<slug>` decision
and a collision-resistant hash suffix for overlong project names. Integration
review accepted the hash suffix only when the normalized route slug would exceed
the contract.

## Rule

Legacy project-derived streams must use the visible `proj-` prefix, normalize
the project name predictably, cap the full route slug at 128 characters, and use
a deterministic 8-hex hash suffix only for overlong normalized project slugs.
The slug must route through both `/s/<slug>` and `/api/streams/{slug}`.

## How to verify

Create requests for normal, empty-normalized, colliding, and overlong project
names. Verify the stored stream slug:

- starts with `proj-` for project-backed requests;
- uses `inbox` for missing project;
- stays at or below the route length cap;
- keeps different overlong projects distinct;
- is retrievable through the browser and API stream routes.

## Sources

- `docs/portal-spec.md` section 3, "Legacy compatibility (defined precisely)".
- `docs/portal-spec.md` Review log, 2026-07-08 integration review entry on
  legacy project-derived stream slugs.
- Trello card `GNGHjZ9y`, worked-stage handoff: fixed bounded legacy
  project-derived stream slugs and documented accepted drift.
- Trello card `GNGHjZ9y`, reviewed-stage handoff: overlong legacy project slugs
  now use a deterministic hash suffix in DB and CLI.
