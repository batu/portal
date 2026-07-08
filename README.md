# Gallery

A persistent pick-by-number review hub. Agents post "decision requests" (N
image or video variants) and poll/block for the verdict; a single human
reviews them on a phone-friendly web UI and picks by number.

Runs as one always-on FastAPI + SQLite service on this Mac mini, reachable
over Tailscale only, plus a `gallery` CLI for agents to post requests and
wait for verdicts.

## Install

```bash
uv tool install --editable /Users/base/dev/appletolye/gallery
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

Optional `--manifest path/to/manifest.json` maps original filenames to
per-variant metadata: `{"variant_1.png": {"caption": "warmer tone", "meta": {"model": "x", "cost": 0.02}}}`.

By default the CLI reads `~/.gallery/config.json` for the server URL and
token; set `GALLERY_URL` / `GALLERY_TOKEN` to point at a different server
(e.g. in tests) without touching that file.

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
in project streams, and before/after review. Phase 2/3 items such as `ask`,
`pull`, stream note boxes, coworker/Trello integration, and public/per-stream
auth are planned in `docs/portal-spec.md`; they are not shipped CLI commands
yet.

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
