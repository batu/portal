# Plan Artifacts Need Porcelain Status

## Problem

Plan-stage workers can create a valid plan file, pass `git diff --check`, and
still leave the artifact untracked or uncommitted.

## Root cause

`git diff --check` checks whitespace in tracked diffs. It does not report new
untracked files, so it cannot prove a newly-created plan artifact will travel
with the branch.

## Rule

After creating and committing a plan artifact, verify the whole worktree state:

```bash
git diff --check
git status --porcelain --untracked-files=all
```

The status output must be empty before the stage handoff. For implementation
stages, use the same check to catch untracked docs, evidence, or generated
artifacts before advancing.

## How to verify

Run `git status --porcelain --untracked-files=all` after the commit that is
supposed to carry the artifact. Empty output is the passing condition. Nonempty
output means either commit the intended file or remove the unintended one.

## Sources

- `twf lesson list`: lesson `825e8279`, source card `jAQ8bS6C`, "`git diff
  --check` does NOT see untracked files".
- Main Gallery checkout `.twf/lessons.jsonl`: same lesson was repeatedly fired
  after card `jAQ8bS6C`.
- Trello card `Nj29W8GT`, planned-stage handoff: explicitly ran
  `git status --porcelain --untracked-files=all` after committing the plan.
