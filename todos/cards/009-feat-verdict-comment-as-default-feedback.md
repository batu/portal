# feat: offer the predecessor's verdict comment as default --feedback

Source: 2026-07-16 iteration loop — human critiques were retyped by the agent into --feedback.

## Problem

The decide-comment on version N is usually the exact feedback that prompts
version N+1, but the agent must re-type it.

## Decided approach

When `portal post --supersedes req_X` runs without `--feedback` and req_X has
a verdict comment, use that comment as the feedback (with a stderr note), or
prompt/print it as a suggestion.
