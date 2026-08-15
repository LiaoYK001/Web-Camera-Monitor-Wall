#!/bin/sh
set -eu
umask 077

display="${DISPLAY:-:99}"
screen="${WEBOBS_XVFB_SCREEN:-1920x1080x24}"
mediamtx_enabled="${WEBOBS_WEBRTC_ENABLED:-true}"
mediamtx_config="${WEBOBS_MEDIAMTX_CONFIG:-/opt/webobs/etc/mediamtx.yml}"
tls_enabled="${WEBOBS_TLS_ENABLED:-false}"
caddy_config="${WEBOBS_CADDY_CONFIG:-/opt/webobs/etc/Caddyfile}"
export WEBOBS_WEBRTC_ENABLED="$mediamtx_enabled"
browser_cache="/config/obs/plugin_config/obs-browser"

fail() {
    echo "$1" >&2
    exit 3
}

read_secret_file() {
    secret_name="$1"
    secret_path="$2"
    case "$secret_path" in
        /*) ;;
        *) fail "$secret_name file path must be absolute" ;;
    esac
    [ -f "$secret_path" ] && [ -r "$secret_path" ] || fail "$secret_name file is not readable"
    secret_size="$(wc -c < "$secret_path" | tr -d ' ')"
    [ "$secret_size" -le 4096 ] || fail "$secret_name file is too large"
    secret_value="$(cat -- "$secret_path")"
    [ -n "$secret_value" ] || fail "$secret_name file is empty"
    case "$secret_value" in
        *"$(printf '\r')"*|*"
"*) fail "$secret_name must contain exactly one value" ;;
    esac
    printf '%s' "$secret_value"
}

cleanup_browser_cache() {
    rm -rf -- "$browser_cache"
}

mkdir -p /config/obs/plugin_config
chmod 0700 /config/obs /config/obs/plugin_config
cleanup_browser_cache
mkdir -m 0700 "$browser_cache"
trap cleanup_browser_cache EXIT

case "$mediamtx_enabled" in
    true|false) ;;
    *) fail "WEBOBS_WEBRTC_ENABLED must be true or false" ;;
esac
if [ "$mediamtx_enabled" = "true" ] && [ ! -r "$mediamtx_config" ]; then
    fail "MediaMTX configuration is not readable"
fi

case "$tls_enabled" in
    true|false) ;;
    *) fail "WEBOBS_TLS_ENABLED must be true or false" ;;
esac
if [ "$tls_enabled" = "true" ]; then
    tls_cert_file="${WEBOBS_TLS_CERT_FILE:-}"
    tls_key_file="${WEBOBS_TLS_KEY_FILE:-}"
    tls_server_name="${WEBOBS_TLS_SERVER_NAME:-}"
    https_port="${WEBOBS_HTTPS_PORT:-8443}"
    tls_public_authority="${WEBOBS_TLS_PUBLIC_AUTHORITY:-${tls_server_name}:${https_port}}"
    [ "${WEBOBS_LISTEN_ADDRESS:-127.0.0.1}" = "127.0.0.1" ] || fail "TLS mode requires WEBOBS_LISTEN_ADDRESS=127.0.0.1"
    [ "${WEBOBS_ALLOW_INSECURE_REMOTE:-false}" = "false" ] || fail "TLS mode requires WEBOBS_ALLOW_INSECURE_REMOTE=false"
    [ -r "$caddy_config" ] || fail "Caddy configuration is not readable"
    [ -f "$tls_cert_file" ] && [ -r "$tls_cert_file" ] || fail "TLS certificate file is not readable"
    [ -f "$tls_key_file" ] && [ -r "$tls_key_file" ] || fail "TLS private-key file is not readable"
    case "$tls_server_name" in
        ''|*[!A-Za-z0-9.-]*) fail "WEBOBS_TLS_SERVER_NAME must be a DNS name or IPv4 address" ;;
    esac
    case "$https_port" in
        ''|*[!0-9]*) fail "WEBOBS_HTTPS_PORT must be an integer" ;;
    esac
    [ "$https_port" -ge 1 ] && [ "$https_port" -le 65535 ] || fail "WEBOBS_HTTPS_PORT must be between 1 and 65535"
    case "$tls_public_authority" in
        ''|*[!A-Za-z0-9.:-]*) fail "WEBOBS_TLS_PUBLIC_AUTHORITY must contain only a host and optional port" ;;
    esac
    export WEBOBS_TLS_CERT_FILE="$tls_cert_file"
    export WEBOBS_TLS_KEY_FILE="$tls_key_file"
    export WEBOBS_TLS_SERVER_NAME="$tls_server_name"
    export WEBOBS_HTTPS_PORT="$https_port"
    export WEBOBS_TLS_PUBLIC_AUTHORITY="$tls_public_authority"
fi

turn_url="${WEBOBS_TURN_URL:-}"
if [ -n "$turn_url" ]; then
    [ "$mediamtx_enabled" = "true" ] || fail "TURN requires WEBOBS_WEBRTC_ENABLED=true"
    [ "${#turn_url}" -le 512 ] || fail "WEBOBS_TURN_URL is too long"
    case "$turn_url" in
        turn:*:*\?transport=tcp|turns:*:*\?transport=tcp) ;;
        *) fail "WEBOBS_TURN_URL must include turn: or turns:, an explicit port, and transport=tcp" ;;
    esac
    case "$turn_url" in
        *[!A-Za-z0-9.:/?=_-]*) fail "WEBOBS_TURN_URL contains unsupported characters" ;;
    esac
    turn_username="$(read_secret_file "TURN username" "${WEBOBS_TURN_USERNAME_FILE:-}")"
    turn_password="$(read_secret_file "TURN password" "${WEBOBS_TURN_PASSWORD_FILE:-}")"
    turn_client_only="${WEBOBS_TURN_CLIENT_ONLY:-false}"
    case "$turn_client_only" in
        true|false) ;;
        *) fail "WEBOBS_TURN_CLIENT_ONLY must be true or false" ;;
    esac
    export MTX_WEBRTCICESERVERS2_0_URL="$turn_url"
    export MTX_WEBRTCICESERVERS2_0_USERNAME="$turn_username"
    export MTX_WEBRTCICESERVERS2_0_PASSWORD="$turn_password"
    export MTX_WEBRTCICESERVERS2_0_CLIENTONLY="$turn_client_only"
fi

case "$display" in
    :*) display_number="${display#:}" ;;
    *) fail "DISPLAY must be a local display such as :99" ;;
esac
case "$display_number" in
    ''|*[!0-9]*) fail "DISPLAY must contain only a local numeric display number" ;;
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
mediamtx_filter_pid=""
mediamtx_log_pipe=""
caddy_pid=""
caddy_filter_pid=""
caddy_log_pipe=""
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
    terminate_child "$caddy_pid"
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
    mediamtx_log_pipe="/tmp/webobs-mediamtx-log.$$"
    mkfifo "$mediamtx_log_pipe"
    /opt/obs/bin/webobs-log-filter < "$mediamtx_log_pipe" &
    mediamtx_filter_pid=$!
    /opt/webobs/bin/mediamtx "$mediamtx_config" > "$mediamtx_log_pipe" 2>&1 &
    mediamtx_pid=$!
fi

if [ "$tls_enabled" = "true" ]; then
    /opt/webobs/bin/caddy validate --config "$caddy_config" --adapter caddyfile >/dev/null
    caddy_log_pipe="/tmp/webobs-caddy-log.$$"
    mkfifo "$caddy_log_pipe"
    /opt/obs/bin/webobs-log-filter < "$caddy_log_pipe" &
    caddy_filter_pid=$!
    /opt/webobs/bin/caddy run --config "$caddy_config" --adapter caddyfile > "$caddy_log_pipe" 2>&1 &
    caddy_pid=$!
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
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$mediamtx_filter_pid" ] && ! kill -0 "$mediamtx_filter_pid" 2>/dev/null; then
        echo "MediaMTX log filter exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$caddy_pid" ] && ! kill -0 "$caddy_pid" 2>/dev/null; then
        echo "HTTPS proxy exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$caddy_filter_pid" ] && ! kill -0 "$caddy_filter_pid" 2>/dev/null; then
        echo "HTTPS proxy log filter exited while webobsd was running" >&2
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
if [ -n "$mediamtx_filter_pid" ]; then
    wait "$mediamtx_filter_pid" 2>/dev/null || true
fi
if [ -n "$caddy_pid" ]; then
    wait "$caddy_pid" 2>/dev/null || true
fi
if [ -n "$caddy_filter_pid" ]; then
    wait "$caddy_filter_pid" 2>/dev/null || true
fi
if [ -n "$mediamtx_log_pipe" ]; then
    rm -f -- "$mediamtx_log_pipe"
fi
if [ -n "$caddy_log_pipe" ]; then
    rm -f -- "$caddy_log_pipe"
fi
wait "$xvfb_pid" 2>/dev/null || true
exit "$exit_status"
