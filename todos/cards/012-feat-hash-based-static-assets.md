# feat: content-hashed static asset URLs

Source: 2026-07-16 session — manual style.css?v=N bumped three times; stale caches read as broken fixes.
Status: Implemented 2026-07-17.

## Problem

Static assets are cache-busted by hand-editing ?v=N in base.html.

## Decided approach

Template helper computing a short content hash per static file at startup
(static_url('style.css') -> /static/style.css?v=<hash8>), replacing manual
version bumps.
