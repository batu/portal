# Archived scratch-board backlog — 2026-07-22

Cards archived from the project's scratch board todo/ideas columns during the 2026-07-22 clean-slate pass. Full text preserved below; cards remain recoverable from the Trello board archive.

## idea: failed card → audiobook voice-clip reply on Telegram (hear-it-in-the-narrator's-voice) (`4YyJwMe5`)

Blue-sky survivor from the 2026-07-09 conversation — Batu nominated it for the next ideation slot.

When a flashcard review FAILS (Again/Hard) on the Telegram librarian bot, reply with a ~20s Telegram VOICE MESSAGE of the actual audiobook passage the card came from — re-encoding via episodic memory in the narrator's voice, which no generic SRS app can do.

All infrastructure exists after today's merges: cards carry anchor_time; mindweaver has word-aligned audio + /hdd originals; ffmpeg can clip; the bot (nanobot/flashcards) already handles ratings and can send voice notes. Missing piece: a small mindweaver endpoint (bookId + anchor_time ± window -> audio clip) + bot integration + card->book provenance in the vault export (deck names already encode the book).

Depends on: FSRS card (cpz1mnOk) landing; nanobot fixes (reviews logging) help too.
Brainstorm/plan before implementing.

## AUDIT #3: enforce hard streaming limits on Portal uploads (`edTqjIOl`)

Problem: `gallery/server.py:483` uses unbounded `await upload.read()` and the streaming helper writes until EOF; the 200 MB check is post-write warning, not admission control.

Classification: direct-to-work
Pipeline: short
Task-class: security-fix
Depends_on: RXr0rqqA
Touches: gallery/server.py, tests

Approach: enforce declared and observed per-file plus aggregate request limits while streaming to bounded temporary files. Abort early, clean partial files, and return a stable 413-style error. Do not trust Content-Length alone.

Acceptance criteria:
1. Oversized known-length and chunked uploads are rejected before unbounded memory/disk use.
2. Partial files are removed on limit, disconnect, and exception.
3. Boundary-size uploads still work and existing artifact types remain supported.
4. Tests prove memory-safe streaming behavior and aggregate limits.

Verification: focused upload tests, `uv run pytest -q`, `uv run ruff check .`.


## AUDIT #31: correlate portal ask/reply with durable question IDs (`weuwLS7N`)

Problem: `portal ask` associates replies by time proximity rather than a durable question key, so concurrent questions can receive each other's answers.

Classification: needs-plan
Pipeline: short
Task-class: messaging-contract
Depends_on: edTqjIOl
Touches: gallery/server.py, portal CLI/client paths, persistence/schema code, tests, docs
Contract: gallery/question_contract.py (owner: this card); question IDs must round-trip through create, delivery, reply, persistence, and retrieval without timing heuristics.

Approach: generate an opaque question ID, require replies to carry it, persist state transitions, and make duplicate/late/wrong-request replies idempotent or explicitly rejected. Provide a compatibility message for legacy unkeyed replies rather than silently guessing.

Acceptance criteria:
1. Two concurrent asks cannot cross-wire answers.
2. Duplicate, late, unknown, and mismatched replies have deterministic outcomes.
3. CLI/API output exposes the question ID and tests cover full round trips.
4. No production data migration is executed by the worker; include a safe migration plan if storage changes.

Verification: focused ask/reply integration tests, `uv run pytest -q`, `uv run ruff check .`.

