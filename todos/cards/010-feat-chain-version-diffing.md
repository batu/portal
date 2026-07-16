# feat: compare-with-previous toggle in the chain view

Source: 2026-07-16 iteration loop — most feedback was comparative across versions.

## Problem

The /c/ chain view shows one version at a time; comparing vN to vN-1 means
tab-flipping and remembering.

## Decided approach

Per-tab "compare with previous" mode reusing the existing before/after
side-by-side + toggle machinery, pairing variants by index across versions.
