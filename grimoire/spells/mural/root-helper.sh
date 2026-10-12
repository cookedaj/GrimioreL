#!/usr/bin/env bash
# System-wide installs for Grimoire MuraL. Run through pkexec (asks for your password):
#   root-helper.sh sddm STAGED_THEME_DIR        install the login theme + make it current
#   root-helper.sh sddm-restore                 put the previous login theme back
#   root-helper.sh plymouth STAGED_THEME_DIR    install the boot theme + rebuild initramfs
#   root-helper.sh plymouth-restore             back to the previous boot theme
#   root-helper.sh sddm-install NAME DIR        install a community login theme as NAME + make it current
#   root-helper.sh plymouth-install NAME DIR    install a community boot theme as NAME + rebuild initramfs
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

case "${1:-}" in
    sddm)
        need_dir "${2:-}" Main.qml
        [[ -f "$SDDM_CONF.grimoire-backup" ]] || cp "$SDDM_CONF" "$SDDM_CONF.grimoire-backup"
        rm -rf "$SDDM_DIR"
        cp -r "$2" "$SDDM_DIR"
        chown -R root:root "$SDDM_DIR"
        chmod -R a+rX,go-w "$SDDM_DIR"
        set_sddm_theme grimoire
        ;;
    sddm-restore)
        prev=$(sed -n '/^\[Theme\]/,/^\[/{s/^Current=//p}' "$SDDM_CONF.grimoire-backup" 2>/dev/null | head -1)
        set_sddm_theme "${prev:-breeze}"
        ;;
    plymouth)
        need_dir "${2:-}" grimoire.plymouth
        [[ -f /var/lib/grimoire-plymouth-previous ]] || readlink -f "$PLY_LINK" > /var/lib/grimoire-plymouth-previous
        rm -rf "$PLY_DIR"
        cp -r "$2" "$PLY_DIR"
        chown -R root:root "$PLY_DIR"
        chmod -R a+rX,go-w "$PLY_DIR"
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
        [[ -f "$SDDM_CONF.grimoire-backup" ]] || cp "$SDDM_CONF" "$SDDM_CONF.grimoire-backup"
        dst="/usr/share/sddm/themes/$2"
        rm -rf "$dst"
        cp -r "$3" "$dst"
        chown -R root:root "$dst"
        chmod -R a+rX,go-w "$dst"
        set_sddm_theme "$2"
        ;;
    plymouth-install)
        valid_name "${2:-}"
        [[ -d "${3:-}" ]] || { echo "not a directory: ${3:-}" >&2; exit 2; }
        file=$(find "$3" -maxdepth 1 -name '*.plymouth' | head -1)
        [[ -n "$file" ]] || { echo "no .plymouth file in $3" >&2; exit 2; }
        [[ -f /var/lib/grimoire-plymouth-previous ]] || readlink -f "$PLY_LINK" > /var/lib/grimoire-plymouth-previous
        dst="/usr/share/plymouth/themes/$2"
        rm -rf "$dst"
        cp -r "$3" "$dst"
        chown -R root:root "$dst"
        chmod -R a+rX,go-w "$dst"
        # community themes often hard-code their install dir; point it at where we put it
        sed -i -E "s#^(ImageDir|ScriptFile)=.*/([^/]+)\$#\1=$dst/\2#; s#^ImageDir=.*#ImageDir=$dst#" "$dst/$(basename "$file")"
        update-alternatives --install "$PLY_LINK" default.plymouth "$dst/$(basename "$file")" 140 >/dev/null
        update-alternatives --set default.plymouth "$dst/$(basename "$file")" >/dev/null
        update-initramfs -u
        ;;
    *)
        sed -n '2,8p' "$0" >&2
        exit 2
        ;;
esac
echo "done"
