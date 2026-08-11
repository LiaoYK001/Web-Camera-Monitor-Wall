#!/bin/sh
set -eu

script_directory="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repository_root="$(CDPATH= cd -- "$script_directory/.." && pwd)"
compose_file="$repository_root/compose.yaml"
smoke_compose_file="$script_directory/compose.smoke.yaml"
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
placeholder_url="rtsp://user:password@192.168.1.10:554/stream"

case "$env_file" in
    /*) ;;
    *) env_file="$repository_root/$env_file" ;;
esac

if [ ! -f "$env_file" ]; then
    echo "Local environment file not found. Copy .env.example to .env and edit it before running this test." >&2
    exit 2
fi

rtsp_url="$(sed -n 's/^[[:space:]]*WEBOBS_RTSP_URL[[:space:]]*=[[:space:]]*//p' "$env_file" \
    | head -n 1 \
    | sed 's/[[:space:]]*$//')"
case "$rtsp_url" in
    \"*\") rtsp_url="${rtsp_url#\"}"; rtsp_url="${rtsp_url%\"}" ;;
    \'*\') rtsp_url="${rtsp_url#\'}"; rtsp_url="${rtsp_url%\'}" ;;
esac
if [ -z "$rtsp_url" ]; then
    echo "WEBOBS_RTSP_URL is missing from the selected environment file." >&2
    exit 2
fi
if [ "$rtsp_url" = "$placeholder_url" ]; then
    echo "WEBOBS_RTSP_URL still contains the .env.example placeholder." >&2
    exit 2
fi
case "$rtsp_url" in
    *'${'*)
        echo "The real-camera runner requires WEBOBS_RTSP_URL to be a literal value, not an interpolation." >&2
        exit 2
        ;;
    rtsp://*|rtsps://*) ;;
    *)
        echo "WEBOBS_RTSP_URL must be an absolute rtsp:// or rtsps:// URI." >&2
        exit 2
        ;;
esac

validate_integer() {
    value="$1"
    minimum="$2"
    maximum="$3"
    label="$4"
    case "$value" in
        ''|*[!0-9]*) echo "$label must be an integer." >&2; exit 2 ;;
    esac
    if [ "$value" -lt "$minimum" ] || [ "$value" -gt "$maximum" ]; then
        echo "$label must be between $minimum and $maximum." >&2
        exit 2
    fi
}

validate_integer "$duration_seconds" 30 3600 "WEBOBS_REAL_DURATION_SECONDS"
validate_integer "$width" 16 8192 "WEBOBS_REAL_WIDTH"
validate_integer "$height" 16 8192 "WEBOBS_REAL_HEIGHT"
validate_integer "$fps" 1 120 "WEBOBS_REAL_FPS"
validate_integer "$bitrate_kbps" 50 100000 "WEBOBS_REAL_BITRATE_KBPS"
validate_integer "$connect_timeout_seconds" 1 300 "WEBOBS_REAL_CONNECT_TIMEOUT_SECONDS"
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
recording_name="m0-real-camera-$timestamp.mp4"
recording_path="$recording_directory/$recording_name"
log_path="$artifact_directory/m0-real-camera-$timestamp.log"

if [ "$skip_build" != "1" ]; then
    docker compose --env-file "$env_file" -f "$compose_file" build webobs
    docker compose -f "$smoke_compose_file" build validator
fi

set +e
raw_output="$(
    docker compose --env-file "$env_file" -f "$compose_file" run --rm -T \
        -e "WEBOBS_OUTPUT=/recordings/$recording_name" \
        -e "WEBOBS_DURATION_SECONDS=$duration_seconds" \
        -e "WEBOBS_WIDTH=$width" \
        -e "WEBOBS_HEIGHT=$height" \
        -e "WEBOBS_FPS=$fps" \
        -e "WEBOBS_BITRATE_KBPS=$bitrate_kbps" \
        -e "WEBOBS_CONNECT_TIMEOUT_SECONDS=$connect_timeout_seconds" \
        -e "WEBOBS_RTSP_TRANSPORT=$rtsp_transport" \
        webobs 2>&1
)"
record_status=$?
set -e

unmasked_urls="$(printf '%s\n' "$raw_output" \
    | grep -Eo 'rtsps?://[^[:space:]]+@' \
    | grep -Ev '^rtsps?://\*{3}:\*{3}@' || true)"
url_authority="${rtsp_url#*://}"
url_authority="${url_authority%%/*}"
userinfo=""
case "$url_authority" in
    *@*) userinfo="${url_authority%@*}" ;;
esac
userinfo_leaked=0
if [ -n "$userinfo" ]; then
    case "$raw_output" in
        *"$userinfo"*) userinfo_leaked=1 ;;
    esac
fi

if [ -n "$unmasked_urls" ] || [ "$userinfo_leaked" -eq 1 ]; then
    umask 077
    printf '%s\n' "Credential redaction failed; raw output was suppressed." >"$log_path"
    echo "Credential redaction failed. Raw output was suppressed; sanitized log: $log_path" >&2
    exit 1
fi

umask 077
printf '%s\n' "$raw_output" \
    | sed -E 's#(rtsps?://)[^[:space:]/@]+(:[^[:space:]/@]*)?@#\1***:***@#g' \
    | tee "$log_path"

if [ "$record_status" -ne 0 ]; then
    echo "Real-camera recording failed with exit code $record_status. Sanitized log: $log_path" >&2
    exit "$record_status"
fi
if [ ! -s "$recording_path" ]; then
    echo "The real-camera recording is missing or empty." >&2
    exit 1
fi

minimum_duration=$((duration_seconds - 2))
if [ "$minimum_duration" -lt 28 ]; then
    minimum_duration=28
fi
maximum_duration=$((duration_seconds + 10))
docker run --rm \
    --mount "type=bind,source=$recording_directory,target=/artifacts,readonly" \
    --entrypoint /usr/local/bin/probe-recording \
    -e "TEST_RECORDING=/artifacts/$recording_name" \
    -e "TEST_DIMENSIONS=${width}x${height}" \
    -e "TEST_FRAME_RATE=$fps/1" \
    -e "TEST_MIN_DURATION=$minimum_duration" \
    -e "TEST_MAX_DURATION=$maximum_duration" \
    webobs-m0-rtsp-fixture:local

echo "M0 real-camera acceptance passed. Recording: $recording_path"
echo "Sanitized local log (do not attach publicly): $log_path"
