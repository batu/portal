# feat: warn when posting into a stream with a live predecessor and no --supersedes

Source: 2026-07-16 iteration loop — chain nearly mislinked twice before the one-shot flag.
Status: Implemented 2026-07-17.

## Problem

`portal post --stream X` without `--supersedes` silently creates a standalone
request even when the stream's newest request is still live — breaking the
chain and minting a new URL.

## Decided approach

At post time, if the target stream's newest request is open and same kind,
print a warning naming it ("did you mean --supersedes req_X?"). Warning only;
no behavior change.
