#!/bin/sh
set -eu

display="${DISPLAY:-:99}"
screen="${WEBOBS_XVFB_SCREEN:-1920x1080x24}"

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
