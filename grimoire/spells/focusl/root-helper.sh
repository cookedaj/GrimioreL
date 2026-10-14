#!/usr/bin/env bash
# Site blocking for Grimoire FocusL. Run through pkexec (asks for your password):
#   root-helper.sh block DOMAIN...    point these sites (and their www.) at 0.0.0.0 / :: in a marked block in /etc/hosts
#   root-helper.sh unblock            remove that block again
# Only the lines between FocusL's two markers are ever written; the rest of the file is left as it was. Before each
# change the file is copied to /var/lib/grimoire-focusl/hosts.bak. Domains are checked (at most 200).
# Testing: FOCUSL_ROOT=<sandbox> works on <sandbox>/etc/hosts and skips the DNS cache flush (pkexec clears the
# environment, so this can't be passed through it).
set -euo pipefail

R="${FOCUSL_ROOT:-}"
HOSTS="$R/etc/hosts"
STATE="$R/var/lib/grimoire-focusl"
BEGIN="# >>> Grimoire FocusL: sites blocked during a focus session (stop the session in FocusL to remove)"
END="# <<< Grimoire FocusL"

[[ -f "$HOSTS" && ! -L "$HOSTS" ]] || { echo "$HOSTS isn't a regular file; not touching it" >&2; exit 3; }

# the file without our block; refuses when the markers are broken, so a half block never eats real lines
without_block() {
    local b e
    b=$(grep -cxF -- "$BEGIN" "$HOSTS" || true)
    e=$(grep -cxF -- "$END" "$HOSTS" || true)
    if [[ "$b" == 0 && "$e" == 0 ]]; then cat "$HOSTS"; return; fi
    if [[ "$b" != 1 || "$e" != 1 ]] || (( $(grep -nxF -- "$BEGIN" "$HOSTS" | cut -d: -f1) > \
                                          $(grep -nxF -- "$END" "$HOSTS" | cut -d: -f1) )); then
        echo "FocusL's block in $HOSTS looks edited by hand; fix or remove it there" >&2; exit 4
    fi
    awk -v b="$BEGIN" -v e="$END" '$0 == b { skip = 1; next } $0 == e { skip = 0; next } !skip' "$HOSTS"
}

# replace the hosts file with stdin, keeping its owner and mode, in one rename
put() {
    local tmp
    mkdir -p "$STATE"
    chmod 755 "$STATE"
    cp -p -- "$HOSTS" "$STATE/hosts.bak"
    tmp=$(mktemp "$R/etc/.hosts.grimoire-focusl.XXXXXX")
    cat > "$tmp"
    chown --reference="$HOSTS" "$tmp"
    chmod --reference="$HOSTS" "$tmp"
    mv -f -- "$tmp" "$HOSTS"
    if [[ -z "$R" ]] && command -v resolvectl >/dev/null; then resolvectl flush-caches 2>/dev/null || true; fi
}

case "${1:-}" in
    block)
        shift
        (( $# >= 1 && $# <= 200 )) || { echo "give 1 to 200 sites" >&2; exit 2; }
        for d in "$@"; do
            [[ "$d" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ && ${#d} -le 200 ]] \
                || { echo "not a site name: $d" >&2; exit 2; }
        done
        rest=$(without_block)
        {
            printf '%s\n' "$rest"
            echo "$BEGIN"
            for d in "$@"; do
                for h in "$d" "www.$d"; do printf '0.0.0.0 %s\n:: %s\n' "$h" "$h"; done
            done
            echo "$END"
        } | put
        ;;
    unblock)
        grep -qxF -- "$BEGIN" "$HOSTS" || exit 0                    # nothing of ours there
        rest=$(without_block)
        printf '%s\n' "$rest" | put
        ;;
    *)
        echo "usage: root-helper.sh block DOMAIN... | unblock" >&2; exit 2 ;;
esac
