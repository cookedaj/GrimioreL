#!/usr/bin/env bash
# Remove Grimoire for the current user (no sudo).
#   ./uninstall.sh            remove the app, its commands, menu entries, wallpaper plugin, auto-tidy and alert
#                             timers and SightsL and tray autostart (and stops the tray); keep your settings so a
#                             later install picks them up
#   ./uninstall.sh --purge    also move Grimoire's settings, logs and cache to the Trash
# Looks and tweaks you applied (MuraL themes, OptimizeL switches) stay as they are: turn them off in Grimoire first
# if you want them undone.
set -euo pipefail
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}"
APP="$DATA/grimoire/app"
BIN="$HOME/.local/bin"
UNITS="$CONFIG/systemd/user"

# background pieces first
pkill -f '^(/usr/bin/)?python3 -m grimoire\.spells\.sightc\.overlay' 2>/dev/null || true   # it relaunches via sys.executable
pkill -f '^(/usr/bin/)?python3 -m grimoire\.tray' 2>/dev/null || true
for unit in grimoire-tidyl grimoire-systeml-alerts; do              # VaultL's auto-tidy, SystemL's alerts
    if [ -f "$UNITS/$unit.timer" ]; then
        systemctl --user disable --now "$unit.timer" 2>/dev/null || true
        rm -f "$UNITS/$unit.timer" "$UNITS/$unit.service"
        systemctl --user daemon-reload 2>/dev/null || true
    fi
done
rm -f "$CONFIG/autostart/grimoire-sightc.desktop" "$CONFIG/autostart/grimoire-tray.desktop"

# commands (only links, never a file someone put there), menu entries and icons Grimoire generated
for link in "$BIN"/grimoire*; do
    if [ -L "$link" ]; then rm -f "$link"; fi
done
rm -f "$DATA"/applications/grimoire.desktop "$DATA"/applications/grimoire-*.desktop
rm -f "$DATA"/icons/hicolor/scalable/apps/grimoire.svg "$DATA"/icons/hicolor/256x256/apps/grimoire-*.png
rm -rf "$DATA/plasma/wallpapers/com.cookedaj.grimoire.mural" "$APP"
update-desktop-database "$DATA/applications" 2>/dev/null || true
kbuildsycoca6 --noincremental >/dev/null 2>&1 || true

if [ "${1:-}" = "--purge" ]; then
    for d in "$CONFIG/grimoire" "$DATA/grimoire" "$CACHE/grimoire"; do
        if [ -e "$d" ]; then gio trash "$d" 2>/dev/null || echo "Couldn't move $d to the Trash; remove it by hand."; fi
    done
    echo "Grimoire removed, settings moved to the Trash."
else
    echo "Grimoire removed. Settings kept in $CONFIG/grimoire and $DATA/grimoire (./uninstall.sh --purge clears them)."
fi
echo "If VaultL opened your folders, pick another file manager in System Settings > Default Applications."
