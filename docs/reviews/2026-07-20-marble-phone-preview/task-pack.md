# Marble Run Phone Preview Task Pack

## Task 1 - Load the current browser build reliably

### Status

passed

### Goal

Ensure existing and fresh browsers load the current release HTML instead of a stale replaced preview.

### Why Now

The public preview can remain stuck on an older broken HTML response for one year.

### User Lens

The phone frame appears not to load even though a clean automated browser can open it.

### Pre-Shot Targets

- Public Marble Run page at desktop width.
- Embedded phone preview after its loading window.

### Repro Setup

- Route: `https://portal.basegamelab.com/games/marble-run`
- Viewport: 1440×1200 and 430×1000
- Fixture: Marble Run `2026.07.20-1`
- State: latest build tab, iPhone 15 Pro preset

### Acceptance Criteria

- Preview HTML is revalidated rather than cached as immutable.
- The iframe URL changes when its stored entry file changes.
- Hashed preview assets remain immutable.

### Expected Visual Result

The current Marble Run menu replaces the loading state without requiring cache clearing.

### Constraints

- Keep preview assets public and sandboxed.
- Preserve immutable caching for hashed assets.

### Out of Scope

- Changing Marble Run gameplay or release content.

### Verification

- Focused game-route tests.
- Public browser capture with no failed requests.

### Spawn Rules

- If the game itself crashes after loading, add a separate runtime task.
- If acceptance is partial, append another iteration.

## Task 2 - Place the phone preview deliberately

### Status

passed

### Goal

Center the phone, its controls, and explanatory copy within the preview column.

### Why Now

The 393 px frame is currently anchored to the left edge of an 815 px column.

### User Lens

The page looks accidental and unbalanced even when the game loads.

### Pre-Shot Targets

- Full desktop release page.
- Full mobile release page.

### Repro Setup

- Route: `https://portal.basegamelab.com/games/marble-run`
- Viewports: 1440×1200 and 430×1000
- Fixture: Marble Run `2026.07.20-1`
- State: latest build tab, iPhone 15 Pro preset

### Acceptance Criteria

- Phone frame is horizontally centered in the media column.
- Controls and disclaimer align with the phone rather than the full loose column.
- Mobile layout stays within the viewport without horizontal clipping.

### Expected Visual Result

The preview reads as one centered device-review unit with balanced whitespace.

### Constraints

- Device preset dimensions must remain real CSS pixels.
- Do not resize the game iframe to fake aspect ratios.

### Out of Scope

- Redesigning release notes or video presentation.

### Verification

- Matched desktop and mobile before/after screenshots.

### Spawn Rules

- Treat broader release-page redesign as a separate task.
- If acceptance is partial, append another iteration.
