#!/usr/bin/env bash
# Idempotent install/upgrade for Gallery on this Mac mini.
# Safe to re-run: skips gallery init if config already exists, and
# bootstraps/kickstarts launchd whether or not the agent is already loaded.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.appletolye.gallery"
PLIST_SRC="$REPO_DIR/deploy/com.appletolye.gallery.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "==> Installing gallery (editable) via uv tool"
uv tool install --editable "$REPO_DIR"

echo "==> Ensuring ~/.gallery/ config exists"
if [ ! -f "$HOME/.gallery/config.json" ]; then
    gallery init
else
    echo "config.json already exists, leaving it in place"
fi

echo "==> Installing launchd plist to $PLIST_DEST"
mkdir -p "$HOME/Library/LaunchAgents"
sed "s#__HOME__#$HOME#g" "$PLIST_SRC" > "$PLIST_DEST"

UID_NUM=$(id -u)
DOMAIN="user/$UID_NUM"

echo "==> (Re)loading launchd agent"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST_DEST"
launchctl kickstart -k "$DOMAIN/$LABEL"

echo "==> Done. Check status with: launchctl print $DOMAIN/$LABEL"
echo "==> Logs: ~/.gallery/logs/stdout.log and stderr.log"
