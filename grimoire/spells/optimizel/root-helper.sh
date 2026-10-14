#!/usr/bin/env bash
# System-wide tweaks for Grimoire OptimizeL. Run through pkexec (one password prompt per batch):
#   root-helper.sh on ID [on|off ID ...]
# Every ID is a fixed, whitelisted change below: a file Grimoire owns (its name has "grimoire-optimizel" in it)
# or the enabled state of named units. No values come from the caller. Before a tweak changes anything, the old
# values are saved under /var/lib/grimoire-optimizel; "off" puts exactly those back and removes Grimoire's file,
# so both states survive a reboot. Packages a tweak installs are left installed when it's turned off.
# Testing: OPTIMIZEL_ROOT=<sandbox> OPTIMIZEL_DRY=1 writes files (and /sys values) under the sandbox and only
# prints commands; OPTIMIZEL_UID stands in for pkexec's caller there (pkexec clears the environment).
set -euo pipefail

R="${OPTIMIZEL_ROOT:-}"
STATE="$R/var/lib/grimoire-optimizel"
MARK="# Grimoire OptimizeL: turn this off in OptimizeL instead of editing it"
mkdir -p "$STATE" "$R/etc/sysctl.d" "$R/etc/modules-load.d" "$R/etc/systemd/journald.conf.d" "$R/etc/apt/apt.conf.d" \
    "$R/etc/tmpfiles.d" "$R/etc/udev/rules.d" "$R/etc/modprobe.d" "$R/etc/default/grub.d" \
    "$R/etc/systemd/system.conf.d" "$R/etc/systemd/user.conf.d" "$R/etc/systemd/system"
chmod 755 "$STATE"

exec 3>&1
run() { if [[ -n "${OPTIMIZEL_DRY:-}" ]]; then echo "would run: $*" >&3; else "$@"; fi; }
warn() { echo "warning: $*" >&2; }
safe() { [[ "$1" =~ ^[A-Za-z0-9+_.:-]+$ ]]; }         # a value we're willing to write back into /sys

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

# sysfs_get PATH: the live value, with "[selected]" picked out of choice lists like "always [madvise] never"
sysfs_get() {
    local v; v=$(cat "$1")
    [[ "$v" =~ \[([^]]+)\] ]] && v=${BASH_REMATCH[1]}
    echo "$v"
}

# sysfs_set PATH VALUE: write it now (into the sandbox when testing)
sysfs_set() {
    if [[ -n "$R" ]]; then mkdir -p "$R$(dirname "$1")"; echo "$2" > "$R$1"; return 0; fi
    echo "$2" > "$1"
}

# sysfs_on ID path=value...: save the live values once, keep ours across boots with tmpfiles.d, apply now
sysfs_on() {
    local id=$1 pv p; shift
    if [[ ! -f "$STATE/$id.sysfs" ]]; then
        for pv in "$@"; do p=${pv%%=*}; echo "$p=$(sysfs_get "$p")"; done > "$STATE/$id.sysfs"
    fi
    { echo "$MARK"; for pv in "$@"; do echo "w ${pv%%=*} - - - - ${pv#*=}"; done; } \
        > "$R/etc/tmpfiles.d/grimoire-optimizel-$id.conf"
    for pv in "$@"; do sysfs_set "${pv%%=*}" "${pv#*=}" || warn "couldn't set ${pv%%=*} now; it applies after a restart"; done
}

sysfs_off() {
    local id=$1 pv p v
    rm -f "$R/etc/tmpfiles.d/grimoire-optimizel-$id.conf"
    [[ -f "$STATE/$id.sysfs" ]] || return 0
    while IFS= read -r pv; do
        p=${pv%%=*}; v=${pv#*=}
        [[ "$p" == /sys/kernel/mm/* ]] && safe "$v" || { warn "skipped odd saved value: $pv"; continue; }
        sysfs_set "$p" "$v" || warn "couldn't restore $p now; it returns after a restart"
    done < "$STATE/$id.sysfs"
    rm -f "$STATE/$id.sysfs"
}

# disks: physical block devices (no loop, zram, device-mapper)
disks() {
    local d
    for d in /sys/block/*; do
        [[ -e "$d/device" && -f "$d/queue/scheduler" ]] && echo "${d##*/}"
    done
}

# udev_on ID ATTR RULES: save every disk's ATTR once, install the rules, apply them now
udev_on() {
    local id=$1 attr=$2 rules=$3 d
    if [[ ! -f "$STATE/$id.udev" ]]; then
        for d in $(disks); do echo "$d $(sysfs_get "/sys/block/$d/queue/$attr")"; done > "$STATE/$id.udev"
    fi
    { echo "$MARK"; echo "$rules"; } > "$R/etc/udev/rules.d/60-grimoire-optimizel-$id.rules"
    run udevadm control --reload || warn "couldn't reload udev; it applies after a restart"
    run udevadm trigger --action=change --subsystem-match=block || warn "couldn't apply now; it applies after a restart"
}

udev_off() {
    local id=$1 attr=$2 d v
    rm -f "$R/etc/udev/rules.d/60-grimoire-optimizel-$id.rules"
    run udevadm control --reload || true
    [[ -f "$STATE/$id.udev" ]] || return 0
    while read -r d v; do
        [[ "$d" =~ ^[a-z0-9]+$ && -e "/sys/block/$d" ]] && safe "$v" || continue
        sysfs_set "/sys/block/$d/queue/$attr" "$v" || warn "couldn't restore $d; it returns after a restart"
    done < "$STATE/$id.udev"
    rm -f "$STATE/$id.udev"
}

# grub_arg ID ARG / grub_off ID: a kernel boot option, added through /etc/default/grub.d (read by update-grub)
grub_arg() {
    local id=$1 arg=$2 f="$R/etc/default/grub.d/99-grimoire-optimizel-$1.cfg"
    command -v update-grub >/dev/null || { echo "this PC doesn't boot with GRUB" >&2; exit 3; }
    printf '%s\nGRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT %s"\n' "$MARK" "$arg" > "$f"
    run update-grub >/dev/null 2>&1 || { rm -f "$f"; echo "update-grub failed; nothing changed" >&2; exit 4; }
}

grub_off() {
    local f="$R/etc/default/grub.d/99-grimoire-optimizel-$1.cfg"
    [[ -f "$f" ]] || return 0
    rm -f "$f"
    run update-grub >/dev/null 2>&1 || warn "update-grub failed; run it once yourself"
}

# modprobe_on ID LINE / modprobe_off ID: a driver option, copied into the initramfs so it applies at boot
modprobe_on() {
    printf '%s\n%s\n' "$MARK" "$2" > "$R/etc/modprobe.d/99-grimoire-optimizel-$1.conf"
    run update-initramfs -u >/dev/null 2>&1 || warn "update-initramfs failed; the option still applies after a restart"
}

modprobe_off() {
    local f="$R/etc/modprobe.d/99-grimoire-optimizel-$1.conf"
    [[ -f "$f" ]] || return 0
    rm -f "$f"
    run update-initramfs -u >/dev/null 2>&1 || warn "update-initramfs failed"
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

# caller: the login name of whoever asked (pkexec sets PKEXEC_UID; tests set OPTIMIZEL_UID inside a sandbox)
caller() {
    local uid="${PKEXEC_UID:-}" name
    [[ -z "$uid" && -n "$R" ]] && uid="${OPTIMIZEL_UID:-}"
    [[ "$uid" =~ ^[0-9]+$ && "$uid" -ge 1000 ]] || { echo "can't tell who asked for this" >&2; exit 5; }
    name=$(getent passwd "$uid" | cut -d: -f1)
    [[ "$name" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "odd user name" >&2; exit 5; }
    echo "$name"
}

# the NVIDIA power limit the card allows at most / runs at now (whole watts)
gpu_limit() {
    local v
    v=$(nvidia-smi --query-gpu="$1" --format=csv,noheader,nounits 2>/dev/null | head -1)
    v=${v%%.*}; v=${v// /}
    [[ "$v" =~ ^[0-9]{2,4}$ ]] || { echo "couldn't read the GPU power limit" >&2; exit 3; }
    echo "$v"
}

# background maintenance jobs that get a low-priority drop-in ("maint")
MAINT_UNITS="apt-daily.service apt-daily-upgrade.service fwupd-refresh.service e2scrub_all.service \
logrotate.service dpkg-db-backup.service sysstat-collect.service sysstat-summary.service update-notifier-download.service \
man-db.service"

zram_conf() {
    printf '%s\n[zram0]\nzram-size = min(ram / 2, 8192)\ncompression-algorithm = zstd\nswap-priority = 100\n' "$MARK"
}

THP=/sys/kernel/mm/transparent_hugepage
IOSCHED_RULES='ACTION=="add|change", SUBSYSTEM=="block", ENV{DEVTYPE}=="disk", KERNEL=="nvme[0-9]*n[0-9]*", ATTR{queue/scheduler}="none"
ACTION=="add|change", SUBSYSTEM=="block", ENV{DEVTYPE}=="disk", KERNEL=="sd[a-z]*|mmcblk[0-9]*", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="mq-deadline"
ACTION=="add|change", SUBSYSTEM=="block", ENV{DEVTYPE}=="disk", KERNEL=="sd[a-z]*", ATTR{queue/rotational}=="1", ATTR{queue/scheduler}="bfq"'
READAHEAD_RULES='ACTION=="add|change", SUBSYSTEM=="block", ENV{DEVTYPE}=="disk", KERNEL=="nvme[0-9]*n[0-9]*|sd[a-z]*|mmcblk[0-9]*", ATTR{queue/rotational}=="0", ATTR{queue/read_ahead_kb}="1024"
ACTION=="add|change", SUBSYSTEM=="block", ENV{DEVTYPE}=="disk", KERNEL=="sd[a-z]*", ATTR{queue/rotational}=="1", ATTR{queue/read_ahead_kb}="4096"'

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
        "on compaction") sysctl_on compaction vm.compaction_proactiveness=0 vm.watermark_boost_factor=0 ;;
        "off compaction") sysctl_off compaction ;;
        "on maxmap")     sysctl_on maxmap vm.max_map_count=1048576 ;;
        "off maxmap")    sysctl_off maxmap ;;
        "on netbuf")     sysctl_on netbuf net.core.rmem_max=33554432 net.core.wmem_max=33554432 \
                             "net.ipv4.tcp_wmem=4096 65536 33554432" net.ipv4.tcp_slow_start_after_idle=0 ;;
        "off netbuf")    sysctl_off netbuf ;;
        "on bbr")
            echo tcp_bbr > "$R/etc/modules-load.d/grimoire-optimizel-bbr.conf"
            run modprobe tcp_bbr || warn "couldn't load tcp_bbr now; it loads after a restart"
            sysctl_on bbr net.core.default_qdisc=fq net.ipv4.tcp_congestion_control=bbr ;;
        "off bbr")
            rm -f "$R/etc/modules-load.d/grimoire-optimizel-bbr.conf"
            sysctl_off bbr ;;
        "on mglru")      sysfs_on mglru /sys/kernel/mm/lru_gen/min_ttl_ms=1000 ;;
        "off mglru")     sysfs_off mglru ;;
        "on thp")        sysfs_on thp "$THP/enabled=always" "$THP/defrag=defer+madvise" "$THP/khugepaged/max_ptes_none=409" ;;
        "off thp")       sysfs_off thp ;;
        "on iosched")    udev_on iosched scheduler "$IOSCHED_RULES" ;;
        "off iosched")   udev_off iosched scheduler ;;
        "on readahead")  udev_on readahead read_ahead_kb "$READAHEAD_RULES" ;;
        "off readahead") udev_off readahead read_ahead_kb ;;
        "on mitigations") grub_arg mitigations mitigations=off ;;
        "off mitigations") grub_off mitigations ;;
        "on nvmeapst")   grub_arg nvmeapst nvme_core.default_ps_max_latency_us=0 ;;
        "off nvmeapst")  grub_off nvmeapst ;;
        "on nvmemclear") modprobe_on nvmemclear "options nvidia NVreg_InitializeSystemMemoryAllocations=0" ;;
        "off nvmemclear") modprobe_off nvmemclear ;;
        "on gpupower")
            local max cur unit="$R/etc/systemd/system/grimoire-optimizel-gpupower.service"
            max=$(gpu_limit power.max_limit); cur=$(gpu_limit power.limit)
            [[ -f "$STATE/gpupower.limit" ]] || echo "$cur" > "$STATE/gpupower.limit"
            printf '%s\n[Unit]\nDescription=Grimoire OptimizeL: NVIDIA power limit at its maximum\nAfter=nvidia-persistenced.service\n\n[Service]\nType=oneshot\nExecStart=/usr/bin/nvidia-smi -pl %s\n\n[Install]\nWantedBy=multi-user.target\n' \
                "$MARK" "$max" > "$unit"
            run systemctl daemon-reload || true
            run systemctl enable grimoire-optimizel-gpupower.service >/dev/null 2>&1 || warn "couldn't enable the power limit at boot"
            run nvidia-smi -pl "$max" >/dev/null || warn "couldn't set the power limit now" ;;
        "off gpupower")
            local old
            run systemctl disable grimoire-optimizel-gpupower.service >/dev/null 2>&1 || true
            rm -f "$R/etc/systemd/system/grimoire-optimizel-gpupower.service"
            run systemctl daemon-reload || true
            old=$(cat "$STATE/gpupower.limit" 2>/dev/null || true)
            if [[ "$old" =~ ^[0-9]{2,4}$ ]]; then run nvidia-smi -pl "$old" >/dev/null || warn "the old limit returns after a restart"; fi
            rm -f "$STATE/gpupower.limit" ;;
        "on gamemode")   # renice needs you in the gamemode group (limits.d gives @gamemode nice -10)
            local user grp=had; user=$(caller)
            [[ -f "$R/etc/security/limits.d/10-gamemode.conf" || -f /etc/security/limits.d/10-gamemode.conf ]] \
                || { echo "GameMode isn't installed" >&2; exit 3; }
            if [[ ! -f "$STATE/gamemode.group" ]]; then
                getent group gamemode >/dev/null || grp=created
                if id -nG "$user" | tr ' ' '\n' | grep -qx gamemode; then echo "$user member $grp"; else echo "$user added $grp"; fi \
                    > "$STATE/gamemode.group"
            fi
            getent group gamemode >/dev/null || run groupadd --system gamemode
            run usermod -aG gamemode "$user" ;;
        "off gamemode")
            local user st grp
            [[ -f "$STATE/gamemode.group" ]] || exit 0
            read -r user st grp < "$STATE/gamemode.group"
            [[ "$user" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "odd saved user" >&2; exit 5; }
            if [[ "$grp" == created ]]; then
                run groupdel gamemode || warn "couldn't remove the gamemode group"
            elif [[ "$st" == added ]]; then
                run gpasswd -d "$user" gamemode >/dev/null || warn "couldn't take $user out of gamemode"
            fi
            rm -f "$STATE/gamemode.group" ;;
        "on shutdown")
            local d
            for d in system user; do
                printf '%s\n[Manager]\nDefaultTimeoutStopSec=15s\n' "$MARK" > "$R/etc/systemd/$d.conf.d/99-grimoire-optimizel.conf"
            done
            run systemctl daemon-reload || warn "it applies after a restart" ;;   # re-reads system.conf (systemd 223+)
        "off shutdown")
            rm -f "$R/etc/systemd/system.conf.d/99-grimoire-optimizel.conf" "$R/etc/systemd/user.conf.d/99-grimoire-optimizel.conf"
            run systemctl daemon-reload || warn "it returns after a restart" ;;
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
        "on thermald")   units_set thermald disable thermald.service ;;
        "off thermald")  units_restore thermald ;;
        "on gpumanager") units_set gpumanager disable gpu-manager.service ;;
        "off gpumanager") units_restore gpumanager ;;
        "on rsyslog")    units_set rsyslog disable rsyslog.service ;;
        "off rsyslog")   units_restore rsyslog ;;
        "on netdispatch") units_set netdispatch disable networkd-dispatcher.service ;;
        "off netdispatch") units_restore netdispatch ;;
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
                printf '%s\n[Service]\nNice=19\nCPUWeight=20\nIOSchedulingClass=idle\n' "$MARK" \
                    > "$R/etc/systemd/system/$u.d/grimoire-optimizel.conf"
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

[[ $# -ge 2 && $(( $# % 2 )) -eq 0 ]] || { sed -n '2,10p' "$0" >&2; exit 2; }
while [[ $# -gt 0 ]]; do
    [[ "$1" == on || "$1" == off ]] || { echo "expected on/off, got: $1" >&2; exit 2; }
    [[ "$2" =~ ^[a-z]+$ ]] || { echo "bad tweak id: $2" >&2; exit 2; }
    tweak "$1" "$2"
    echo "$1 $2 ok"
    shift 2
done
