#!/usr/bin/env bash
# Install Grimoire for the current user (no sudo). Run it from wherever you downloaded Grimoire; run it again from a
# newer download to upgrade. Afterwards the download can be moved or deleted.
#   - copies the app into ~/.local/share/grimoire/app (everything runs from there)
#   - links the commands into ~/.local/bin and adds the app-menu entry, plus VaultL's (each spell's Install button
#     on the home page adds its own; ./install.sh --all adds every spell's launcher)
#   - copies the MuraL wallpaper plugin into Plasma
#   - adds the Grimoire Tray menu entry (it starts at login only once you turn that on)
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

# 2. commands: point every grimoire* link at the installed copy; drop links an old install left dangling
mkdir -p "$BIN" "$DATA/applications" "$DATA/plasma/wallpapers" "$DATA/icons/hicolor/scalable/apps"
for cmd in "$APP"/bin/grimoire*; do ln -sfn "$cmd" "$BIN/$(basename "$cmd")"; done
for link in "$BIN"/grimoire*; do
    if [ -L "$link" ] && [ ! -e "$link" ]; then rm -f "$link"; fi
done

# 3. the wallpaper plugin, copied so Plasma doesn't depend on the download
PLUGIN="$DATA/plasma/wallpapers/com.cookedaj.grimoire.mural"
rm -rf "$PLUGIN"
cp -r "$APP/plasma/com.cookedaj.grimoire.mural" "$PLUGIN"
cp "$APP/grimoire/assets/clover5.svg" "$DATA/icons/hicolor/scalable/apps/grimoire.svg"

cat > "$DATA/applications/grimoire.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Grimoire
GenericName=Personal tools
Comment=Your spells: MuraL wallpapers and more
Exec=$BIN/grimoire %u
Icon=grimoire
Categories=Utility;Settings;
StartupWMClass=grimoire
Actions=mural;sightc;vaultl;optimizel;systeml;

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
EOF

# the tray icon's menu entry; it starts at login only once you turn that on (its autostart runs $BIN/grimoire-tray)
cat > "$DATA/applications/grimoire-tray.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Grimoire Tray
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
update-desktop-database "$DATA/applications" 2>/dev/null || true

case ":$PATH:" in *":$BIN:"*) ;; *) echo "Note: add $BIN to your PATH to run grimoire from a terminal." ;; esac
echo "Grimoire installed in $APP. Launch it from the app menu or run: grimoire"
