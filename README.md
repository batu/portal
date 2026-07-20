# Gallery

A persistent pick-by-number review hub. Agents post "decision requests" (N
image or video variants) and poll/block for the verdict; a single human
reviews them on a phone-friendly web UI and picks by number.

Runs as one always-on FastAPI + SQLite service on this Mac mini, reachable
over Tailscale only, plus a `gallery` CLI for agents to post requests and
wait for verdicts.

## Install

```bash
uv tool install --editable /Users/base/dev/appletolye/portal
gallery init
```

`gallery init` creates `~/.gallery/` (SQLite db, media files, config, logs),
generates a bearer token, and prints the phone URL with the token baked in —
visit it once from your phone to set a cookie.

To run the service persistently under launchd (recommended on the Mac mini):

```bash
./deploy/install.sh
```

This installs the package, runs `gallery init` if needed, and loads
`~/Library/LaunchAgents/com.appletolye.gallery.plist` (RunAtLoad + KeepAlive).
Logs go to `~/.gallery/logs/stdout.log` and `stderr.log`. A reference
systemd user unit for a future Linux move lives at `deploy/gallery.service`
(not used on macOS).

## Config

`~/.gallery/config.json`:

```json
{
  "token": "...",
  "host": "0.0.0.0",
  "port": 8787,
  "url": "http://bases-mac-mini:8787",
  "telegram_bot_token": null,
  "telegram_chat_id": null
}
```

- `GALLERY_DATA_DIR` overrides `~/.gallery` for the whole service (db path,
  media dir, config, logs).
- `GALLERY_URL` / `GALLERY_TOKEN` override the CLI's server URL/token without
  touching config.json (handy for pointing the CLI at a scratch/test server).

### Doorbell notifications (optional)

When a new request is created, the server pings you on Telegram: it POSTs
directly to the Telegram Bot API (stdlib `urllib`, no extra dependency, 10s
timeout, fired from a background thread so it never delays the response). If
`telegram_bot_token` or `telegram_chat_id` is missing, the doorbell is
silently skipped — request creation always succeeds regardless.

To enable it:

1. Message [@BotFather](https://t.me/BotFather) on Telegram, `/newbot`, and
   copy the bot token it gives you. This bot only ever sends messages to
   you — no polling, no other permissions needed.
2. Send your new bot any message, then fetch
   `https://api.telegram.org/bot<token>/getUpdates` to find your numeric
   `chat_id` in the response.
3. Put both values in `~/.gallery/config.json` (`telegram_bot_token`,
   `telegram_chat_id`), or set `GALLERY_TELEGRAM_BOT_TOKEN` /
   `GALLERY_TELEGRAM_CHAT_ID` in the environment the server runs under.

## CLI usage (for agents)

```bash
# Post a decision request. FILES are paths or globs, in display order.
gallery post --title "Pick the best crop" --kind pick-one \
  --project "fabrika/find_the_dog" --context "**pick the sharpest one**" \
  out/variant_*.png
# -> {"id": "req_a1b2c3", "url": "http://bases-mac-mini:8787/r/req_a1b2c3", "variant_count": 3}

# Block until a human decides, or exit 2 on timeout.
gallery wait req_a1b2c3 --timeout 3600 --interval 5
# -> prints the verdict JSON on stdout when decided (exit 0), or exits 2 on timeout

# Check current state without blocking.
gallery status req_a1b2c3

# List requests.
gallery list --open --project fabrika/find_the_dog
gallery list --json
```

`kind` is one of `pick-one`, `pick-many`, `rank`, `approve`, `comment`.

### Iteration loops (new version of an existing request)

When a request is a revision of an earlier one, never post it standalone.
Post with `--supersedes` and `--feedback` so the whole loop stays one chain:

```bash
portal post --title "Ball styles (v2)" --kind pick-one --stream my-loop \
  --supersedes req_old --feedback "Sheen looked bad — removed; added toon" \
  --author "claude-fable-5" \
  out/*.png
# -> {"id": "req_new", ..., "supersedes": "req_old", "chain_url": ".../c/req_new"}
```

Share the `chain_url` **once**: `/c/<id>` is permanent, resolves from any
request id in the chain, shows one tab per version (old tabs display the
recorded feedback and author), and a plain refresh always opens the latest
version. `--feedback` should quote the human's actual words, so the trail
reads as they said it. `--author` records who/what produced the version
(defaults to `$PORTAL_AUTHOR`; agents should pass their model id).

Attach or fix feedback after the fact (works on superseded requests):

```bash
portal feedback req_old "the highlight dot looked like a cutout"
```

Optional `--manifest path/to/manifest.json` maps original filenames to
per-variant metadata: `{"variant_1.png": {"caption": "warmer tone", "meta": {"model": "x", "cost": 0.02}}}`.

By default the CLI reads `~/.gallery/config.json` for the server URL and
token; set `GALLERY_URL` / `GALLERY_TOKEN` to point at a different server
(e.g. in tests) without touching that file.

## Game releases

Portal publishes permanent, downloadable game releases at `/games/<slug>`.
Each release gets its own version tab, changelog, real-time gameplay video,
share preview, and immutable artifact URL. Release files live outside Git in
`~/.gallery/games/<slug>/<version>/`.

```bash
portal game publish \
  --slug marble-run --title "Marble Run" --version 2026.07.20-1 \
  --description "Guide marbles through handcrafted tracks." \
  --changelog-file CHANGELOG.md --artifact MarbleRun.apk \
  --video gameplay.mp4 --poster preview.jpg
```

The poster must be JPEG; use a 1200x630 frame so WhatsApp and other link
previews display cleanly. Record gameplay at normal speed. A changelog must
describe only the delta from the immediately preceding Portal release. For a
game's first release, say `Initial release` instead of inventing a comparison.

Published release files are immutable. Correct release notes or recoverably
remove a mistaken release with the supported commands:

```bash
portal game changelog --slug marble-run --version 2026.07.20-1 \
  --changelog-file CHANGELOG.md
portal game remove --slug marble-run --version 2026.07.20-1 --yes
```

Removal moves the release directory under `~/.gallery/trash/games/` before
removing its database record. Public game pages, videos, preview images, and
downloads are read-only; publishing and release management require the API
token.

## Portal streams

Portal is the current agent-facing surface of this service. Use the `portal`
CLI for new stream/report work; `gallery` remains a compatibility alias for
the same entry point and prints the same command surface.

Streams are permanent containers with stable URLs at `/s/<slug>`. Producers
push content explicitly: the server never crawls evidence folders or imports
local files on its own. `portal report --stream <slug>` and
`portal post --stream <slug>` auto-create a missing stream as a `session`, so
the common path does not require a separate `stream new`.

```bash
# Optional explicit stream creation. Useful for pinned or named session streams.
portal stream new ftd-menu-redesign-0708 --kind session --title "FTD menu redesign"

# Push a self-contained HTML report plus optional sibling assets.
portal report --stream ftd-menu-redesign-0708 --title "Spacing pass 3" \
  docs/evidence/2026-07-08-grid/grid.html docs/evidence/2026-07-08-grid/assets/*

# Post a decision request into the stream. --before adds the baseline image
# for before/after review; candidate files remain the selectable variants.
portal post --stream ftd-menu-redesign-0708 --title "Pick the strongest pass" \
  --kind before-after --project "fabrika/find_the_dog" --before before.png \
  after-*.png

portal wait req_a1b2c3 --timeout 3600 --interval 5
portal status req_a1b2c3
portal list --open --project fabrika/find_the_dog
portal stream close ftd-menu-redesign-0708
```

`portal post --kind` accepts `pick-one`, `pick-many`, `rank`, `approve`,
`comment`, and `before-after`. Reports and stream-attached decisions use the
same bearer-token config as the older Gallery request flow. Stream post uploads
over the 200 MB soft cap return a warning but are not rejected solely for size.

Phase 1 includes streams, report posts, stream pages, legacy decision requests
in project streams, and before/after review. Phase 2 added `ask`, `pull`, and
stream note boxes. Public/per-stream auth remains planned in
`docs/portal-spec.md`.

### Interactive views (`--kind view`)

A view is a producer-supplied, self-contained HTML page posted as a decision
request. The first `.html` file is the entry; sibling uploads (video, images)
are served next to it with `NN_` order prefixes. View HTML is served
scripts-enabled (unlike reports, which stay script-blocked) and rendered
full-bleed in a sandboxed iframe at `/r/<id>`. The page submits its verdict as
opaque JSON — `POST /r/<id>/decide` with `{"payload": <any JSON>}` and
same-origin credentials — and `portal wait <id>` returns the payload
unchanged. Portal stores view verdicts without interpreting them; the verdict
schema belongs to the view's producer. First producer:
fabrikav2 `tools/video-refs` (the frame-picker).

**Verify views by looking — Playwright is allowed and suggested.** Views are
desktop-web surfaces (Portal is PC-first), so browser screenshots are the
sanctioned verification, before posting and after:

```bash
npx playwright screenshot --viewport-size=1440,900 --wait-for-timeout=3000 \
  "https://portal.basegamelab.com/r/<id>?token=$GALLERY_TOKEN" view.png
```

Render with **realistic data density** (real candidate counts, not a 3-item
fixture) and read the screenshot before shipping — structural tests cannot
catch a layout that only breaks at density. This is the opposite of the
mobile-game rule (browser is never evidence for games); Portal views are web
pages and the browser IS their real environment.

### Portal inbox

The Inbox verbs implement the phase 2 steering/questions protocol from
[`docs/portal-spec.md` §7](docs/portal-spec.md#7-steering-and-questions-phase-2).
They use client-side polling only; route handlers do not long-poll.

```bash
# Ask a blocking human question on a stream. Missing streams are auto-created.
portal ask --stream ftd-menu-redesign-0708 "Which direction should I take?" \
  --timeout 1800 --interval 15
# -> {"reply": "...", "message_id": "...", "elapsed_s": 1.23}

# Pick up the oldest queued human steering note. Default --timeout 0 is one
# non-blocking check.
portal pull --stream ftd-menu-redesign-0708
# -> {"text": "...", "message_id": "..."}
```

`portal ask` posts a `to_human` question, rings the notification hook, then
polls `GET /api/streams/<slug>/messages` for the first unconsumed `to_agent`
reply after the ask timestamp. Human replies are submitted from the stream
page's answer form; the browser uses the cookie-authenticated
`POST /s/<slug>/answer` twin, so rendered forms do not carry `?token=` URLs.
On success `ask` exits `0` with reply JSON. Client/API errors exit `1` with
stderr only. Timeout exits `2` with `{"timeout": true}`. Argparse usage errors
also exit `2` with no branch JSON.

`portal pull` reads the oldest unconsumed `to_agent` message and consumes it
before printing. Human notes are submitted from the stream page's note box
through `POST /s/<slug>/note`; delivery is intended for agent turn boundaries,
not mid-turn interruption. `ask` answers and human notes share this same
`to_agent` queue, so agents should avoid running `pull` against a stream while
an `ask` is waiting unless that queue sharing is intentional. On success `pull`
exits `0` with message JSON. Client/API errors exit `1`; an empty queue exits
`3` with `{"empty": true}`. Argparse usage errors exit `2`. `pull` and browser
note/answer routes require an existing stream; they do not auto-create one.

### Trello watcher for twf cards

`portal trello-watch` is a foreground polling loop for coworker-created Trello
cards. It reads the target twf repo's `agents/config.json` `trello` block,
watches a trigger list, runs one `twf run-card <shortid> --worktree` stage per
tracked card per poll pass, and mirrors pickup, handoff, failure, and stop
states into a per-card Portal stream named `trello-<shortid>`.
This is the phase 3 watcher slice from
[`docs/portal-spec.md` §11.3](docs/portal-spec.md#11-phases).

Required inputs:

- `--repo <path>` points at the twf project to run cards in.
- `TRELLO_API_KEY` and `TRELLO_TOKEN` must be in the watcher environment.
- `GALLERY_URL` / `GALLERY_TOKEN`, or `~/.gallery/config.json`, provide the
  Portal endpoint and bearer token.

```bash
portal trello-watch --repo /Users/base/dev/appletolye/fabrikav2 \
  --list todo --interval 60 --max-stage aesthetics_reviewed
```

`--list` accepts a configured list name/key or a raw Trello list id and defaults
to the repo board's `todo` list. `--max-stage` defaults to
`aesthetics_reviewed`; the watcher stops there, on `blocked_on_batu`, or after
an errored run. It also stops and posts a human message if a tracked card is
closed or moved to an unknown list. It never merges, lands, or advances past
`--max-stage`. Each poll prints one JSON summary line; `--once` exits `75` for
retryable one-shot failures and exits `1` for client/config/API errors.

For a single test poll:

```bash
portal trello-watch --repo /Users/base/dev/appletolye/fabrikav2 --once
```

To leave it running outside an interactive terminal:

```bash
mkdir -p "${GALLERY_DATA_DIR:-$HOME/.gallery}/logs"
nohup portal trello-watch --repo /Users/base/dev/appletolye/fabrikav2 \
  --interval 60 >"${GALLERY_DATA_DIR:-$HOME/.gallery}/logs/trello-watch.log" 2>&1 &
```

Watcher state lives under `${GALLERY_DATA_DIR:-~/.gallery}/trello-watch/`.
Errored cards are skipped until a human inspects or clears that context's state
file. Run only one watcher process per repo/list context; the state file is
written atomically but is not a cross-process lock, so concurrent watchers can
race the same card.

## Phone URL

Visit `http://bases-mac-mini:8787?token=<token>` once (from `gallery init`'s
output or `~/.gallery/config.json`) over Tailscale — this sets a cookie so
you won't need the token in the URL again. The queue page (`/`) lists open
requests newest-first, with a collapsed, searchable "Decided" history below.
Each request opens at `/r/<id>` with a numbered variant grid and
kind-specific controls (tap-to-select, rank-by-tapping-order, approve/reject,
or just a comment box).

## HTTP API

All routes are under `/api` and require `Authorization: Bearer <token>`,
except `GET /api/health` (unauthenticated). Media at `/media/<request_id>/<filename>`
and the web UI accept the token via cookie or a `?token=` query param instead.

| Route | Notes |
|---|---|
| `POST /api/requests` | multipart: `title`, `project`, `kind`, `context`, `manifest` (JSON), file uploads as `files` (order = variant index) |
| `GET /api/requests?status=&project=` | list |
| `GET /api/requests/{id}` | full detail incl. variants + verdict |
| `POST /api/requests/{id}/verdict` | `{"selected": [int], "ratings": {...}?, "comment": str?}`. Re-posting revises the verdict; request stays decided. |
| `GET /media/{request_id}/{filename}` | serves an uploaded variant |
| `GET /api/health` | `{"status", "open_count"}`, no auth |

## Development

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
uv run pytest
```

Tests use `GALLERY_DATA_DIR` pointed at a pytest tmp dir and FastAPI's
`TestClient`, so they never touch `~/.gallery`.
Pipeline learnings: [docs/solutions/](docs/solutions/); draft backlog: [todos/cards/](todos/cards/).
