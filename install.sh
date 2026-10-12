#!/usr/bin/env bash
# Install Grimoire for the current user (no sudo). Re-run any time; it only (re)creates links.
#   - links the launcher into ~/.local/bin
#   - adds an app-menu entry
#   - links the MuraL wallpaper plugin into Plasma
# Requires (apt): python3-pyside6.{qtcore,qtgui,qtwidgets,qtsvg,qtdbus,qtqml,qtquick} python3-pil
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

python3 -c "import PySide6.QtWidgets, PIL" 2>/dev/null || {
    echo "PySide6 or Pillow missing. Run:"
    echo "  sudo apt install python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets python3-pyside6.qtsvg python3-pyside6.qtdbus python3-pyside6.qtqml python3-pyside6.qtquick python3-pil"
    exit 1
}

chmod +x "$DIR/bin/grimoire" "$DIR/bin/grimoire-sightc" "$DIR/bin/grimoire-tidyl" "$DIR/bin/grimoire-filel"
mkdir -p ~/.local/bin ~/.local/share/applications ~/.local/share/plasma/wallpapers ~/.local/share/icons/hicolor/scalable/apps
ln -sfn "$DIR/bin/grimoire" ~/.local/bin/grimoire
ln -sfn "$DIR/bin/grimoire-sightc" ~/.local/bin/grimoire-sightc
ln -sfn "$DIR/bin/grimoire-tidyl" ~/.local/bin/grimoire-tidyl
ln -sfn "$DIR/bin/grimoire-filel" ~/.local/bin/grimoire-filel
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
cat > ~/.local/share/applications/grimoire-filel.desktop <<DESKTOP
[Desktop Entry]
Type=Application
Name=FileL
GenericName=File Manager
Comment=Grimoire's file manager
Exec=$HOME/.local/bin/grimoire-filel %u
Icon=grimoire
Terminal=false
Categories=Utility;System;FileTools;FileManager;
MimeType=inode/directory;
StartupWMClass=grimoire-filel
DESKTOP
update-desktop-database ~/.local/share/applications 2>/dev/null || true
echo "Grimoire installed. Launch it from the app menu or run: grimoire"
