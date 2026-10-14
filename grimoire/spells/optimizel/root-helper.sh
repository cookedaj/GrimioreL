#!/usr/bin/env bash
# System-wide tweaks for Grimoire OptimizeL. Run through pkexec (one password prompt per batch):
#   root-helper.sh on ID [on|off ID ...]
# Every ID is a fixed, whitelisted change below: a file Grimoire owns (its name has "grimoire-optimizel" in it)
# or the enabled state of named units. Before a tweak changes anything, the old values are saved under
# /var/lib/grimoire-optimizel; "off" puts exactly those back and removes Grimoire's file, so both states
# survive a reboot. Packages a tweak installs are left installed when it's turned off (they sit idle).
# Testing: OPTIMIZEL_ROOT=<sandbox> OPTIMIZEL_DRY=1 writes files under the sandbox and only prints commands
# (pkexec clears the environment, so these can't be passed through it).
set -euo pipefail

R="${OPTIMIZEL_ROOT:-}"
STATE="$R/var/lib/grimoire-optimizel"
MARK="# Grimoire OptimizeL: turn this off in OptimizeL instead of editing it"
mkdir -p "$STATE" "$R/etc/sysctl.d" "$R/etc/modules-load.d" "$R/etc/systemd/journald.conf.d" "$R/etc/apt/apt.conf.d"
chmod 755 "$STATE"

exec 3>&1
run() { if [[ -n "${OPTIMIZEL_DRY:-}" ]]; then echo "would run: $*" >&3; else "$@"; fi; }
warn() { echo "warning: $*" >&2; }

# sysctl_on ID key=value...: save the live values once (or the keys in $SAVE), write our file, apply now
sysctl_on() {
    local id=$1 kv k; shift
    if [[ ! -f "$STATE/$id.sysctl" ]]; then
        for k in ${SAVE:-${*%%=*}}; do k=${k%%=*}; echo "$k=$(sysctl -n "$k")"; done > "$STATE/$id.sysctl"
    fi
    { echo "$MARK"; printf '%s\n' "$@"; } > "$R/etc/sysctl.d/99-grimoire-optimizel-$id.conf"
    for kv in "$@"; do run sysctl -q -w "$kv" || warn "couldn't set $kv now; it applies after a restart"; done
}

sysctl_off() {
    local id=$1 kv
    rm -f "$R/etc/sysctl.d/99-grimoire-optimizel-$id.conf"
    [[ -f "$STATE/$id.sysctl" ]] || return 0
    while IFS= read -r kv; do
        [[ -n "$kv" ]] && { run sysctl -q -w "$kv" || warn "couldn't restore $kv now; it returns after a restart"; }
    done < "$STATE/$id.sysctl"
    rm -f "$STATE/$id.sysctl"
}

# units_save ID unit...: remember each unit's enabled state (once; "not-found" if it isn't installed yet)
units_save() {
    local id=$1 u st; shift
    [[ -f "$STATE/$id.units" ]] && return 0
    for u in "$@"; do
        st=$(systemctl is-enabled "$u" 2>/dev/null || true)
        echo "$u ${st:-not-found}"
    done > "$STATE/$id.units"
}

# units_set ID enable|disable unit...: save their states, then enable or disable them now
units_set() {
    local id=$1 how=$2 u; shift 2
    units_save "$id" "$@"
    for u in "$@"; do
        systemctl cat "$u" >/dev/null 2>&1 || continue          # not installed here
        run systemctl "$how" --now "$u" >/dev/null 2>&1 || warn "couldn't $how $u"
    done
}

units_restore() {
    local id=$1 u st now
    [[ -f "$STATE/$id.units" ]] || return 0
    while read -r u st; do
        systemctl cat "$u" >/dev/null 2>&1 || continue
        now=$(systemctl is-enabled "$u" 2>/dev/null || true)
        if [[ "$st" == enabled && "$now" != enabled ]]; then
            run systemctl enable --now "$u" >/dev/null 2>&1 || warn "couldn't re-enable $u"
        elif [[ "$st" != enabled && "$st" != static && "$now" == enabled ]]; then
            run systemctl disable --now "$u" >/dev/null 2>&1 || warn "couldn't disable $u"
        fi
    done < "$STATE/$id.units"
    rm -f "$STATE/$id.units"
}

# need_pkg PKG: install it if missing (needs the network); returns 1 if that fails, so callers can undo first
need_pkg() {
    dpkg -s "$1" >/dev/null 2>&1 && return 0
    run apt-get install -y --no-install-recommends "$1" >/dev/null || { echo "couldn't install $1" >&2; return 1; }
}

# background maintenance jobs that get a low-priority drop-in ("maint")
MAINT_UNITS="apt-daily.service apt-daily-upgrade.service fwupd-refresh.service e2scrub_all.service \
logrotate.service dpkg-db-backup.service sysstat-collect.service sysstat-summary.service update-notifier-download.service"

zram_conf() {
    printf '%s\n[zram0]\nzram-size = min(ram / 2, 8192)\ncompression-algorithm = zstd\nswap-priority = 100\n' "$MARK"
}

tweak() {
    local how=$1 id=$2
    case "$how $id" in
        "on nmi")        sysctl_on nmi kernel.nmi_watchdog=0 ;;
        "off nmi")       sysctl_off nmi ;;
        "on splitlock")  sysctl_on splitlock kernel.split_lock_mitigate=0 ;;
        "off splitlock") sysctl_off splitlock ;;
        "on vfscache")   sysctl_on vfscache vm.vfs_cache_pressure=50 ;;
        "off vfscache")  sysctl_off vfscache ;;
        "on dirty")      # bytes and ratios exclude each other: restoring the ratios clears the byte limits
                         SAVE="vm.dirty_ratio vm.dirty_background_ratio" \
                         sysctl_on dirty vm.dirty_bytes=268435456 vm.dirty_background_bytes=134217728 ;;
        "off dirty")     sysctl_off dirty ;;
        "on bbr")
            echo tcp_bbr > "$R/etc/modules-load.d/grimoire-optimizel-bbr.conf"
            run modprobe tcp_bbr || warn "couldn't load tcp_bbr now; it loads after a restart"
            sysctl_on bbr net.core.default_qdisc=fq net.ipv4.tcp_congestion_control=bbr ;;
        "off bbr")
            rm -f "$R/etc/modules-load.d/grimoire-optimizel-bbr.conf"
            sysctl_off bbr ;;
        "on zram")
            local conf="$R/etc/systemd/zram-generator.conf"
            if [[ -e "$conf" ]] && ! grep -q "Grimoire OptimizeL" "$conf"; then
                echo "$conf is your own zram setup; not replacing it" >&2; exit 3
            fi
            need_pkg systemd-zram-generator || exit 4
            zram_conf > "$conf"
            SAVE="vm.swappiness vm.page-cluster" sysctl_on zram vm.swappiness=180 vm.page-cluster=0
            run systemctl daemon-reload || warn "couldn't reload systemd"
            run systemctl restart systemd-zram-setup@zram0.service || warn "zram starts after a restart" ;;
        "off zram")
            local conf="$R/etc/systemd/zram-generator.conf"
            if [[ -f "$conf" ]] && grep -q "Grimoire OptimizeL" "$conf"; then
                if [[ -f /usr/lib/systemd/zram-generator.conf ]]; then
                    # an /etc file with no [zram0] overrides the package default, which would turn zram back on
                    echo "$MARK (zram off)" > "$conf"
                else
                    rm -f "$conf"
                fi
            fi
            sysctl_off zram
            run systemctl stop systemd-zram-setup@zram0.service || warn "zram goes away after a restart"
            run systemctl daemon-reload || warn "couldn't reload systemd" ;;
        "on earlyoom")   # the saved state is what marks it On, so it goes again if the install fails
            units_save earlyoom earlyoom.service
            need_pkg earlyoom || { rm -f "$STATE/earlyoom.units"; exit 4; }
            units_set earlyoom enable earlyoom.service ;;
        "off earlyoom")  units_restore earlyoom ;;
        "on waitonline") units_set waitonline disable NetworkManager-wait-online.service ;;
        "off waitonline") units_restore waitonline ;;
        "on iscsi")      units_set iscsi disable open-iscsi.service iscsid.service iscsid.socket ;;
        "off iscsi")     units_restore iscsi ;;
        "on cupsbrowsed") units_set cupsbrowsed disable cups-browsed.service ;;
        "off cupsbrowsed") units_restore cupsbrowsed ;;
        "on journal")
            printf '%s\n[Journal]\nSystemMaxUse=200M\n' "$MARK" > "$R/etc/systemd/journald.conf.d/99-grimoire-optimizel.conf"
            run systemctl restart systemd-journald || warn "couldn't restart the journal; the limit applies after a restart"
            run journalctl --vacuum-size=200M >/dev/null 2>&1 || true ;;
        "off journal")
            rm -f "$R/etc/systemd/journald.conf.d/99-grimoire-optimizel.conf"
            run systemctl restart systemd-journald || warn "couldn't restart the journal; it changes after a restart" ;;
        "on aptcache")   # only downloaded .deb files go; apt fetches them again when it needs them
            printf '%s\nAPT::Keep-Downloaded-Packages "false";\nBinary::apt::APT::Keep-Downloaded-Packages "false";\n' \
                "$MARK" > "$R/etc/apt/apt.conf.d/99grimoire-optimizel"
            run apt-get clean || warn "couldn't clear the apt cache now" ;;
        "off aptcache")  rm -f "$R/etc/apt/apt.conf.d/99grimoire-optimizel" ;;
        "on maint")
            local u
            for u in $MAINT_UNITS; do
                mkdir -p "$R/etc/systemd/system/$u.d"
                printf '%s\n[Service]\nNice=19\nCPUWeight=20\n' "$MARK" > "$R/etc/systemd/system/$u.d/grimoire-optimizel.conf"
            done
            run systemctl daemon-reload || warn "couldn't reload systemd; it applies after a restart" ;;
        "off maint")
            local u
            for u in $MAINT_UNITS; do
                rm -f "$R/etc/systemd/system/$u.d/grimoire-optimizel.conf"
                rmdir "$R/etc/systemd/system/$u.d" 2>/dev/null || true
            done
            run systemctl daemon-reload || warn "couldn't reload systemd; it applies after a restart" ;;
        *) echo "unknown tweak: $how $id" >&2; exit 2 ;;
    esac
}

[[ $# -ge 2 && $(( $# % 2 )) -eq 0 ]] || { sed -n '2,9p' "$0" >&2; exit 2; }
while [[ $# -gt 0 ]]; do
    [[ "$1" == on || "$1" == off ]] || { echo "expected on/off, got: $1" >&2; exit 2; }
    tweak "$1" "$2"
    echo "$1 $2 ok"
    shift 2
done
