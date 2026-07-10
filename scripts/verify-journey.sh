#!/usr/bin/env bash
# Desktop visual check for the native /g/<slug> journey page.
#
# Serves Portal on a throwaway data dir, seeds a self-contained wool-crush demo
# (a real image post + a live request + a journey referencing them — no
# production ids required), then screenshots /g/<slug> in headless Chromium at
# 1440x900. Exits non-zero on any failure.
#
# The work sandbox may not be able to launch a browser; in that case the
# conductor runs this. Requires Playwright's chromium browser to be installed
# (uv run --with playwright playwright install chromium).
#
# Usage: scripts/verify-journey.sh [output.png]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SLUG="${SLUG:-wool-crush-demo}"
PORT="${PORT:-8799}"
OUT="${1:-$ROOT/journey-verify.png}"
WORKDIR="$(mktemp -d)"
export GALLERY_DATA_DIR="$WORKDIR/data"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/private/tmp/uv-cache}"

SERVER_PID=""
cleanup() {
  [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null || true
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

echo "==> Seeding self-contained demo journey ($SLUG)"
uv run --extra dev python scripts/seed_journey_demo.py --local --slug "$SLUG"

TOKEN="$(uv run --extra dev python -c 'from gallery import config; print(config.load_config()["token"])')"

echo "==> Serving Portal on 127.0.0.1:$PORT"
uv run --extra dev uvicorn gallery.server:app --host 127.0.0.1 --port "$PORT" >"$WORKDIR/server.log" 2>&1 &
SERVER_PID=$!

echo "==> Waiting for health"
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null

echo "==> Screenshotting /g/$SLUG at 1440x900"
uv run --with playwright python - "$PORT" "$TOKEN" "$SLUG" "$OUT" <<'PY'
import sys
from playwright.sync_api import sync_playwright

port, token, slug, out = sys.argv[1:5]
url = f"http://127.0.0.1:{port}/g/{slug}?token={token}"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(url, wait_until="networkidle")
    assert page.locator(".journey-spine").count() == 1, "journey spine did not render"
    page.screenshot(path=out, full_page=True)
    browser.close()
print(f"wrote {out}")
PY

echo "==> Journey screenshot written to $OUT"
