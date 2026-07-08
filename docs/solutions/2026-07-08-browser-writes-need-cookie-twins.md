---
title: "Browser Writes Need Cookie Twins"
date: "2026-07-08"
module: "portal"
problem_type: "browser-auth"
tags: ["browser-auth", "cookies", "token-hygiene", "portal"]
---

# Browser Writes Need Cookie Twins

## Problem

Portal has bearer-token API routes for agents, but browser forms and JavaScript
need to submit human actions without leaking the token through query strings,
form actions, or rendered links.

## Root cause

The API and browser auth surfaces are intentionally different. A browser can
carry the `gallery_token` cookie, while API clients should use `Authorization:
Bearer ...`. Reusing API URLs or `window.location.search` from web UI code risks
token propagation and confusing route contracts.

## Rule

Every browser write path needs a cookie-authenticated twin route with token-free
form actions and token-free JS `fetch` URLs. Keep bearer API routes for CLI and
agent clients. Do not add server-side sleeps or long polls in handlers; polling
belongs in clients.

## How to verify

For each browser write route:

- render the page with a token query once and assert forms/actions do not carry
  `token=`;
- submit through the cookie-auth route, not the bearer API route;
- assert missing stream/request and closed-stream behavior on the browser twin;
- scan rendered artifacts for raw token strings before writing evidence.

## Sources

- `docs/portal-spec.md` section 5, "Browser twins".
- `docs/portal-spec.md` Review log, 2026-07-08 feasibility review entry on
  cookie-auth browser twin routes.
- Trello card `oaxqoVgF`, worked-stage handoff: added cookie-auth
  `/s/{slug}/note` and `/s/{slug}/answer` twins.
- Trello card `oaxqoVgF`, reviewed-stage handoff: security review found
  token/text leak risk from `window.location.search` and default GET forms;
  fixed by token-free twin URLs and explicit POST actions.
- `docs/evidence/2026-07-08-portal-phase1/evidence.md`, token scan and browser
  verdict route hardening.
