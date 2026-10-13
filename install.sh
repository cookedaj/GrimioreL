#!/usr/bin/env bash
# Install Grimoire for the current user (no sudo). Re-run any time; it only (re)creates links.
#   - links the launcher into ~/.local/bin
#   - adds an app-menu entry, plus FileL's (each spell's Install button on the home page adds its own;
#     ./install.sh --all adds every spell's launcher)
#   - links the MuraL wallpaper plugin into Plasma
# Requires (apt): python3-pyside6.{qtcore,qtgui,qtwidgets,qtsvg,qtdbus,qtqml,qtquick} python3-pil
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

python3 -c "import PySide6.QtWidgets, PIL" 2>/dev/null || {
    echo "PySide6 or Pillow missing. Run:"
    echo "  sudo apt install python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets python3-pyside6.qtsvg python3-pyside6.qtdbus python3-pyside6.qtqml python3-pyside6.qtquick python3-pil"
    exit 1
}

chmod +x "$DIR"/bin/grimoire*
mkdir -p ~/.local/bin ~/.local/share/applications ~/.local/share/plasma/wallpapers ~/.local/share/icons/hicolor/scalable/apps
for cmd in "$DIR"/bin/grimoire*; do ln -sfn "$cmd" ~/.local/bin/"$(basename "$cmd")"; done
ln -sfn "$DIR/plasma/com.cookedaj.grimoire.mural" ~/.local/share/plasma/wallpapers/com.cookedaj.grimoire.mural
cp "$DIR/grimoire/assets/clover5.svg" ~/.local/share/icons/hicolor/scalable/apps/grimoire.svg

cat > ~/.local/share/applications/grimoire.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Grimoire
GenericName=Personal tools
Comment=Your spells: MuraL wallpapers and more
Exec=$HOME/.local/bin/grimoire %u
Icon=grimoire
Categories=Utility;Settings;
StartupWMClass=grimoire
Actions=mural;sightc;tidyl;

[Desktop Action mural]
Name=MuraL
Exec=$HOME/.local/bin/grimoire mural

[Desktop Action sightc]
Name=SightsL (crosshair)
Exec=$HOME/.local/bin/grimoire sightc

[Desktop Action tidyl]
Name=TidyL
Exec=$HOME/.local/bin/grimoire tidyl
EOF
# standalone spells: FileL always (it's the default folder handler), the rest when installed or with --all
standalone() { PYTHONPATH="$DIR" QT_QPA_PLATFORM=offscreen python3 -m grimoire.standalone "$@"; }
standalone install filel >/dev/null
standalone refresh
[ "${1:-}" = "--all" ] && standalone install all
update-desktop-database ~/.local/share/applications 2>/dev/null || true
echo "Grimoire installed. Launch it from the app menu or run: grimoire"
