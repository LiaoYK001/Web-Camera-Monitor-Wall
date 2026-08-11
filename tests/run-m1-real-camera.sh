#!/bin/sh
set -eu

script_directory="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repository_root="$(CDPATH= cd -- "$script_directory/.." && pwd)"
product_compose_file="$repository_root/compose.yaml"
test_compose_file="$script_directory/compose.smoke.yaml"
recording_directory="$repository_root/recordings"
artifact_directory="$script_directory/artifacts"
env_file="${WEBOBS_ENV_FILE:-$repository_root/.env}"
duration_seconds="${WEBOBS_REAL_DURATION_SECONDS:-30}"
width="${WEBOBS_REAL_WIDTH:-1920}"
height="${WEBOBS_REAL_HEIGHT:-1080}"
fps="${WEBOBS_REAL_FPS:-30}"
bitrate_kbps="${WEBOBS_REAL_BITRATE_KBPS:-6000}"
connect_timeout_seconds="${WEBOBS_REAL_CONNECT_TIMEOUT_SECONDS:-20}"
rtsp_transport="${WEBOBS_REAL_RTSP_TRANSPORT:-tcp}"
skip_build="${WEBOBS_SKIP_BUILD:-0}"
use_synthetic_fixture="${WEBOBS_REAL_USE_SYNTHETIC:-0}"

dotenv_value() {
    name="$1"
    file="$2"
    sed -n "s/^[[:space:]]*${name}[[:space:]]*=[[:space:]]*//p" "$file" \
        | head -n 1 | sed 's/[[:space:]]*$//' \
        | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

if [ "$use_synthetic_fixture" = "1" ]; then
    rtsp_scheme="rtsp"
    rtsp_url="${rtsp_scheme}://mediamtx:8554/m0-test"
else
    case "$env_file" in
        /*) ;;
        *) env_file="$repository_root/$env_file" ;;
    esac
    if [ ! -f "$env_file" ]; then
        echo "Local environment file not found. Copy .env.example to .env and edit it before running this test." >&2
        exit 2
    fi
    rtsp_url="$(dotenv_value WEBOBS_RTSP_URL "$env_file")"
    example_url="$(dotenv_value WEBOBS_RTSP_URL "$repository_root/.env.example")"
    if [ -z "$rtsp_url" ]; then
        echo "WEBOBS_RTSP_URL is missing from the selected environment file." >&2
        exit 2
    fi
    if [ "$rtsp_url" = "$example_url" ]; then
        echo "WEBOBS_RTSP_URL still contains the .env.example placeholder." >&2
        exit 2
    fi
    case "$rtsp_url" in
        *'${'*) echo "The M1 real-camera runner requires a literal WEBOBS_RTSP_URL." >&2; exit 2 ;;
    esac
fi
case "$rtsp_url" in
    rtsp://*|rtsps://*) ;;
    *) echo "WEBOBS_RTSP_URL must be an absolute rtsp:// or rtsps:// URI." >&2; exit 2 ;;
esac

validate_integer() {
    value="$1"; minimum="$2"; maximum="$3"; label="$4"
    case "$value" in
        ''|*[!0-9]*) echo "$label must be an integer." >&2; exit 2 ;;
    esac
    if [ "$value" -lt "$minimum" ] || [ "$value" -gt "$maximum" ]; then
        echo "$label must be between $minimum and $maximum." >&2
        exit 2
    fi
}
validate_integer "$duration_seconds" 10 3600 "WEBOBS_REAL_DURATION_SECONDS"
validate_integer "$width" 16 8192 "WEBOBS_REAL_WIDTH"
validate_integer "$height" 16 8192 "WEBOBS_REAL_HEIGHT"
validate_integer "$fps" 1 120 "WEBOBS_REAL_FPS"
validate_integer "$bitrate_kbps" 50 100000 "WEBOBS_REAL_BITRATE_KBPS"
validate_integer "$connect_timeout_seconds" 1 300 "WEBOBS_REAL_CONNECT_TIMEOUT_SECONDS"
if [ "$use_synthetic_fixture" != "1" ] && [ "$duration_seconds" -lt 30 ]; then
    echo "The real-camera M1 acceptance duration must be at least 30 seconds." >&2
    exit 2
fi
if [ $((width % 2)) -ne 0 ] || [ $((height % 2)) -ne 0 ]; then
    echo "WEBOBS_REAL_WIDTH and WEBOBS_REAL_HEIGHT must both be even." >&2
    exit 2
fi
case "$rtsp_transport" in
    tcp|udp) ;;
    *) echo "WEBOBS_REAL_RTSP_TRANSPORT must be tcp or udp." >&2; exit 2 ;;
esac

"$script_directory/run-public-audit.sh"
command -v docker >/dev/null 2>&1
docker compose version >/dev/null
mkdir -p "$recording_directory" "$artifact_directory"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
if [ "$use_synthetic_fixture" = "1" ]; then
    recording_prefix="m1-real-camera-rehearsal"
else
    recording_prefix="m1-real-camera"
fi
recording_name="$recording_prefix-$timestamp.mp4"
recording_path="$recording_directory/$recording_name"
log_path="$artifact_directory/$recording_prefix-$timestamp.log"
project_name="webobs-m1-real-$(printf '%s' "$timestamp" | tr '[:upper:]' '[:lower:]')"

export WEBOBS_RTSP_URL="$rtsp_url"
export WEBOBS_REAL_RECORDING_NAME="$recording_name"
export WEBOBS_REAL_WIDTH="$width"
export WEBOBS_REAL_HEIGHT="$height"
export WEBOBS_REAL_FPS="$fps"
export WEBOBS_REAL_BITRATE_KBPS="$bitrate_kbps"
export WEBOBS_REAL_CONNECT_TIMEOUT_SECONDS="$connect_timeout_seconds"
export WEBOBS_REAL_RTSP_TRANSPORT="$rtsp_transport"

compose() {
    docker compose -p "$project_name" -f "$test_compose_file" "$@"
}

container_id=""
logs_saved=0
leak_detected=0
save_logs() {
    if [ "$logs_saved" -eq 1 ] || [ -z "$container_id" ]; then
        return
    fi
    set +e
    raw_output="$(docker logs "$container_id" 2>&1)"
    set -e
    url_authority="${rtsp_url#*://}"
    url_authority="${url_authority%%/*}"
    userinfo=""
    case "$url_authority" in *@*) userinfo="${url_authority%@*}" ;; esac
    unmasked_urls="$(printf '%s\n' "$raw_output" \
        | grep -Eo 'rtsps?://[^[:space:]]+@' \
        | grep -Ev '^rtsps?://\*{3}:\*{3}@' || true)"
    if [ -n "$unmasked_urls" ]; then leak_detected=1; fi
    if [ -n "$userinfo" ]; then
        case "$raw_output" in *"$userinfo"*) leak_detected=1 ;; esac
    fi
    umask 077
    printf '%s\n' "$raw_output" \
        | sed -E 's#rtsps?://[^[:space:]''"]+#rtsp://<redacted>#g' >"$log_path"
    logs_saved=1
}
cleanup() {
    save_logs || true
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

if [ "$skip_build" != "1" ]; then
    docker compose -f "$product_compose_file" build webobs
    docker compose -f "$test_compose_file" build validator
    if [ "$use_synthetic_fixture" = "1" ]; then
        docker compose -f "$test_compose_file" build mediamtx
    fi
fi

if [ "$use_synthetic_fixture" = "1" ]; then
    compose up --no-build -d mediamtx fixture
    fixture_deadline=$(( $(date +%s) + 30 ))
    while ! compose logs --no-color mediamtx 2>/dev/null \
        | grep -F '[path m0-test] stream is available and online' >/dev/null
    do
        if [ "$(date +%s)" -ge "$fixture_deadline" ]; then
            echo "Synthetic RTSP fixture did not publish a stream within 30 seconds." >&2
            exit 1
        fi
        sleep 1
    done
fi
compose up --no-build -d --no-deps webobs-real-control
container_id="$(compose ps -q webobs-real-control)"
test -n "$container_id"

compose run --rm --no-deps real-control-client
sleep "$duration_seconds"
compose stop webobs-real-control
exit_code="$(docker inspect --format '{{.State.ExitCode}}' "$container_id")"
if [ "$exit_code" != "0" ]; then
    echo "The M1 real-camera process returned a non-zero status." >&2
    exit 1
fi

save_logs
if [ "$leak_detected" -eq 1 ]; then
    echo "Credential redaction failed. Raw output was suppressed; inspect only the endpoint-redacted log at $log_path." >&2
    exit 1
fi
if [ ! -s "$recording_path" ]; then
    echo "The M1 real-camera recording is missing or empty." >&2
    exit 1
fi

docker run --rm \
    --mount "type=bind,source=$recording_directory,target=/artifacts,readonly" \
    --entrypoint //usr/local/bin/probe-recording \
    -e "TEST_RECORDING=//artifacts/$recording_name" \
    -e "TEST_DIMENSIONS=${width}x${height}" \
    -e "TEST_FRAME_RATE=$fps/1" \
    -e "TEST_MIN_DURATION=$duration_seconds" \
    -e "TEST_MAX_DURATION=$((duration_seconds + 30))" \
    -e TEST_REJECT_BLACKOUT=1 \
    -e TEST_BLACKOUT_YAVG_MAX=16.5 \
    webobs-m0-rtsp-fixture:local

if [ "$use_synthetic_fixture" = "1" ]; then mode="synthetic rehearsal"; else mode="real camera"; fi
echo "M1 $mode acceptance passed. Recording: $recording_path"
echo "Endpoint-redacted local log (do not attach publicly): $log_path"
