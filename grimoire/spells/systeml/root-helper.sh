#!/usr/bin/env bash
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
        systemd|systemd-journal|systemd-logind|dbus-daemon|dbus-broker|sddm|kwin_wayland|Xwayland|plasmashell)
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
        renice -n "$3" -p "$2" >/dev/null
        ;;
    unit)
        [[ "${2:-}" =~ ^(start|stop|restart|enable|disable)$ ]] || { echo "bad action: ${2:-}" >&2; exit 2; }
        [[ "${3:-}" =~ ^[-A-Za-z0-9@._:]+\.(service|timer|socket)$ ]] || { echo "bad unit name: ${3:-}" >&2; exit 2; }
        if [[ "$2" =~ ^(stop|disable)$ ]]; then
            case "$3" in
                dbus*|systemd-*|sddm.service|display-manager.service|polkit.service|user@*|getty@*|udisks2.service)
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
        swapoff -a && swapon -a
        ;;
    *)
        echo "usage: root-helper.sh signal|renice|unit|swap-refresh …" >&2
        exit 2
        ;;
esac
