#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# System-wide installs for Grimoire MuraL. Run through pkexec (asks for your password):
#   root-helper.sh sddm STAGED_THEME_DIR        install the login theme + make it current
#   root-helper.sh sddm-restore                 put the previous login theme back
#   root-helper.sh plymouth STAGED_THEME_DIR    install the boot theme + rebuild initramfs
#   root-helper.sh plymouth-restore             back to the previous boot theme
#   root-helper.sh sddm-install NAME DIR        install a community login theme as NAME + make it current
#   root-helper.sh plymouth-install NAME DIR    install a community boot theme as NAME + rebuild initramfs
# Theme folders Grimoire installs carry a .grimoire-installed marker; any other existing folder (a system
# theme like breeze, or one you installed yourself) is never replaced.
set -euo pipefail

SDDM_CONF=/etc/sddm.conf
SDDM_DIR=/usr/share/sddm/themes/grimoire
PLY_DIR=/usr/share/plymouth/themes/grimoire
PLY_LINK=/usr/share/plymouth/themes/default.plymouth

valid_name() {
    [[ "$1" =~ ^[A-Za-z0-9._-]+$ && "$1" != "." && "$1" != ".." ]] || { echo "bad theme name: $1" >&2; exit 2; }
}

need_dir() {
    [[ -d "$1" && -f "$1/$2" ]] || { echo "not a staged theme: $1" >&2; exit 2; }
}

# put_theme SRC DST: replace DST with a root-owned copy of SRC, but only if DST is free or ours
put_theme() {
    if [[ -e "$2" && ! -f "$2/.grimoire-installed" ]]; then
        echo "$2 already exists and wasn't installed by Grimoire; not replacing it" >&2
        exit 3
    fi
    rm -rf "$2"
    cp -r "$1" "$2"
    touch "$2/.grimoire-installed"
    chown -R root:root "$2"
    chmod -R a+rX,go-w "$2"
}

set_sddm_theme() {
    if grep -q '^\[Theme\]' "$SDDM_CONF" 2>/dev/null; then
        if sed -n '/^\[Theme\]/,/^\[/p' "$SDDM_CONF" | grep -q '^Current='; then
            sed -i "/^\[Theme\]/,/^\[/{s/^Current=.*/Current=$1/}" "$SDDM_CONF"
        else
            sed -i "/^\[Theme\]/a Current=$1" "$SDDM_CONF"
        fi
    else
        printf '\n[Theme]\nCurrent=%s\n' "$1" >> "$SDDM_CONF"
    fi
}

backup_sddm_conf() {    # once; a missing sddm.conf (theme set only in sddm.conf.d) backs up as empty
    [[ -f "$SDDM_CONF.grimoire-backup" ]] && return
    if [[ -f "$SDDM_CONF" ]]; then cp "$SDDM_CONF" "$SDDM_CONF.grimoire-backup"; else touch "$SDDM_CONF.grimoire-backup"; fi
}

case "${1:-}" in
    sddm)
        need_dir "${2:-}" Main.qml
        backup_sddm_conf
        [[ -d "$SDDM_DIR" ]] && touch "$SDDM_DIR/.grimoire-installed"    # always ours (older installs lack the marker)
        put_theme "$2" "$SDDM_DIR"
        set_sddm_theme grimoire
        ;;
    sddm-restore)
        prev=$(sed -n '/^\[Theme\]/,/^\[/{s/^Current=//p}' "$SDDM_CONF.grimoire-backup" 2>/dev/null | head -1)
        if [[ -n "$prev" ]]; then
            set_sddm_theme "$prev"
        else                    # the theme came from sddm.conf.d (e.g. Kubuntu's): let it apply again
            sed -i '/^\[Theme\]/,/^\[/{/^Current=/d}' "$SDDM_CONF"
        fi
        ;;
    plymouth)
        need_dir "${2:-}" grimoire.plymouth
        [[ -f /var/lib/grimoire-plymouth-previous ]] || readlink -f "$PLY_LINK" > /var/lib/grimoire-plymouth-previous
        [[ -d "$PLY_DIR" ]] && touch "$PLY_DIR/.grimoire-installed"      # always ours (older installs lack the marker)
        put_theme "$2" "$PLY_DIR"
        update-alternatives --install "$PLY_LINK" default.plymouth "$PLY_DIR/grimoire.plymouth" 150 >/dev/null
        update-alternatives --set default.plymouth "$PLY_DIR/grimoire.plymouth" >/dev/null
        update-initramfs -u
        ;;
    plymouth-restore)
        prev=$(cat /var/lib/grimoire-plymouth-previous 2>/dev/null || true)
        [[ -n "$prev" && -f "$prev" ]] || { echo "no previous boot theme recorded" >&2; exit 2; }
        update-alternatives --set default.plymouth "$prev" >/dev/null
        update-initramfs -u
        ;;
    sddm-install)
        valid_name "${2:-}"
        need_dir "${3:-}" Main.qml
        backup_sddm_conf
        dst="/usr/share/sddm/themes/$2"
        put_theme "$3" "$dst"
        set_sddm_theme "$2"
        ;;
    plymouth-install)
        valid_name "${2:-}"
        [[ -d "${3:-}" ]] || { echo "not a directory: ${3:-}" >&2; exit 2; }
        file=$(find "$3" -maxdepth 1 -name '*.plymouth' | head -1)
        [[ -n "$file" ]] || { echo "no .plymouth file in $3" >&2; exit 2; }
        [[ -f /var/lib/grimoire-plymouth-previous ]] || readlink -f "$PLY_LINK" > /var/lib/grimoire-plymouth-previous
        dst="/usr/share/plymouth/themes/$2"
        put_theme "$3" "$dst"
        # community themes often hard-code their install dir; point it at where we put it
        sed -i -E "s#^(ImageDir|ScriptFile)=.*/([^/]+)\$#\1=$dst/\2#; s#^ImageDir=.*#ImageDir=$dst#" "$dst/$(basename "$file")"
        update-alternatives --install "$PLY_LINK" default.plymouth "$dst/$(basename "$file")" 140 >/dev/null
        update-alternatives --set default.plymouth "$dst/$(basename "$file")" >/dev/null
        update-initramfs -u
        ;;
    *)
        sed -n '2,10p' "$0" >&2
        exit 2
        ;;
esac
echo "done"
