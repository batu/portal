# perf: auto-transcode GIFs to looping MP4 + lazy-load variant media

Source: 2026-07-16 iteration loop — 22 versions x ~4MB GIFs per card.
Status: Implemented 2026-07-17.

## Problem

GIF-heavy chains are slow on phones; GIFs are ~10x larger than equivalent MP4.

## Decided approach

On upload, transcode image/gif variants to muted looping MP4 (keep original
as fallback), render with <video autoplay loop muted playsinline>; add
loading=lazy / IntersectionObserver for below-the-fold cards.
