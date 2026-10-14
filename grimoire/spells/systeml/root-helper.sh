#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# System-wide actions for Grimoire SystemL. Run through pkexec (asks for your password):
#   root-helper.sh signal PID TERM|KILL|STOP|CONT     signal a process you don't own
#   root-helper.sh renice PID NICE                    set a process's priority (-20..19)
#   root-helper.sh unit start|stop|restart|enable|disable NAME    a system service, timer or socket
#   root-helper.sh swap-refresh                       move swap back into RAM (only when it fits)
# Every argument is checked; core processes and units that keep the session alive are refused.
set -euo pipefail

need_pid() {
    [[ "$1" =~ ^[0-9]+$ && "$1" -gt 2 && -d "/proc/$1" ]] || { echo "not a process you can change: $1" >&2; exit 2; }
    local comm; comm=$(cat "/proc/$1/comm" 2>/dev/null || true)
    case "$comm" in
        # /proc comm is cut at 15 characters, hence kwin_wayland_wr and startplasma-way
        systemd|systemd-journal|systemd-logind|dbus-daemon|dbus-broker|sddm|kwin_wayland|kwin_wayland_wr|Xwayland|\
        plasmashell|ksmserver|startplasma-way|pipewire|wireplumber)
            [[ "${2:-}" == renice ]] || { echo "$comm keeps the system running; not stopping it" >&2; exit 3; } ;;
    esac
}

case "${1:-}" in
    signal)
        need_pid "${2:-}"
        [[ "${3:-}" =~ ^(TERM|KILL|STOP|CONT)$ ]] || { echo "bad signal: ${3:-}" >&2; exit 2; }
        kill -s "$3" "$2"
        ;;
    renice)
        need_pid "${2:-}" renice
        [[ "${3:-}" =~ ^-?[0-9]+$ && "$3" -ge -20 && "$3" -le 19 ]] || { echo "bad priority: ${3:-}" >&2; exit 2; }
        # nice is per thread on Linux: set every thread, not just the main one
        for t in /proc/"$2"/task/*; do renice -n "$3" -p "${t##*/}" >/dev/null 2>&1 || true; done
        renice -n "$3" -p "$2" >/dev/null
        ;;
    unit)
        [[ "${2:-}" =~ ^(start|stop|restart|enable|disable)$ ]] || { echo "bad action: ${2:-}" >&2; exit 2; }
        [[ "${3:-}" =~ ^[-A-Za-z0-9@._:]+\.(service|timer|socket)$ ]] || { echo "bad unit name: ${3:-}" >&2; exit 2; }
        if [[ "$2" =~ ^(stop|disable|restart)$ ]]; then
            case "$3" in
                dbus*|systemd-*|sddm.service|display-manager.service|polkit.service|user@*|getty@*|udisks2.service|\
                plasma-kwin_wayland*|plasma-workspace*|plasma-plasmashell*)
                    echo "$3 keeps the system running; not stopping it" >&2; exit 3 ;;
            esac
        fi
        systemctl "$2" -- "$3"
        ;;
    swap-refresh)
        avail=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
        total=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)
        free=$(awk '/^SwapFree:/ {print $2}' /proc/meminfo)
        used=$((total - free))
        (( used > 0 )) || { echo "swap is already empty"; exit 0; }
        (( avail > used + 1048576 )) || { echo "not enough free RAM to empty swap safely" >&2; exit 3; }
        # swapon -a only brings back fstab entries, so zram would stay off: put back exactly what was on
        # (zram devices stay set up after swapoff, so swapon on them works), with their old priorities
        mapfile -t swaps < <(swapon --show=NAME,PRIO --noheadings --raw)
        for s in "${swaps[@]}"; do swapoff "${s% *}" || echo "couldn't empty ${s% *}" >&2; done
        for s in "${swaps[@]}"; do
            prio=${s##* }; [[ "$prio" =~ ^[0-9]+$ ]] && opt=(-p "$prio") || opt=()
            swapon "${opt[@]}" "${s% *}" 2>/dev/null || swapon --show=NAME --noheadings | grep -qxF "${s% *}" \
                || echo "couldn't turn ${s% *} back on" >&2
        done
        ;;
    *)
        echo "usage: root-helper.sh signal|renice|unit|swap-refresh …" >&2
        exit 2
        ;;
esac
