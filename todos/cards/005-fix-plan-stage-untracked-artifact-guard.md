# fix: add plan-stage untracked artifact guard

Source: `twf` lesson `825e8279` from card `jAQ8bS6C`; Trello card `Nj29W8GT`
planned-stage handoff.

## Problem

Plan workers can pass `git diff --check` while leaving the plan document
untracked, which makes the Trello comment point at an artifact that will not be
merged.

## Decided approach

Candidate approach for conductor review: make plan-stage checklist text and/or
automation require `git status --porcelain --untracked-files=all` to be empty
after committing the plan document.

## Scope fence

Pipeline checklist/guidance and tests only. Do not rewrite historical plan
documents or move existing cards.

## Acceptance criteria

- Plan-stage guidance names both `git diff --check` and `git status
  --porcelain --untracked-files=all`.
- The status check happens after the plan commit, not before.
- A regression test or fixture proves untracked plan files are caught.

## Verification

Exercise the planned-stage checklist in a temporary card/worktree and confirm an
untracked plan file prevents handoff until committed.
