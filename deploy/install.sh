#!/usr/bin/env bash
# Idempotent install/upgrade for Gallery on this Mac mini.
# Safe to re-run: skips gallery init if config already exists, and
# bootstraps/kickstarts launchd whether or not the daemon is already loaded.
# Installs a system LaunchDaemon (needs sudo) so Portal starts at boot
# without a GUI login.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.appletolye.gallery"
PLIST_SRC="$REPO_DIR/deploy/com.appletolye.gallery.plist"
PLIST_DEST="/Library/LaunchDaemons/$LABEL.plist"
LEGACY_AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "==> Installing gallery (editable) via uv tool"
uv tool install --editable "$REPO_DIR"

echo "==> Ensuring ~/.gallery/ config exists"
if [ ! -f "$HOME/.gallery/config.json" ]; then
    gallery init
else
    echo "config.json already exists, leaving it in place"
fi

echo "==> Retiring the legacy per-login agent, if present"
if [ -f "$LEGACY_AGENT" ]; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    mv "$LEGACY_AGENT" "$LEGACY_AGENT.disabled"
fi

echo "==> Installing launchd daemon to $PLIST_DEST"
TMP_PLIST="$(mktemp)"
sed -e "s#__HOME__#$HOME#g" -e "s#__USER__#$(id -un)#g" "$PLIST_SRC" > "$TMP_PLIST"
sudo install -o root -g wheel -m 644 "$TMP_PLIST" "$PLIST_DEST"
rm -f "$TMP_PLIST"

echo "==> (Re)loading launchd daemon"
sudo launchctl bootout "system/$LABEL" 2>/dev/null || true
pkill -f "$HOME/.local/bin/gallery serve" 2>/dev/null || true
sudo launchctl bootstrap system "$PLIST_DEST"

echo "==> Done. Check status with: sudo launchctl print system/$LABEL"
echo "==> Logs: ~/.gallery/logs/stdout.log and stderr.log"
