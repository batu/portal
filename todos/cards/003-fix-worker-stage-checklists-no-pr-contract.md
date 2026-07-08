# fix: align worked-stage checklist with no-PR worker contract

Source: Trello structured handoff `Surprises` and low `Plan-friction` rows on
cards `8OEiwp9u`, `3Dlkoks2`, `A9oMiXGV`, `jAQ8bS6C`, `zKUB2Tnl`,
`TmbwBUm2`, `tHvZgqWB`, `oaxqoVgF`, and `Nj29W8GT`.
Status: Unscheduled draft; not on Trello; requires human conductor scheduling before implementation.

## Problem

The generated `worked` checklist repeatedly asks spawned workers to open a draft
PR and comment the PR URL, while the injected worker contract repeatedly says
not to open PRs because the conductor merges the branch.

## Decided approach

Candidate approach for conductor review: split PR duties out of spawned worker
stage checklists, or make the checklist renderer aware of the no-PR worker
contract for this pipeline profile.

## Scope fence

twf checklist text, stage guidance, and tests in the pipeline tooling project.
Do not change this Gallery product codebase as part of implementing the idea.

## Acceptance criteria

- Spawned worker `worked` checklist no longer requires draft PR creation when
  the worker contract forbids PRs.
- Conductor-owned merge/PR responsibilities remain documented elsewhere.
- Existing cards already in progress are not advanced or moved by the change.
- Regression tests cover the profile-specific checklist text.

## Verification

Run the twf checklist tests in the pipeline tooling repository and manually
inspect `twf status` on a no-PR worker card.
