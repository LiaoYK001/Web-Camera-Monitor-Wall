#!/bin/sh
set -eu

display="${DISPLAY:-:99}"
screen="${WEBOBS_XVFB_SCREEN:-1920x1080x24}"

case "$display" in
    :*) display_number="${display#:}" ;;
    *) echo "DISPLAY must be a local display such as :99" >&2; exit 3 ;;
esac
case "$display_number" in
    ''|*[!0-9]*) echo "DISPLAY must contain only a local numeric display number" >&2; exit 3 ;;
esac

display_lock="/tmp/.X${display_number}-lock"
display_socket="/tmp/.X11-unix/X${display_number}"
if xdpyinfo -display "$display" >/dev/null 2>&1; then
    echo "X display $display is already active" >&2
    exit 3
fi
if [ -f "$display_lock" ]; then
    display_pid="$(tr -cd '0-9' < "$display_lock")"
    if [ -n "$display_pid" ] && kill -0 "$display_pid" 2>/dev/null; then
        echo "X display $display is owned by live process $display_pid" >&2
        exit 3
    fi
fi
rm -f -- "$display_lock" "$display_socket"

Xvfb "$display" -screen 0 "$screen" -nolisten tcp -ac +extension GLX +render -noreset &
xvfb_pid=$!

ready=0
attempt=0
while [ "$attempt" -lt 100 ]; do
    if xdpyinfo -display "$display" >/dev/null 2>&1; then
        ready=1
        break
    fi
    if ! kill -0 "$xvfb_pid" 2>/dev/null; then
        echo "Xvfb exited before the display became ready" >&2
        exit 3
    fi
    attempt=$((attempt + 1))
    sleep 0.05
done

if [ "$ready" -ne 1 ]; then
    echo "Timed out waiting for Xvfb display $display" >&2
    exit 3
fi

exec /opt/obs/bin/webobsd "$@"
