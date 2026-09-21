#!/bin/sh
set -eu
umask 077

display="${DISPLAY:-:99}"
configured_display="$display"
screen="${WEBOBS_XVFB_SCREEN:-1920x1080x24}"
node_role="${WEBOBS_NODE_ROLE:-standalone}"
case "$node_role" in
    standalone)
        role_mediamtx_default=true
        role_nvr_default=false
        role_registry_default=true
        role_v2_default=true
        role_events_default=true
        role_cluster_default=true
        ;;
    controller)
        role_mediamtx_default=true
        role_nvr_default=false
        role_registry_default=true
        role_v2_default=true
        role_events_default=true
        role_cluster_default=true
        ;;
    recorder)
        role_mediamtx_default=false
        role_nvr_default=true
        role_registry_default=false
        role_v2_default=false
        role_events_default=false
        role_cluster_default=false
        export WEBOBS_HTTP_PORT="${WEBOBS_HTTP_PORT:-0}"
        ;;
    worker)
        role_mediamtx_default=false
        role_nvr_default=false
        role_registry_default=false
        role_v2_default=false
        role_events_default=false
        role_cluster_default=false
        export WEBOBS_HTTP_PORT="${WEBOBS_HTTP_PORT:-0}"
        ;;
    *) fail_message="WEBOBS_NODE_ROLE must be standalone, controller, recorder, or worker"; echo "$fail_message" >&2; exit 3 ;;
esac
export WEBOBS_NODE_ROLE="$node_role"
mediamtx_enabled="${WEBOBS_WEBRTC_ENABLED:-$role_mediamtx_default}"
mediamtx_config="${WEBOBS_MEDIAMTX_CONFIG:-/opt/webobs/etc/mediamtx.yml}"
tls_enabled="${WEBOBS_TLS_ENABLED:-false}"
nvr_enabled="${WEBOBS_NVR_ENABLED:-$role_nvr_default}"
camera_registry_enabled="${WEBOBS_CAMERA_REGISTRY_ENABLED:-$role_registry_default}"
v2_client_control_enabled="${WEBOBS_V2_CLIENT_CONTROL_ENABLED:-$role_v2_default}"
events_enabled="${WEBOBS_EVENTS_ENABLED:-$role_events_default}"
cluster_enabled="${WEBOBS_CLUSTER_ENABLED:-$role_cluster_default}"
compat_basic_auth="${WEBOBS_COMPAT_BASIC_AUTH:-true}"
archive_enabled="${WEBOBS_ARCHIVE_ENABLED:-false}"
encrypted_backup_enabled="${WEBOBS_ENCRYPTED_BACKUP_ENABLED:-false}"
node_agent_enabled=false
case "$node_role" in
    recorder|worker) node_agent_enabled=true ;;
esac
caddy_config="${WEBOBS_CADDY_CONFIG:-/opt/webobs/etc/Caddyfile}"
export WEBOBS_WEBRTC_ENABLED="$mediamtx_enabled"
browser_cache="/config/obs/plugin_config/obs-browser"
renderer_requested="${WEBOBS_RENDERER:-auto}"
vaapi_device="${WEBOBS_VAAPI_DEVICE:-/dev/dri/renderD128}"
renderer_required=false
if [ "${WEBOBS_COMPOSITE_ENABLED:-false}" = true ] ||
   [ -n "${WEBOBS_OUTPUT:-}" ] || [ -n "${WEBOBS_RTSP_URL:-}" ]; then
    renderer_required=true
fi
renderer_argument=""
for argument in "$@"; do
    if [ -n "$renderer_argument" ]; then
        case "$renderer_argument" in
            output|rtsp) [ -n "$argument" ] && renderer_required=true ;;
            composite) [ "$argument" = true ] && renderer_required=true ;;
        esac
        renderer_argument=""
        continue
    fi
    case "$argument" in
        --output) renderer_argument=output ;;
        --rtsp-url) renderer_argument=rtsp ;;
        --composite-enabled) renderer_argument=composite ;;
    esac
done

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
case "$nvr_enabled" in
    true|false) ;;
    *) fail "WEBOBS_NVR_ENABLED must be true or false" ;;
esac
case "$camera_registry_enabled" in
    true|false) ;;
    *) fail "WEBOBS_CAMERA_REGISTRY_ENABLED must be true or false" ;;
esac
case "$v2_client_control_enabled" in
    true|false) ;;
    *) fail "WEBOBS_V2_CLIENT_CONTROL_ENABLED must be true or false" ;;
esac
[ "$v2_client_control_enabled" = "false" ] || [ "$camera_registry_enabled" = "true" ] || \
    fail "v2 client control requires WEBOBS_CAMERA_REGISTRY_ENABLED=true"
if [ "$v2_client_control_enabled" = "true" ]; then
    WEBOBS_V2_INTERNAL_TOKEN="$(tr -d '-' < /proc/sys/kernel/random/uuid)$(tr -d '-' < /proc/sys/kernel/random/uuid)"
    case "$WEBOBS_V2_INTERNAL_TOKEN" in
        *[!0-9a-f]*|'') fail "could not create the v2 internal administrator token" ;;
    esac
    [ "${#WEBOBS_V2_INTERNAL_TOKEN}" -eq 64 ] || fail "could not create the v2 internal administrator token"
    export WEBOBS_V2_INTERNAL_TOKEN
fi
case "$events_enabled" in
    true|false) ;;
    *) fail "WEBOBS_EVENTS_ENABLED must be true or false" ;;
esac
case "$cluster_enabled" in
    true|false) ;;
    *) fail "WEBOBS_CLUSTER_ENABLED must be true or false" ;;
esac
case "$compat_basic_auth" in
    true|false) ;;
    *) fail "WEBOBS_COMPAT_BASIC_AUTH must be true or false" ;;
esac
export WEBOBS_COMPAT_BASIC_AUTH="$compat_basic_auth"
case "$archive_enabled" in
    true|false) ;;
    *) fail "WEBOBS_ARCHIVE_ENABLED must be true or false" ;;
esac
[ "$archive_enabled" = "false" ] || [ "$nvr_enabled" = "true" ] || \
    fail "S3 archive requires WEBOBS_NVR_ENABLED=true"
if [ "$archive_enabled" = "true" ]; then
    [ -r "${WEBOBS_ARCHIVE_CONFIG:-/config/webobs/archive.json}" ] || fail "S3 archive configuration is not readable"
fi
case "$encrypted_backup_enabled" in
    true|false) ;;
    *) fail "WEBOBS_ENCRYPTED_BACKUP_ENABLED must be true or false" ;;
esac
if [ "$encrypted_backup_enabled" = "true" ]; then
    [ -r "${WEBOBS_BACKUP_KEY_FILE:-/run/secrets/webobs_backup_key}" ] || fail "encrypted backup key is not readable"
    mkdir -p "${WEBOBS_BACKUP_ROOT:-/backups}"
fi
if [ "$cluster_enabled" = "true" ]; then
    if [ -n "${WEBOBS_CLUSTER_INTERNAL_TOKEN_FILE:-}" ]; then
        WEBOBS_CLUSTER_INTERNAL_TOKEN="$(read_secret_file WEBOBS_CLUSTER_INTERNAL_TOKEN "${WEBOBS_CLUSTER_INTERNAL_TOKEN_FILE}")"
    else
        WEBOBS_CLUSTER_INTERNAL_TOKEN="$(tr -d '-' < /proc/sys/kernel/random/uuid)$(tr -d '-' < /proc/sys/kernel/random/uuid)"
    fi
    case "$WEBOBS_CLUSTER_INTERNAL_TOKEN" in
        *[!0-9a-f]*|'') fail "could not create the cluster internal administrator token" ;;
    esac
    [ "${#WEBOBS_CLUSTER_INTERNAL_TOKEN}" -eq 64 ] || fail "could not create the cluster internal administrator token"
    export WEBOBS_CLUSTER_INTERNAL_TOKEN
fi
if [ "$node_agent_enabled" = "true" ]; then
    [ -n "${WEBOBS_CONTROLLER_URL:-}" ] || fail "recorder and worker roles require WEBOBS_CONTROLLER_URL"
    [ -n "${WEBOBS_CLUSTER_CA_FILE:-}" ] && [ -r "${WEBOBS_CLUSTER_CA_FILE}" ] || \
        fail "recorder and worker roles require a readable cluster CA file"
fi

case "$renderer_requested" in
    auto|hardware|software) ;;
    *) fail "WEBOBS_RENDERER must be auto, hardware, or software" ;;
esac
vaapi_node_number="${vaapi_device#/dev/dri/renderD}"
case "$vaapi_node_number" in
    ''|*[!0-9]*) fail "WEBOBS_VAAPI_DEVICE must be an absolute /dev/dri/renderD<n> path" ;;
esac
[ "$vaapi_device" = "/dev/dri/renderD${vaapi_node_number}" ] || \
    fail "WEBOBS_VAAPI_DEVICE must be an absolute /dev/dri/renderD<n> path"

# A render node by itself does not prove that libva can load a driver or that
# the GPU exposes encode/decode entry points. Export the individual results so
# webobsd can report the observed runtime state without re-running a shell.
vaapi_device_present=false
vaapi_driver_loaded=false
vaapi_encode_supported=false
vaapi_decode_supported=false
vaapi_runtime_probe_passed=false
vaapi_probe_file="/tmp/webobs-vainfo.$$"
if [ -e "$vaapi_device" ] && [ -r "$vaapi_device" ] && [ -w "$vaapi_device" ]; then
    vaapi_device_present=true
    if vainfo --display drm --device "$vaapi_device" >"$vaapi_probe_file" 2>&1; then
        vaapi_runtime_probe_passed=true
        if grep -Eq 'Driver version|va_openDriver.*returns 0' "$vaapi_probe_file"; then
            vaapi_driver_loaded=true
        fi
        if grep -Eq 'VAEntrypointEncSlice|VAEntrypointEncSliceLP' "$vaapi_probe_file"; then
            vaapi_encode_supported=true
        fi
        if grep -Eq 'VAEntrypointVLD' "$vaapi_probe_file"; then
            vaapi_decode_supported=true
        fi
    fi
fi
rm -f -- "$vaapi_probe_file"
export WEBOBS_VAAPI_DEVICE_PRESENT="$vaapi_device_present"
export WEBOBS_VAAPI_DRIVER_LOADED="$vaapi_driver_loaded"
export WEBOBS_VAAPI_ENCODE_SUPPORTED="$vaapi_encode_supported"
export WEBOBS_VAAPI_DECODE_SUPPORTED="$vaapi_decode_supported"
export WEBOBS_VAAPI_RUNTIME_PROBE_PASSED="$vaapi_runtime_probe_passed"
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

xvfb_pid=""
weston_pid=""
weston_runtime=""
weston_log=""
mediamtx_pid=""
mediamtx_filter_pid=""
mediamtx_log_pipe=""
caddy_pid=""
caddy_filter_pid=""
caddy_log_pipe=""
nvr_pid=""
nvr_filter_pid=""
nvr_log_pipe=""
camera_registry_pid=""
camera_registry_filter_pid=""
camera_registry_log_pipe=""
v2_client_control_pid=""
v2_client_control_filter_pid=""
v2_client_control_log_pipe=""
events_pid=""
events_filter_pid=""
events_log_pipe=""
cluster_pid=""
cluster_filter_pid=""
cluster_log_pipe=""
node_agent_pid=""
node_agent_filter_pid=""
node_agent_log_pipe=""
detector_worker_pid=""
detector_worker_log=""
archive_pid=""
archive_filter_pid=""
archive_log_pipe=""
encrypted_backup_pid=""
encrypted_backup_filter_pid=""
encrypted_backup_log_pipe=""
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
    terminate_child "$nvr_pid"
    terminate_child "$camera_registry_pid"
    terminate_child "$v2_client_control_pid"
    terminate_child "$events_pid"
    terminate_child "$cluster_pid"
    terminate_child "$node_agent_pid"
    terminate_child "$detector_worker_pid"
    terminate_child "$archive_pid"
    terminate_child "$encrypted_backup_pid"
    terminate_child "$xvfb_pid"
    terminate_child "$weston_pid"
}

request_shutdown() {
    shutdown_requested=1
    trap - INT TERM
    # Keep Xvfb and MediaMTX available while webobsd flushes its outputs.
    terminate_child "$webobsd_pid"
}

trap request_shutdown INT TERM

# v2.3 performs a one-time, byte-verified configuration snapshot before any
# service can migrate its SQLite schema. The EXIT trap restores immediately
# when children have stopped, or leaves the authenticated pending marker for a
# guaranteed rollback before the next start if a child is still flushing.
upgrade_guard=/opt/webobs/bin/webobs-preupgrade-guard
upgrade_pending=/config/webobs/.v2-m7-upgrade-pending.json
python3 "$upgrade_guard" prepare --config-root /config/webobs
upgrade_exit() {
    upgrade_status=$?
    trap - EXIT
    if [ -f "$upgrade_pending" ]; then
        shutdown_children
        upgrade_wait=0
        while [ "$upgrade_wait" -lt 20 ]; do
            upgrade_alive=false
            for upgrade_pid in "$webobsd_pid" "$nvr_pid" "$camera_registry_pid" \
                    "$v2_client_control_pid" "$events_pid" "$cluster_pid" "$node_agent_pid" \
                    "$archive_pid" "$encrypted_backup_pid"; do
                if [ -n "$upgrade_pid" ] && kill -0 "$upgrade_pid" 2>/dev/null; then
                    upgrade_alive=true
                    break
                fi
            done
            [ "$upgrade_alive" = true ] || break
            upgrade_wait=$((upgrade_wait + 1))
            sleep 0.1
        done
        if [ "$upgrade_alive" = false ]; then
            python3 "$upgrade_guard" rollback --config-root /config/webobs || upgrade_status=3
        else
            echo "v2-M7 upgrade rollback deferred until the next safe start" >&2
            upgrade_status=3
        fi
    fi
    cleanup_browser_cache
    exit "$upgrade_status"
}
trap upgrade_exit EXIT

renderer_selected=idle
renderer_fallback=false
renderer_fallback_reason=""
hardware_renderer_ready=false

# A hardware X11/EGL context cannot be obtained from Xvfb. On a qualified
# render node, Weston provides a headless EGL compositor and Xwayland gives
# libobs the X11 display required by OBS 32.1.2. Auto mode falls back to the
# deterministic Xvfb/llvmpipe path if any part of that probe fails.
if [ "$renderer_required" = true ] && [ "$renderer_requested" != software ] &&
   [ "$vaapi_runtime_probe_passed" = true ]; then
    unset LIBGL_ALWAYS_SOFTWARE GALLIUM_DRIVER || true
    weston_runtime="/tmp/webobs-weston-runtime.$$"
    weston_log="/tmp/webobs-weston.$$"
    mkdir -m 0700 "$weston_runtime"
    export XDG_RUNTIME_DIR="$weston_runtime"
    export WAYLAND_DISPLAY="webobs-wayland"
    env -u EGL_PLATFORM weston --backend=headless-backend.so --renderer=gl --xwayland \
        --idle-time=0 --socket="$WAYLAND_DISPLAY" >"$weston_log" 2>&1 &
    weston_pid=$!
    attempt=0
    while [ "$attempt" -lt 100 ]; do
        for candidate in /tmp/.X11-unix/X*; do
            [ -S "$candidate" ] || continue
            candidate_number="${candidate##*/X}"
            case "$candidate_number" in ''|*[!0-9]*) continue ;; esac
            if xdpyinfo -display ":$candidate_number" >/dev/null 2>&1; then
                display=":$candidate_number"
                export DISPLAY="$display"
                renderer_probe="$(glxinfo -B -display "$display" 2>/dev/null || true)"
                if printf '%s\n' "$renderer_probe" | grep -Eq 'OpenGL renderer string:' && \
                   ! printf '%s\n' "$renderer_probe" | grep -Eiq 'llvmpipe|softpipe|software rasterizer'; then
                    hardware_renderer_ready=true
                fi
                break 2
            fi
        done
        kill -0 "$weston_pid" 2>/dev/null || break
        attempt=$((attempt + 1))
        sleep 0.05
    done
fi

if [ "$renderer_required" != true ]; then
    unset LIBGL_ALWAYS_SOFTWARE GALLIUM_DRIVER XDG_RUNTIME_DIR WAYLAND_DISPLAY || true
elif [ "$hardware_renderer_ready" = true ]; then
    renderer_selected=hardware
else
    renderer_selected=software
    if [ -n "$weston_pid" ]; then
        terminate_child "$weston_pid"
        wait "$weston_pid" 2>/dev/null || true
        weston_pid=""
    fi
    if [ "$renderer_requested" = hardware ]; then
        fail "hardware renderer was requested but the headless EGL/Xwayland probe failed"
    fi
    [ "$renderer_requested" = auto ] && renderer_fallback=true
    [ "$renderer_requested" = auto ] && renderer_fallback_reason="hardware_renderer_probe_failed"
    unset XDG_RUNTIME_DIR WAYLAND_DISPLAY || true
    export LIBGL_ALWAYS_SOFTWARE=1
    export GALLIUM_DRIVER=llvmpipe
    display="$configured_display"
    export DISPLAY="$display"
    case "$display" in :*) display_number="${display#:}" ;; *) fail "DISPLAY must be a local display such as :99" ;; esac
    case "$display_number" in ''|*[!0-9]*) fail "DISPLAY must contain only a local numeric display number" ;; esac
    display_lock="/tmp/.X${display_number}-lock"
    display_socket="/tmp/.X11-unix/X${display_number}"
    if xdpyinfo -display "$display" >/dev/null 2>&1; then
        fail "X display $display is already active"
    fi
    if [ -f "$display_lock" ]; then
        display_pid="$(tr -cd '0-9' < "$display_lock")"
        if [ -n "$display_pid" ] && kill -0 "$display_pid" 2>/dev/null; then
            fail "X display $display is owned by a live process"
        fi
    fi
    rm -f -- "$display_lock" "$display_socket"
    Xvfb "$display" -screen 0 "$screen" -nolisten tcp -ac +extension GLX +render -noreset &
    xvfb_pid=$!
    ready=0
    attempt=0
    while [ "$attempt" -lt 100 ]; do
        if xdpyinfo -display "$display" >/dev/null 2>&1; then ready=1; break; fi
        kill -0 "$xvfb_pid" 2>/dev/null || break
        attempt=$((attempt + 1))
        sleep 0.05
    done
    [ "$ready" -eq 1 ] || fail "Timed out waiting for the software X display"
fi
export WEBOBS_RENDERER_REQUESTED="$renderer_requested"
export WEBOBS_RENDERER_SELECTED="$renderer_selected"
export WEBOBS_RENDERER_FALLBACK="$renderer_fallback"
export WEBOBS_RENDERER_FALLBACK_REASON="$renderer_fallback_reason"

if [ "$mediamtx_enabled" = "true" ]; then
    mediamtx_log_pipe="/tmp/webobs-mediamtx-log.$$"
    rm -f -- "$mediamtx_log_pipe"
    mkfifo "$mediamtx_log_pipe"
    /opt/obs/bin/webobs-log-filter < "$mediamtx_log_pipe" &
    mediamtx_filter_pid=$!
    /opt/webobs/bin/mediamtx "$mediamtx_config" > "$mediamtx_log_pipe" 2>&1 &
    mediamtx_pid=$!
fi

if [ "$tls_enabled" = "true" ]; then
    /opt/webobs/bin/caddy validate --config "$caddy_config" --adapter caddyfile >/dev/null
    caddy_log_pipe="/tmp/webobs-caddy-log.$$"
    rm -f -- "$caddy_log_pipe"
    mkfifo "$caddy_log_pipe"
    /opt/obs/bin/webobs-log-filter < "$caddy_log_pipe" &
    caddy_filter_pid=$!
    /opt/webobs/bin/caddy run --config "$caddy_config" --adapter caddyfile > "$caddy_log_pipe" 2>&1 &
    caddy_pid=$!
fi

if [ "$nvr_enabled" = "true" ]; then
    nvr_log_pipe="/tmp/webobs-nvr-log.$$"
    rm -f -- "$nvr_log_pipe"
    mkfifo "$nvr_log_pipe"
    /opt/obs/bin/webobs-log-filter < "$nvr_log_pipe" &
    nvr_filter_pid=$!
    python3 /opt/webobs/bin/webobs-nvrd > "$nvr_log_pipe" 2>&1 &
    nvr_pid=$!
fi

if [ "$camera_registry_enabled" = "true" ]; then
    camera_registry_log_pipe="/tmp/webobs-camera-registry-log.$$"
    rm -f -- "$camera_registry_log_pipe"
    mkfifo "$camera_registry_log_pipe"
    /opt/obs/bin/webobs-log-filter < "$camera_registry_log_pipe" &
    camera_registry_filter_pid=$!
    python3 /opt/webobs/bin/webobs-camera-registry > "$camera_registry_log_pipe" 2>&1 &
    camera_registry_pid=$!
    registry_ready=0
    registry_attempt=0
    while [ "$registry_attempt" -lt 50 ]; do
        if curl --fail --silent --show-error http://127.0.0.1:8092/health >/dev/null; then
            registry_ready=1
            break
        fi
        if ! kill -0 "$camera_registry_pid" 2>/dev/null; then
            fail "Camera Registry exited before becoming ready"
        fi
        registry_attempt=$((registry_attempt + 1))
        sleep 0.1
    done
    [ "$registry_ready" -eq 1 ] || fail "Timed out waiting for Camera Registry"
fi

if [ "$v2_client_control_enabled" = "true" ]; then
    v2_client_control_log_pipe="/tmp/webobs-client-control-log.$$"
    rm -f -- "$v2_client_control_log_pipe"
    mkfifo "$v2_client_control_log_pipe"
    /opt/obs/bin/webobs-log-filter < "$v2_client_control_log_pipe" &
    v2_client_control_filter_pid=$!
    python3 /opt/webobs/bin/webobs-client-control > "$v2_client_control_log_pipe" 2>&1 &
    v2_client_control_pid=$!
    v2_ready=0
    v2_attempt=0
    while [ "$v2_attempt" -lt 50 ]; do
        if curl --fail --silent --show-error http://127.0.0.1:8094/health >/dev/null; then
            v2_ready=1
            break
        fi
        if ! kill -0 "$v2_client_control_pid" 2>/dev/null; then
            fail "v2 client control exited before becoming ready"
        fi
        v2_attempt=$((v2_attempt + 1))
        sleep 0.1
    done
    [ "$v2_ready" -eq 1 ] || fail "Timed out waiting for v2 client control"
fi

if [ "$events_enabled" = "true" ]; then
    events_log_pipe="/tmp/webobs-events-log.$$"
    rm -f -- "$events_log_pipe"
    mkfifo "$events_log_pipe"
    /opt/obs/bin/webobs-log-filter < "$events_log_pipe" &
    events_filter_pid=$!
    python3 /opt/webobs/bin/webobs-events > "$events_log_pipe" 2>&1 &
    events_pid=$!
    events_ready=0
    events_attempt=0
    while [ "$events_attempt" -lt 50 ]; do
        if curl --fail --silent --show-error http://127.0.0.1:8093/health >/dev/null; then
            events_ready=1
            break
        fi
        if ! kill -0 "$events_pid" 2>/dev/null; then
            fail "Event service exited before becoming ready"
        fi
        events_attempt=$((events_attempt + 1))
        sleep 0.1
    done
    [ "$events_ready" -eq 1 ] || fail "Timed out waiting for Event service"
fi

if [ "$cluster_enabled" = "true" ]; then
    cluster_log_pipe="/tmp/webobs-cluster-log.$$"
    rm -f -- "$cluster_log_pipe"
    mkfifo "$cluster_log_pipe"
    /opt/obs/bin/webobs-log-filter < "$cluster_log_pipe" &
    cluster_filter_pid=$!
    python3 /opt/webobs/bin/webobs-cluster > "$cluster_log_pipe" 2>&1 &
    cluster_pid=$!
    cluster_ready=0
    cluster_attempt=0
    while [ "$cluster_attempt" -lt 50 ]; do
        if curl --fail --silent --show-error http://127.0.0.1:8095/health >/dev/null; then
            cluster_ready=1
            break
        fi
        if ! kill -0 "$cluster_pid" 2>/dev/null; then
            fail "Cluster service exited before becoming ready"
        fi
        cluster_attempt=$((cluster_attempt + 1))
        sleep 0.1
    done
    [ "$cluster_ready" -eq 1 ] || fail "Timed out waiting for Cluster service"
fi

if [ "$node_agent_enabled" = "true" ]; then
    node_agent_log_pipe="/tmp/webobs-node-agent-log.$$"
    rm -f -- "$node_agent_log_pipe"
    mkfifo "$node_agent_log_pipe"
    /opt/obs/bin/webobs-log-filter < "$node_agent_log_pipe" &
    node_agent_filter_pid=$!
    python3 /opt/webobs/bin/webobs-node-agent > "$node_agent_log_pipe" 2>&1 &
    node_agent_pid=$!
    # Enrollment may await explicit administrator approval. Only require the
    # process to survive initial validation here; health is represented by its
    # atomic assignment state and controller node status.
    sleep 0.2
    kill -0 "$node_agent_pid" 2>/dev/null || fail "Node agent exited during startup"
fi

if [ "$archive_enabled" = "true" ]; then
    archive_log_pipe="/tmp/webobs-archive-log.$$"
    rm -f -- "$archive_log_pipe"
    mkfifo "$archive_log_pipe"
    /opt/obs/bin/webobs-log-filter < "$archive_log_pipe" &
    archive_filter_pid=$!
    python3 /opt/webobs/bin/webobs-s3-archive > "$archive_log_pipe" 2>&1 &
    archive_pid=$!
    sleep 0.2
    kill -0 "$archive_pid" 2>/dev/null || fail "S3 archive service exited during startup"
fi

if [ "$encrypted_backup_enabled" = "true" ]; then
    encrypted_backup_log_pipe="/tmp/webobs-encrypted-backup-log.$$"
    rm -f -- "$encrypted_backup_log_pipe"
    mkfifo "$encrypted_backup_log_pipe"
    /opt/obs/bin/webobs-log-filter < "$encrypted_backup_log_pipe" &
    encrypted_backup_filter_pid=$!
    python3 /opt/webobs/bin/webobs-encrypted-backup schedule > "$encrypted_backup_log_pipe" 2>&1 &
    encrypted_backup_pid=$!
    sleep 0.2
    kill -0 "$encrypted_backup_pid" 2>/dev/null || fail "Encrypted backup scheduler exited during startup"
fi

/opt/obs/bin/webobsd "$@" &
webobsd_pid=$!
sleep 0.2
kill -0 "$webobsd_pid" 2>/dev/null || fail "webobsd exited during v2-M7 migration startup"
python3 "$upgrade_guard" commit --config-root /config/webobs || fail "v2-M7 migration commit failed"

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
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$nvr_pid" ] && ! kill -0 "$nvr_pid" 2>/dev/null; then
        echo "NVR service exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$nvr_filter_pid" ] && ! kill -0 "$nvr_filter_pid" 2>/dev/null; then
        echo "NVR log filter exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$camera_registry_pid" ] && ! kill -0 "$camera_registry_pid" 2>/dev/null; then
        echo "Camera Registry exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$camera_registry_filter_pid" ] && ! kill -0 "$camera_registry_filter_pid" 2>/dev/null; then
        echo "Camera Registry log filter exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$v2_client_control_pid" ] && ! kill -0 "$v2_client_control_pid" 2>/dev/null; then
        echo "v2 client control exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$v2_client_control_filter_pid" ] && ! kill -0 "$v2_client_control_filter_pid" 2>/dev/null; then
        echo "v2 client control log filter exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$events_pid" ] && ! kill -0 "$events_pid" 2>/dev/null; then
        echo "Event service exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$events_filter_pid" ] && ! kill -0 "$events_filter_pid" 2>/dev/null; then
        echo "Event service log filter exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$cluster_pid" ] && ! kill -0 "$cluster_pid" 2>/dev/null; then
        echo "Cluster service exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$cluster_filter_pid" ] && ! kill -0 "$cluster_filter_pid" 2>/dev/null; then
        echo "Cluster service log filter exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$node_agent_pid" ] && ! kill -0 "$node_agent_pid" 2>/dev/null; then
        echo "Node agent exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$detector_worker_pid" ] && ! kill -0 "$detector_worker_pid" 2>/dev/null; then
        echo "Detector worker exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$node_agent_filter_pid" ] && ! kill -0 "$node_agent_filter_pid" 2>/dev/null; then
        echo "Node agent log filter exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$archive_pid" ] && ! kill -0 "$archive_pid" 2>/dev/null; then
        echo "S3 archive service exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$encrypted_backup_pid" ] && ! kill -0 "$encrypted_backup_pid" 2>/dev/null; then
        echo "Encrypted backup scheduler exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$xvfb_pid" ] && ! kill -0 "$xvfb_pid" 2>/dev/null; then
        echo "software X display exited while webobsd was running" >&2
        exit_status=3
        terminate_child "$webobsd_pid"
        break
    fi
    if [ "$shutdown_requested" -eq 0 ] && [ -n "$weston_pid" ] && ! kill -0 "$weston_pid" 2>/dev/null; then
        echo "hardware EGL compositor exited while webobsd was running" >&2
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
if [ -n "$nvr_pid" ]; then
    wait "$nvr_pid" 2>/dev/null || true
fi
if [ -n "$nvr_filter_pid" ]; then
    wait "$nvr_filter_pid" 2>/dev/null || true
fi
if [ -n "$camera_registry_pid" ]; then
    wait "$camera_registry_pid" 2>/dev/null || true
fi
if [ -n "$camera_registry_filter_pid" ]; then
    wait "$camera_registry_filter_pid" 2>/dev/null || true
fi
if [ -n "$v2_client_control_pid" ]; then
    wait "$v2_client_control_pid" 2>/dev/null || true
fi
if [ -n "$v2_client_control_filter_pid" ]; then
    wait "$v2_client_control_filter_pid" 2>/dev/null || true
fi
if [ -n "$events_pid" ]; then
    wait "$events_pid" 2>/dev/null || true
fi
if [ -n "$events_filter_pid" ]; then
    wait "$events_filter_pid" 2>/dev/null || true
fi
if [ -n "$cluster_pid" ]; then
    wait "$cluster_pid" 2>/dev/null || true
fi
if [ -n "$cluster_filter_pid" ]; then
    wait "$cluster_filter_pid" 2>/dev/null || true
fi
if [ -n "$node_agent_pid" ]; then
    wait "$node_agent_pid" 2>/dev/null || true
fi
if [ -n "$node_agent_filter_pid" ]; then
    wait "$node_agent_filter_pid" 2>/dev/null || true
fi
if [ -n "$detector_worker_pid" ]; then
    wait "$detector_worker_pid" 2>/dev/null || true
fi
if [ -n "$archive_pid" ]; then
    wait "$archive_pid" 2>/dev/null || true
fi
if [ -n "$archive_filter_pid" ]; then
    wait "$archive_filter_pid" 2>/dev/null || true
fi
if [ -n "$encrypted_backup_pid" ]; then
    wait "$encrypted_backup_pid" 2>/dev/null || true
fi
if [ -n "$encrypted_backup_filter_pid" ]; then
    wait "$encrypted_backup_filter_pid" 2>/dev/null || true
fi
if [ -n "$mediamtx_log_pipe" ]; then
    rm -f -- "$mediamtx_log_pipe"
fi
if [ -n "$caddy_log_pipe" ]; then
    rm -f -- "$caddy_log_pipe"
fi
if [ -n "$nvr_log_pipe" ]; then
    rm -f -- "$nvr_log_pipe"
fi
if [ -n "$detector_worker_log" ]; then
    rm -f -- "$detector_worker_log"
fi
if [ -n "$camera_registry_log_pipe" ]; then
    rm -f -- "$camera_registry_log_pipe"
fi
if [ -n "$v2_client_control_log_pipe" ]; then
    rm -f -- "$v2_client_control_log_pipe"
fi
if [ -n "$events_log_pipe" ]; then
    rm -f -- "$events_log_pipe"
fi
if [ -n "$cluster_log_pipe" ]; then
    rm -f -- "$cluster_log_pipe"
fi
if [ -n "$node_agent_log_pipe" ]; then
    rm -f -- "$node_agent_log_pipe"
fi
if [ -n "$archive_log_pipe" ]; then
    rm -f -- "$archive_log_pipe"
fi
if [ -n "$encrypted_backup_log_pipe" ]; then
    rm -f -- "$encrypted_backup_log_pipe"
fi
if [ -n "$xvfb_pid" ]; then
    wait "$xvfb_pid" 2>/dev/null || true
fi
if [ -n "$weston_pid" ]; then
    wait "$weston_pid" 2>/dev/null || true
fi
if [ -n "$weston_log" ]; then
    rm -f -- "$weston_log"
fi
if [ -n "$weston_runtime" ]; then
    rm -rf -- "$weston_runtime"
fi
exit "$exit_status"
