#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Lay Grimoire Linux out for a system-wide distro package under DESTDIR (debian/rules and the AUR PKGBUILD both call
# this, so the two packages are the same tree):
#   packaging/stage.sh DESTDIR [deb|arch|…]
#
#   /usr/share/grimoire-linux/        the app (grimoire/, bin/, plasma/, install.sh, uninstall.sh) + a PACKAGED marker,
#                                     which turns the self-updater off (the package manager updates it)
#   /usr/bin/grimoire*                links to its bin/ launchers (they find the app through readlink -f)
#   /usr/share/applications/          Grimoire Linux, its tray and VaultL (the other spells get theirs from the Install
#                                     button on their home card, per user, as with install.sh)
#   /usr/share/icons/hicolor/         the clover and every spell's tile icon
#   /usr/share/plasma/wallpapers/     MuraL's wallpaper plugin
#   /usr/share/metainfo/              AppStream data, so Discover and other software centers can list it
#   /usr/libexec/grimoire-linux/      the root helpers (<spell>-root-helper.sh, 0755, root-owned in the package), the
#                                     only copies pkexec runs (grimoire/roothelper.py); the app tree carries none
#   /usr/share/polkit-1/actions/      their polkit actions, so the password prompt names Grimoire Linux
#
# LaunchL's panel widget isn't installed system-wide: its page installs it for you with kpackagetool6 (from
# /usr/share/grimoire-linux/plasma) together with the spell list its search reads, and swaps it for Kickoff.
# Nothing else per user happens here: timers, autostart entries and hotkeys are written by the app itself when you turn
# them on, and point at /usr/bin. Run /usr/share/grimoire-linux/uninstall.sh as yourself before removing the package
# to clear those.
set -euo pipefail
umask 022
SRC="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
DEST="${1:?usage: stage.sh DESTDIR [kind]}"
KIND="${2:-package}"
USR="$DEST/usr"
APP="$USR/share/grimoire-linux"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/grimoire/__init__.py")"

install -d "$APP" "$USR/bin" "$USR/share/applications" "$USR/share/icons/hicolor/scalable/apps" \
    "$USR/share/icons/hicolor/256x256/apps" "$USR/share/plasma/wallpapers" "$USR/share/metainfo"

# 1. the app, with plain modes (a checkout may carry a 002 umask's group-write bits)
tar -C "$SRC" --exclude=__pycache__ --exclude='*.pyc' -cf - grimoire bin plasma install.sh uninstall.sh README.md LICENSE \
    | tar -C "$APP" --no-same-owner -xf -
find "$APP" -type d -exec chmod 755 {} +
find "$APP" -type f -exec chmod 644 {} +
chmod 755 "$APP"/bin/grimoire* "$APP"/*.sh
rm -f "$APP"/grimoire/spells/*/root-helper.sh           # runtime uses /usr/libexec/grimoire-linux only (step 6)
printf '%s\n' "$KIND" > "$APP/PACKAGED"

# 2. commands
for cmd in "$APP"/bin/grimoire*; do
    ln -sfn "../share/grimoire-linux/bin/$(basename "$cmd")" "$USR/bin/$(basename "$cmd")"
done

# 3. wallpaper plugin and icons
cp -r "$SRC/plasma/com.cookedaj.grimoire.mural" "$USR/share/plasma/wallpapers/"
find "$USR/share/plasma/wallpapers" -type d -exec chmod 755 {} + -o -type f -exec chmod 644 {} +
install -m644 "$SRC/grimoire/assets/clover5.svg" "$USR/share/icons/hicolor/scalable/apps/grimoire.svg"
# each spell's black tile with its line glyph, drawn by the app itself (needs PySide6; offscreen, in a throwaway HOME
# so importing the app doesn't create folders in the builder's home)
VAULT_ICON=grimoire
TMPHOME="$(mktemp -d)"
if HOME="$TMPHOME" XDG_CONFIG_HOME="$TMPHOME/c" XDG_DATA_HOME="$TMPHOME/d" XDG_CACHE_HOME="$TMPHOME/k" \
   QT_QPA_PLATFORM=offscreen PYTHONPATH="$SRC" python3 -I -c '
import sys
sys.path.insert(0, sys.argv[2])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from grimoire.spells import SPELLS
from grimoire.standalone import app_icon
for s in SPELLS:
    assert app_icon(s.icon).save(f"{sys.argv[1]}/grimoire-{s.id}.png")
' "$USR/share/icons/hicolor/256x256/apps" "$SRC" 2>/dev/null; then
    chmod 644 "$USR"/share/icons/hicolor/256x256/apps/*.png
    VAULT_ICON=grimoire-vaultl
else
    echo "stage.sh: PySide6 isn't importable here, so spell icons are left out (menu entries use the clover)" >&2
fi
rm -rf "$TMPHOME"

# 4. menu entries (the same ones install.sh writes per user, running /usr/bin commands)
cat > "$USR/share/applications/grimoire.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Grimoire Linux
GenericName=Desktop toolkit
Comment=Black & white tools for KDE Plasma: customization, crosshair, files, system monitor, terminal and more
Keywords=grimoire;customize;theme;wallpaper;ricing;crosshair;file manager;system monitor;terminal;screenshot;
Exec=grimoire %u
Icon=grimoire
Categories=Utility;Settings;
StartupWMClass=grimoire
Actions=mural;sightc;vaultl;optimizel;systeml;terminall;

[Desktop Action mural]
Name=MuraL
Exec=grimoire mural

[Desktop Action sightc]
Name=SightsL (crosshair)
Exec=grimoire sightc

[Desktop Action vaultl]
Name=VaultL (files)
Exec=grimoire vaultl

[Desktop Action optimizel]
Name=OptimizeL
Exec=grimoire optimizel

[Desktop Action systeml]
Name=SystemL (system monitor)
Exec=grimoire systeml

[Desktop Action terminall]
Name=TerminalL (terminal)
Exec=grimoire terminall
EOF
cat > "$USR/share/applications/grimoire-tray.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Grimoire Linux Tray
GenericName=Tray icon
Comment=Live CPU/RAM in the system tray, plus crosshair, tidy and performance mode
Exec=grimoire-tray
Icon=grimoire
Categories=Utility;System;
EOF
cat > "$USR/share/applications/grimoire-vaultl.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=VaultL
GenericName=File Manager
Comment=Your file manager with tidying built in: places, drives, previews, trash with restore, plus auto-sorted Downloads
Exec=grimoire-vaultl %u
Icon=$VAULT_ICON
Terminal=false
Categories=Utility;System;FileTools;FileManager;
MimeType=inode/directory;
StartupWMClass=grimoire-vaultl
EOF
chmod 644 "$USR"/share/applications/*.desktop

# 5. AppStream
sed "s/@VERSION@/$VERSION/; s/@DATE@/$(date -u +%Y-%m-%d)/" "$SRC/packaging/io.github.cookedaj.grimoire_linux.metainfo.xml" \
    > "$USR/share/metainfo/io.github.cookedaj.grimoire_linux.metainfo.xml"
chmod 644 "$USR/share/metainfo/io.github.cookedaj.grimoire_linux.metainfo.xml"
# 6. root helpers + polkit actions (root ownership comes from dpkg-deb --root-owner-group / makepkg's fakeroot)
LIBEXEC=/usr/libexec/grimoire-linux
POLICY="$USR/share/polkit-1/actions/io.github.cookedaj.grimoire-linux.policy"
python3 -I "$SRC/grimoire/roothelper.py" stage "$DEST$LIBEXEC"
chmod 755 "$DEST$LIBEXEC" "$DEST$LIBEXEC"/*-root-helper.sh
install -d -m755 "$USR/share/polkit-1/actions"
python3 -I "$SRC/grimoire/roothelper.py" policy "$LIBEXEC" > "$POLICY"
chmod 644 "$POLICY"

echo "Staged Grimoire Linux $VERSION ($KIND) in $DEST"
