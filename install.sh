#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Install Grimoire Linux for the current user (no sudo). Run it from wherever you downloaded Grimoire; run it again from a
# newer download to upgrade. Afterwards the download can be moved or deleted. (Distro packages install it system-wide
# instead: see packaging/.)
#   - copies the app into ~/.local/share/grimoire/app (everything runs from there)
#   - links the commands into ~/.local/bin and adds the app-menu entry, plus VaultL's (each spell's Install button
#     on the home page adds its own; ./install.sh --all adds every spell's launcher)
#   - copies the MuraL wallpaper plugin and the LaunchL launcher widget into Plasma (LaunchL only takes Kickoff's
#     place when you ask, on its page)
#   - adds the Grimoire Tray menu entry (it starts at login only once you turn that on)
#   - records the commit it came from (app/INSTALLED.json), so Grimoire can tell when there's an update
# Settings stay in ~/.config/grimoire and ~/.local/share/grimoire; ./uninstall.sh removes the app again.
set -euo pipefail
SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APP="$DATA/grimoire/app"
BIN="$HOME/.local/bin"
SKIP=(--exclude .git --exclude .worktrees --exclude __pycache__ --exclude '*.pyc' --exclude .ENV --exclude CLAUDE.local.md --exclude .claude)

python3 -c "import PySide6.QtWidgets, PIL, psutil" 2>/dev/null || {
    echo "PySide6, Pillow or psutil is missing; see \"Requirements\" in README.md for your distro's packages."
    exit 1
}

# 1. the app itself (skipped when this script is the installed copy, e.g. to refresh the links)
if [ "$SRC" != "$APP" ]; then
    mkdir -p "$APP"
    if command -v rsync >/dev/null; then
        rsync -a --delete --delete-excluded "${SKIP[@]}" "$SRC/" "$APP/"
    else
        find "$APP" -mindepth 1 -delete
        tar -C "$SRC" "${SKIP[@]}" -cf - . | tar -C "$APP" -xf -
    fi
fi
chmod +x "$APP"/bin/grimoire* "$APP"/*.sh

# INSTALLED.json: what this copy was built from, for Grimoire's self-update (grimoire/update.py). The commit the
# updater passes in, else the checkout's HEAD (only a checkout of Grimoire itself, not a repo a download sits in),
# else what an earlier install recorded (when the installed copy refreshes itself), else 'unknown'
SHA="${GRIMOIRE_SOURCE_SHA:-}" DATE="${GRIMOIRE_SOURCE_DATE:-}" DIRTY=0
if [ -z "$SHA" ] && [ -e "$SRC/.git" ] && SHA="$(git -C "$SRC" rev-parse HEAD 2>/dev/null)"; then
    DATE="$(git -C "$SRC" log -1 --format=%cI HEAD 2>/dev/null || true)"
    if [ -n "$(git -C "$SRC" status --porcelain --untracked-files=no 2>/dev/null)" ]; then DIRTY=1; fi
fi
if [ -n "$SHA" ] || [ "$SRC" != "$APP" ] || [ ! -f "$APP/INSTALLED.json" ]; then
    SHA="$SHA" DATE="$DATE" DIRTY="$DIRTY" python3 - "$APP/INSTALLED.json" <<'PY'
import json, os, sys, time
sha = os.environ["SHA"].strip().lower()
ok = len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)
info = {"sha": sha if ok else "unknown", "date": os.environ["DATE"] if ok else "",
        "installed": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
if ok and os.environ["DIRTY"] == "1":
    info["dirty"] = True           # installed from a checkout with uncommitted changes
with open(sys.argv[1], "w") as f:
    json.dump(info, f, indent=1)
PY
fi

# 2. commands: point every grimoire* link at the installed copy; drop links an old install left dangling
mkdir -p "$BIN" "$DATA/applications" "$DATA/plasma/wallpapers" "$DATA/plasma/plasmoids" "$DATA/icons/hicolor/scalable/apps"
for cmd in "$APP"/bin/grimoire*; do ln -sfn "$cmd" "$BIN/$(basename "$cmd")"; done
for link in "$BIN"/grimoire*; do
    if [ -L "$link" ] && [ ! -e "$link" ]; then rm -f "$link"; fi
done

# 3. the wallpaper plugin, copied so Plasma doesn't depend on the download
PLUGIN="$DATA/plasma/wallpapers/com.cookedaj.grimoire.mural"
rm -rf "$PLUGIN"
cp -r "$APP/plasma/com.cookedaj.grimoire.mural" "$PLUGIN"
cp "$APP/grimoire/assets/clover5.svg" "$DATA/icons/hicolor/scalable/apps/grimoire.svg"
# the LaunchL panel widget, the same way (a panel already showing it picks the new version up when Plasma restarts)
LAUNCHL="$DATA/plasma/plasmoids/com.cookedaj.grimoire.launchl"
rm -rf "$LAUNCHL"
cp -r "$APP/plasma/com.cookedaj.grimoire.launchl" "$LAUNCHL"

cat > "$DATA/applications/grimoire.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Grimoire Linux
GenericName=Desktop toolkit
Comment=Black & white tools for KDE Plasma: customization, crosshair, files, system monitor, terminal and more
Keywords=grimoire;customize;theme;wallpaper;ricing;crosshair;file manager;system monitor;terminal;screenshot;
Exec=$BIN/grimoire %u
Icon=grimoire
Categories=Utility;Settings;
StartupWMClass=grimoire
Actions=mural;sightc;vaultl;optimizel;systeml;terminall;

[Desktop Action mural]
Name=MuraL
Exec=$BIN/grimoire mural

[Desktop Action sightc]
Name=SightsL (crosshair)
Exec=$BIN/grimoire sightc

[Desktop Action vaultl]
Name=VaultL (files)
Exec=$BIN/grimoire vaultl

[Desktop Action optimizel]
Name=OptimizeL
Exec=$BIN/grimoire optimizel

[Desktop Action systeml]
Name=SystemL (system monitor)
Exec=$BIN/grimoire systeml

[Desktop Action terminall]
Name=TerminalL (terminal)
Exec=$BIN/grimoire terminall
EOF

# the tray icon's menu entry; it starts at login only once you turn that on (its autostart runs $BIN/grimoire-tray)
cat > "$DATA/applications/grimoire-tray.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Grimoire Linux Tray
GenericName=Tray icon
Comment=Live CPU/RAM in the system tray, plus crosshair, tidy and performance mode
Exec=$BIN/grimoire-tray
Icon=grimoire
Categories=Utility;System;
EOF

# 4. standalone spells: VaultL always (it's the file manager; FileL's and TidyL's old entries become hidden
#    aliases), the rest when installed or with --all. Their menu entries, the auto-tidy timer and SightsL's
#    autostart all run the ~/.local/bin commands linked above.
standalone() { PYTHONPATH="$APP" QT_QPA_PLATFORM=offscreen python3 -m grimoire.standalone "$@"; }
standalone install vaultl >/dev/null
standalone refresh
if [ "${1:-}" = "--all" ]; then standalone install all; fi
# Grimoire's spells and their icons for LaunchL's search
PYTHONPATH="$APP" QT_QPA_PLATFORM=offscreen python3 -P -c "from grimoire.spells.launchl import panel; panel.write_spells()" \
    2>/dev/null || true
update-desktop-database "$DATA/applications" 2>/dev/null || true

case ":$PATH:" in *":$BIN:"*) ;; *) echo "Note: add $BIN to your PATH to run grimoire from a terminal." ;; esac
echo "Grimoire Linux installed in $APP. Launch it from the app menu or run: grimoire"
