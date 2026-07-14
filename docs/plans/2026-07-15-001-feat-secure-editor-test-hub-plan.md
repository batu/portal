---
title: Secure durable editor-test hub and service links
type: feat
status: implementation-ready
execution: code
origin: https://trello.com/c/JT2t3c2r
trello: https://trello.com/c/JT2t3c2r
---

# Secure durable editor-test hub and service links

## Goal

Give the real-game editor experiment one authenticated Portal landing page while
removing the known query-token and HTTPS-cookie hazards. The hub must be useful
before editor URLs exist: Marble Run's GrapesJS and Phaser Editor entries render
as explicit disabled placeholders, then become hardened HTTP(S) links when the
operator adds them to Portal's existing local config.

## Scope

- Redact secret query parameters from `uvicorn.access` records before handlers
  receive them.
- Stop `portal init` from printing a bearer token in a URL; direct humans to the
  existing passphrase login instead.
- Mark authentication cookies `Secure` when the request arrived through an HTTPS
  reverse proxy, while preserving local HTTP development.
- Add an authenticated `/editor-hub` page with two safe Marble placeholders and
  optional configured editor, revision-preview, reference, and evidence links.
- Document the current public-host threat boundary and deterministic launchd
  deployment procedure without changing the live service, proxy, or Caddy.

## Non-goals

- No production deploy or process restart.
- No Caddy, DNS, tunnel, auth-schema, database, or per-user authorization work.
- No editor implementation and no active URL invented before Fabrika publishes
  one.
- No generic proxying of editor content through Portal.

## Implementation

1. Keep and run the interrupted worker's proof-first tests; confirm failures.
2. Add a small access-log filter, proxy-aware cookie helper, and safe URL/config
   normalization in `gallery/server.py`.
3. Add the hub template and focused styles; link it from Portal navigation.
4. Change initialization output and correct README/spec deployment statements.
5. Run focused tests, the full suite, inspect the diff, and simplify.

## Acceptance

- Access logs retain route and non-secret query values but never raw `token`,
  `access_token`, `api_key`, `key`, or `password` values.
- HTTPS-proxied logins set `Secure`; ordinary HTTP test/local logins do not.
- `/editor-hub` requires existing Portal authentication and returns
  `Referrer-Policy: no-referrer`.
- Default hub shows separate disabled GrapesJS and Phaser Editor Marble cards.
- Only absolute HTTP(S) configured URLs render as links; labels/content remain
  template-escaped and links use `noopener noreferrer`.
- Documentation states that the public hostname exposes a single shared-secret
  service and that interactive views remain trusted-producer-only.
- Focused and full pytest suites pass.
