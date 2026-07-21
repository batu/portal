# Device Lab task pack

## Task 1 - Put every playable build inside the selected phone

### Status

passed

### Goal

Turn each release tab into a focused Device Lab where its own web build runs interactively inside the selected phone frame.

### Why Now

The current build tab has a generic device dropdown above an unframed iframe, so it does not implement the selected play-first workflow.

### User Lens

A designer should choose a version and iPhone, then immediately understand that the game they are playing belongs to that build and viewport.

### Pre-Shot Targets

- Latest Marble Run build on desktop.
- Latest Marble Run build at iPhone-sized Portal width.

### Repro Setup

- Route: `/games/marble-run`
- Viewports: 1440x1100 and 430x932
- Fixture: current published Marble Run release
- State: latest build, portrait

### Acceptance Criteria

- Every release with a web bundle renders its own live iframe inside a recognizable phone frame.
- The workspace contains only build tabs, device selection, orientation, and fullscreen controls.
- Changelog, real-time gameplay video, and APK download remain attached to the selected release.
- The layout remains usable at desktop and phone widths.

### Expected Visual Result

The selected build tab leads into a three-part workspace: a device rail, a centered playable phone, and a minimal action rail. Release evidence follows below.

### Constraints

- Preserve Portal's existing visual language and public release URLs.
- Preserve real iframe viewport dimensions and pointer interaction.
- Do not add session, comparison, or issue-reporting flows.

### Out of Scope

- Native APK emulation in the browser.
- Automated screenshots across a device matrix.
- Publishing or changing release artifacts.

### Verification

- Compare desktop and mobile before/after screenshots.
- Run focused game tests and the full test suite.
- Exercise device, orientation, build-tab, and fullscreen controls in a browser.

### Spawn Rules

- If a non-Device-Lab game-page issue appears, record it instead of expanding this task.
- If any acceptance criterion is partial, append another iteration to the journal.
