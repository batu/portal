#!/usr/bin/env bash
# Idempotent install/upgrade for Gallery on this Mac mini.
# Safe to re-run: skips gallery init if config already exists, and
# bootstraps launchd whether or not the daemon is already loaded.
# Run it as the user Portal should run as (not with sudo); it calls sudo
# itself only for the system LaunchDaemon steps, so Portal starts at boot
# without a GUI login. When run as root, set GALLERY_INSTALL_USER to the
# target user explicitly.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.appletolye.gallery"
PLIST_SRC="$REPO_DIR/deploy/com.appletolye.gallery.plist"
PLIST_DEST="/Library/LaunchDaemons/$LABEL.plist"

if [ "$(id -un)" = "root" ]; then
    if [ -z "${GALLERY_INSTALL_USER:-}" ] || [ "$GALLERY_INSTALL_USER" = "root" ]; then
        echo "Refusing to install as root: Portal would run as root with root's home." >&2
        echo "Run ./deploy/install.sh as your normal user (it calls sudo when needed)," >&2
        echo "or set GALLERY_INSTALL_USER=<user> to name the target user explicitly." >&2
        exit 1
    fi
    TARGET_USER="$GALLERY_INSTALL_USER"
    TARGET_HOME="$(dscl . -read "/Users/$TARGET_USER" NFSHomeDirectory | awk '{print $2}')"
    as_user() { sudo -u "$TARGET_USER" -H env PATH="$TARGET_HOME/.local/bin:$PATH" "$@"; }
else
    TARGET_USER="$(id -un)"
    TARGET_HOME="$HOME"
    as_user() { "$@"; }
fi
TARGET_UID="$(id -u "$TARGET_USER")"
LEGACY_AGENT="$TARGET_HOME/Library/LaunchAgents/$LABEL.plist"

echo "==> Installing gallery (editable) via uv tool for $TARGET_USER"
as_user uv tool install --editable "$REPO_DIR"

echo "==> Ensuring $TARGET_HOME/.gallery/ config exists"
if [ ! -f "$TARGET_HOME/.gallery/config.json" ]; then
    as_user "$TARGET_HOME/.local/bin/gallery" init
else
    echo "config.json already exists, leaving it in place"
fi

echo "==> Retiring the legacy per-login agent, if present"
if [ -f "$LEGACY_AGENT" ]; then
    sudo launchctl bootout "gui/$TARGET_UID/$LABEL" 2>/dev/null || true
    as_user mv "$LEGACY_AGENT" "$LEGACY_AGENT.disabled"
fi

echo "==> Installing launchd daemon to $PLIST_DEST"
TMP_PLIST="$(mktemp)"
sed -e "s#__HOME__#$TARGET_HOME#g" -e "s#__USER__#$TARGET_USER#g" "$PLIST_SRC" > "$TMP_PLIST"
sudo install -o root -g wheel -m 644 "$TMP_PLIST" "$PLIST_DEST"
rm -f "$TMP_PLIST"

echo "==> (Re)loading launchd daemon"
sudo launchctl bootout "system/$LABEL" 2>/dev/null || true
# bootout returns before launchd finishes unloading; bootstrapping too early
# fails with "Bootstrap failed: 5". Wait (up to 10 s) until the label is gone.
for _ in $(seq 1 50); do
    sudo launchctl print "system/$LABEL" >/dev/null 2>&1 || break
    sleep 0.2
done
if sudo launchctl print "system/$LABEL" >/dev/null 2>&1; then
    echo "system/$LABEL is still loaded 10 s after bootout; not bootstrapping." >&2
    exit 1
fi
pkill -u "$TARGET_USER" -f "$TARGET_HOME/.local/bin/gallery serve" 2>/dev/null || true
sudo launchctl bootstrap system "$PLIST_DEST"

echo "==> Done. Check status with: sudo launchctl print system/$LABEL"
echo "==> Logs: $TARGET_HOME/.gallery/logs/stdout.log and stderr.log"
