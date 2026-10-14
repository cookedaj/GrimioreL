#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Remove Grimoire Linux for the current user (no sudo). With a distro package, run this before removing the package
# to clear the per-user parts (timers, autostart, LaunchL, menu entries a spell's Install button added).
#   ./uninstall.sh            remove the app, its commands, menu entries, wallpaper plugin, LaunchL widget (putting
#                             Kickoff back first if LaunchL replaced it), auto-tidy and alert timers and SightsL and
#                             tray autostart (and stops the tray); keep your settings so a later install picks them up
#   ./uninstall.sh --purge    also move Grimoire's settings, logs and cache to the Trash
# Desktops still showing MuraL's wallpaper are switched to Plasma's own image wallpaper first (MuraL's current
# picture, copied to ~/Pictures/Wallpapers), so no screen goes blank. With --purge, any wallpaper or lock-screen
# picture that lives in Grimoire's data is copied there too before that data goes to the Trash.
# Looks and tweaks you applied (MuraL themes, OptimizeL switches) stay as they are: turn them off in Grimoire first
# if you want them undone.
# GRIMOIRE_UNINSTALL_DRY=1 changes nothing: it only reads, and prints what it would do.
set -euo pipefail
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}"
APP="$DATA/grimoire/app"
BIN="$HOME/.local/bin"
UNITS="$CONFIG/systemd/user"
MURAL_ID="com.cookedaj.grimoire.mural"
PLUGIN="$DATA/plasma/wallpapers/$MURAL_ID"
DRY="${GRIMOIRE_UNINSTALL_DRY:-}"
PURGE=""; if [ "${1:-}" = "--purge" ]; then PURGE=1; fi
PICS="$(xdg-user-dir PICTURES 2>/dev/null || true)"
if [ -z "$PICS" ] || [ "$PICS" = "$HOME" ]; then PICS="$HOME/Pictures"; fi
KEEP="$PICS/Wallpapers"                                          # where in-use pictures are kept

exec 3>&2                                                        # dry-run lines survive callers' 2>/dev/null
run() {                                                          # every change goes through here (dry run prints it)
    if [ -n "$DRY" ]; then echo "[dry] $*" >&3; else "$@"; fi
}
warn() { echo "Warning: $*" >&2; }
py() { python3 -I -c "$@"; }
plasma() {                                                       # evaluateScript; fails when plasmashell isn't there
    qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "$1" 2>/dev/null
}
in_data() { case "$1" in "$DATA/grimoire/"*) return 0;; *) return 1;; esac; }

keep_copy() {
    # Copy a picture out of Grimoire's data into $KEEP ("name (2).ext" on clashes, never overwriting) and print
    # the new path. Re-running reuses an identical copy instead of making another.
    local src="$1" name stem ext dest n=2
    name="$(basename "$src")"; stem="${name%.*}"; ext=""
    if [ -n "$stem" ] && [ "$stem" != "$name" ]; then ext=".${name##*.}"; else stem="$name"; fi
    dest="$KEEP/$name"
    while [ -e "$dest" ] || [ -L "$dest" ]; do
        if cmp -s "$src" "$dest"; then echo "$dest"; return; fi
        dest="$KEEP/$stem ($n)$ext"; n=$((n + 1))
    done
    run mkdir -p "$KEEP"
    run cp -p "$src" "$dest"
    echo "$dest"
}

safe_picture() {
    # MuraL's current picture (the first still image of its playlist) somewhere that survives the uninstall;
    # empty = let Plasma use its default.
    local first
    first="$(py 'import json, sys, pathlib
try:
    items = json.loads(pathlib.Path(sys.argv[1]).read_text()).get("items", [])
except (OSError, ValueError, AttributeError):
    items = []
exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".svg", ".avif", ".jxl"}
print(next((p for p in items if isinstance(p, str) and pathlib.Path(p).suffix.lower() in exts
            and pathlib.Path(p).is_file()), ""))' "$CONFIG/grimoire/mural.json")"
    if [ -z "$first" ]; then return; fi
    if in_data "$first"; then keep_copy "$first"; else echo "$first"; fi
}

to_url() { py 'import pathlib, sys; print(pathlib.Path(sys.argv[1]).as_uri())' "$1"; }
from_url() {                                                     # file:// URL -> path ("" for anything else)
    py 'import sys, urllib.parse as u
p = u.urlparse(sys.argv[1])
print(u.unquote(p.path) if p.scheme == "file" else "")' "$1"
}
js() { py 'import json, sys; print(json.dumps(sys.argv[1]))' "$1"; }

KEEP_PLUGIN=""
release_wallpapers() {
    # Switch desktops off MuraL's plugin (and, with --purge, off pictures in Grimoire's data) before they vanish.
    local listing i plugin url path pic="" pic_done="" script="" new out
    if ! listing="$(plasma 'var ds = desktops(), out = [];
for (var i = 0; i < ds.length; i++) {
    var d = ds[i];
    d.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    out.push(d.wallpaperPlugin + "\t" + d.readConfig("Image", ""));
}
print(out.join("\n"));')"; then
        if grep -qs "$MURAL_ID" "$CONFIG/plasma-org.kde.plasma.desktop-appletsrc"; then
            KEEP_PLUGIN=1
            warn "Plasma isn't running, so your desktop can't be switched off MuraL's wallpaper."
            warn "Kept the wallpaper plugin ($PLUGIN) so the desktop doesn't go blank. Pick another wallpaper"
            warn "(right-click the desktop > Desktop and Wallpaper), then move that folder to the Trash."
        fi
        if [ -n "$PURGE" ]; then
            warn "Couldn't check which pictures your desktops use; any from Grimoire's library will be in the Trash."
        fi
        return 0
    fi
    i=0
    while IFS=$'\t' read -r plugin url; do
        new=""
        if [ "$plugin" = "$MURAL_ID" ]; then
            if [ -z "$pic_done" ]; then pic="$(safe_picture)"; pic_done=1; fi
            new="${pic:+$(to_url "$pic")}"
            if [ -n "$pic" ]; then echo "Desktop $((i + 1)): MuraL's wallpaper -> $pic"
            else echo "Desktop $((i + 1)): MuraL's wallpaper -> Plasma's default picture"; fi
        elif [ -n "$PURGE" ] && [ "$plugin" = "org.kde.image" ] && [ -n "$url" ]; then
            path="$(from_url "$url")"
            if [ -n "$path" ] && in_data "$path" && [ -f "$path" ]; then
                path="$(keep_copy "$path")"
                new="$(to_url "$path")"
                echo "Desktop $((i + 1)): its picture is kept as $path"
            fi
        fi
        if [ "$plugin" = "$MURAL_ID" ] || [ -n "$new" ]; then
            script+="set($i, $(js "$new"));"$'\n'
        fi
        i=$((i + 1))
    done <<< "$listing"
    if [ -z "$script" ]; then return 0; fi
    script='function set(i, url) {
    var d = desktops()[i];
    d.wallpaperPlugin = "org.kde.image";
    d.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    if (url) { d.writeConfig("Image", url); d.writeConfig("PreviewImage", url); }
}
'"$script"
    if [ -n "$DRY" ]; then
        printf '[dry] evaluateScript:\n%s' "$script" >&3
    elif ! out="$(plasma "$script")" || [ -n "$out" ]; then
        KEEP_PLUGIN=1
        warn "Plasma refused the wallpaper switch${out:+ ($out)}; kept the wallpaper plugin so nothing goes blank."
    fi
}

release_lock_screen() {
    # --purge: the lock screen's picture usually lives in Grimoire's data (MuraL renders it there).
    local url path
    url="$(kreadconfig6 --file kscreenlockerrc --group Greeter --group Wallpaper --group org.kde.image \
           --group General --key Image 2>/dev/null || true)"
    [ -n "$url" ] || return 0
    path="$(from_url "$url")"
    if [ -n "$path" ] && in_data "$path" && [ -f "$path" ]; then
        path="$(keep_copy "$path")"
        url="$(to_url "$path")"
        for key in Image PreviewImage; do
            run kwriteconfig6 --file kscreenlockerrc --group Greeter --group Wallpaper --group org.kde.image \
                --group General --key "$key" "$url"
        done
        echo "Lock screen: its picture is kept as $path"
    fi
}

# background pieces first
run pkill -f '^(/usr/bin/)?python3 -m grimoire\.spells\.sightc\.overlay' 2>/dev/null || true   # it relaunches via sys.executable
run pkill -f '^(/usr/bin/)?python3 -m grimoire\.tray' 2>/dev/null || true
run pkill -f '^(/usr/bin/)?python3 -m grimoire\.spells\.focusl\.runner' 2>/dev/null || true   # ends a FocusL session cleanly
for unit in grimoire-tidyl grimoire-systeml-alerts grimoire-netl-usage; do   # VaultL's tidy, SystemL's alerts, NetL's usage
    if [ -f "$UNITS/$unit.timer" ]; then
        run systemctl --user disable --now "$unit.timer" 2>/dev/null || true
        run rm -f "$UNITS/$unit.timer" "$UNITS/$unit.service"
        run systemctl --user daemon-reload 2>/dev/null || true
    fi
done
run rm -f "$CONFIG/autostart/grimoire-sightc.desktop" "$CONFIG/autostart/grimoire-tray.desktop" "$CONFIG/autostart/grimoire.desktop"

# wallpapers in use, before their plugin and pictures go
release_wallpapers
if [ -n "$PURGE" ]; then release_lock_screen; fi

# LaunchL: put the old launcher back in the panel first, then remove the widget. If that can't be done (Plasma not
# running, or LaunchL added by hand), the widget stays so the panel isn't left with a broken placeholder.
LAUNCHL="$DATA/plasma/plasmoids/com.cookedaj.grimoire.launchl"
CODE="$APP"                                                      # a distro package's copy when there's no per-user one
if [ ! -d "$CODE/grimoire" ]; then CODE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"; fi
if [ -d "$LAUNCHL" ]; then
    if [ -n "$DRY" ]; then
        echo "[dry] put Kickoff back if LaunchL replaced it, then rm -rf $LAUNCHL" >&3
    elif [ -d "$CODE/grimoire" ] && PYTHONPATH="$CODE" python3 -P -m grimoire.spells.launchl uninstall; then
        rm -rf "$LAUNCHL"
    elif [ ! -d "$CODE/grimoire" ]; then
        rm -rf "$LAUNCHL"
    else
        echo "LaunchL's widget was kept (see above). Remove it later from the panel, then delete $LAUNCHL."
    fi
fi

# commands (only links, never a file someone put there), menu entries and icons Grimoire generated
for link in "$BIN"/grimoire*; do
    if [ -L "$link" ]; then run rm -f "$link"; fi
done
run rm -f "$DATA"/applications/grimoire.desktop "$DATA"/applications/grimoire-*.desktop
run rm -f "$DATA"/icons/hicolor/scalable/apps/grimoire.svg "$DATA"/icons/hicolor/256x256/apps/grimoire-*.png
if [ -z "$KEEP_PLUGIN" ]; then run rm -rf "$PLUGIN"; fi
run rm -rf "$APP"
run update-desktop-database "$DATA/applications" 2>/dev/null || true
run kbuildsycoca6 --noincremental >/dev/null 2>&1 || true

if [ -n "$PURGE" ]; then
    for d in "$CONFIG/grimoire" "$DATA/grimoire" "$CACHE/grimoire"; do
        if [ -e "$d" ]; then run gio trash "$d" 2>/dev/null || echo "Couldn't move $d to the Trash; remove it by hand."; fi
    done
    echo "Grimoire Linux removed, settings moved to the Trash."
else
    echo "Grimoire Linux removed. Settings kept in $CONFIG/grimoire and $DATA/grimoire (./uninstall.sh --purge clears them)."
fi
if [ -n "$DRY" ]; then echo "(dry run: nothing was changed)"; fi
echo "If VaultL opened your folders, pick another file manager in System Settings > Default Applications."
