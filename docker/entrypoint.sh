#!/bin/sh
set -eu

display="${DISPLAY:-:99}"
screen="${WEBOBS_XVFB_SCREEN:-1920x1080x24}"
mediamtx_enabled="${WEBOBS_WEBRTC_ENABLED:-true}"
mediamtx_config="${WEBOBS_MEDIAMTX_CONFIG:-/opt/webobs/etc/mediamtx.yml}"
export WEBOBS_WEBRTC_ENABLED="$mediamtx_enabled"

case "$mediamtx_enabled" in
    true|false) ;;
    *) echo "WEBOBS_WEBRTC_ENABLED must be true or false" >&2; exit 3 ;;
esac
if [ "$mediamtx_enabled" = "true" ] && [ ! -r "$mediamtx_config" ]; then
    echo "MediaMTX configuration is not readable: $mediamtx_config" >&2
    exit 3
fi

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
mediamtx_pid=""
webobsd_pid=""
shutdown_requested=0

terminate_child() {
    child_pid="$1"
    if [ -n "$child_pid" ] && kill -0 "$child_pid" 2>/dev/null; then
        kill -TERM "$child_pid" 2>/dev/null || true
    fi
}

shutdown_children() {
    terminate_child "$webobsd_pid"
    terminate_child "$mediamtx_pid"
    terminate_child "$xvfb_pid"
}

request_shutdown() {
    shutdown_requested=1
    trap - INT TERM
    # Keep Xvfb and MediaMTX available while webobsd flushes its outputs.
    terminate_child "$webobsd_pid"
}

trap request_shutdown INT TERM

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
    terminate_child "$xvfb_pid"
    echo "Timed out waiting for Xvfb display $display" >&2
    exit 3
fi

if [ "$mediamtx_enabled" = "true" ]; then
    /opt/webobs/bin/mediamtx "$mediamtx_config" &
    mediamtx_pid=$!
fi

/opt/obs/bin/webobsd "$@" &
webobsd_pid=$!

exit_status=0
while kill -0 "$webobsd_pid" 2>/dev/null; do
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$mediamtx_pid" ] && ! kill -0 "$mediamtx_pid" 2>/dev/null; then
        echo "MediaMTX exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && ! kill -0 "$xvfb_pid" 2>/dev/null; then
        echo "Xvfb exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    sleep 0.1
done

set +e
wait "$webobsd_pid"
webobsd_status=$?
set -e
if [ "$exit_status" -eq 0 ]; then
    exit_status=$webobsd_status
fi

shutdown_children
if [ -n "$mediamtx_pid" ]; then
    wait "$mediamtx_pid" 2>/dev/null || true
fi
wait "$xvfb_pid" 2>/dev/null || true
exit "$exit_status"
