---
status: local-verification
subject: Marble editor hub live-service wiring
created: 2026-07-15
---

# Evidence: Marble editor hub live-service wiring

## Observed services

- Phaser Editor 5.0.2 was listening on port `19598` with both the Marble
  project and its `project/plugins` directory passed to the process. The
  command did not include `-public`.
- The GrapesJS editor was listening on loopback port `5203`.
- The saved GrapesJS publication revision was
  `sha256-aee5336e6fec725aa19aa71468a82549ed4fbd320b81d7a081ea9747faf944bf`.
- The saved Phaser publication revision was
  `sha256-5b4c5864b8ecedafc8317d36ddfa0b977cdd2c2214fd71be87169edca81af0b7`.
- The live Portal config contained no `editor_hub` entries, so the production
  hub still rendered disabled placeholders. No live config or process was
  changed by this worktree.

## Portal contract added

Each fixed Marble editor entry can now show independent saved editor and
Preview revisions plus bounded, escaped access instructions. Links retain the
existing absolute HTTP(S), no-userinfo, and no-query-secret validation. The hub
itself retains existing Portal authentication and `Referrer-Policy:
no-referrer`.

Loopback editor links are not public shares. An operator first establishes the
documented SSH port forwards, signs in to Portal, and opens the links from the
authenticated hub. A revision-specific Preview link stays unavailable until a
separate safe endpoint is configured.

## Verification

- Proof-first focused test: the new revision/access contract failed before the
  server and template changes, then passed afterward.
- Focused tests: `33 passed` across `tests/test_editor_hub.py` and
  `tests/test_web_login.py`.
- Full suite: `360 passed` with one pre-existing Starlette/httpx deprecation
  warning.
- Authenticated Playwright checks passed at `1440 x 1000` and `390 x 844`:
  unauthenticated requests redirected to login, both cards rendered the full
  configured revision in their title metadata, both loopback links used
  `noopener noreferrer` and `no-referrer`, and no layout overflow was visible.
- `git diff --check` passed.

## Release boundary

This evidence does not claim a Portal deployment or mutate
`~/.gallery/config.json`. After the Portal branch lands, the operator must:

1. install/restart the reviewed Portal service through the documented release
   procedure;
2. add the two config entries using the current publication revisions;
3. establish the SSH loopback forwards;
4. verify authenticated `/editor-hub` rendering and both editor links;
5. add Preview URLs only when they are real, revision-pinned, and safe.
