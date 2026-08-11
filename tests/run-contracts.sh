#!/bin/sh
set -eu

script_directory="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
compose_file="${1:-$script_directory/compose.smoke.yaml}"
artifact_directory="${2:-$script_directory/artifacts}"
signal_container="webobs-m0-signal-test"

expect_exit() {
    expected="$1"
    label="$2"
    shift 2
    set +e
    command_output="$("$@" 2>&1)"
    status=$?
    set -e
    if [ "$status" -ne "$expected" ]; then
        printf '%s\n' "$command_output" >&2
        echo "$label: expected exit $expected, got $status" >&2
        exit 1
    fi
    echo "$label: exit $status verified"
    CONTRACT_OUTPUT="$command_output"
}

cleanup_signal_container() {
    docker rm -f "$signal_container" >/dev/null 2>&1 || true
}

mkdir -p "$artifact_directory"
rm -f "$artifact_directory/signal.mp4"
rm -f "$artifact_directory"/.signal.mp4.webobsd-*.mkv
cleanup_signal_container
trap cleanup_signal_container EXIT INT TERM

expect_exit 2 "missing URL" \
    docker run --rm --entrypoint /opt/obs/bin/webobsd -e WEBOBS_RTSP_URL= webobs:m0

expect_exit 5 "missing output directory" \
    docker run --rm --entrypoint /opt/obs/bin/webobsd \
        -e WEBOBS_RTSP_URL=rtsp://camera.invalid/live \
        -e WEBOBS_OUTPUT=/directory-that-does-not-exist/capture.mp4 \
        webobs:m0

expect_exit 4 "unreachable RTSP" \
    docker run --rm \
        -e WEBOBS_RTSP_URL=rtsp://test-user:supersecret@127.0.0.1:65534/unreachable \
        -e WEBOBS_OUTPUT=/recordings/unreachable.mp4 \
        -e WEBOBS_CONNECT_TIMEOUT_SECONDS=1 \
        -e WEBOBS_LOG_LEVEL=debug \
        webobs:m0
if printf '%s' "$CONTRACT_OUTPUT" | grep -F 'test-user' >/dev/null 2>&1 || \
   printf '%s' "$CONTRACT_OUTPUT" | grep -F 'supersecret' >/dev/null 2>&1; then
    echo "credential redaction: clear-text RTSP credentials leaked" >&2
    exit 1
fi
printf '%s' "$CONTRACT_OUTPUT" | grep -F 'rtsp://***:***@127.0.0.1' >/dev/null
echo "credential redaction: verified"

expect_exit 5 "existing output refusal" \
    docker run --rm --entrypoint /opt/obs/bin/webobsd \
        -v "$artifact_directory:/artifacts" \
        -e WEBOBS_RTSP_URL=rtsp://camera.invalid/live \
        -e WEBOBS_OUTPUT=/artifacts/smoke.mp4 \
        webobs:m0

docker compose -f "$compose_file" up -d mediamtx fixture
docker compose -f "$compose_file" run --detach --name "$signal_container" \
    -e WEBOBS_OUTPUT=/artifacts/signal.mp4 \
    -e WEBOBS_DURATION_SECONDS=0 \
    -e WEBOBS_CONNECT_TIMEOUT_SECONDS=30 \
    webobs >/dev/null

started=0
attempt=0
while [ "$attempt" -lt 60 ]; do
    logs="$(docker logs "$signal_container" 2>&1 || true)"
    if printf '%s' "$logs" | grep -F 'Recording started:' >/dev/null; then
        started=1
        break
    fi
    if [ "$(docker inspect -f '{{.State.Running}}' "$signal_container")" != "true" ]; then
        break
    fi
    attempt=$((attempt + 1))
    sleep 1
done
if [ "$started" -ne 1 ]; then
    docker logs "$signal_container" >&2 || true
    echo "SIGTERM test: recording did not start" >&2
    exit 1
fi

sleep 3
docker stop --timeout 20 "$signal_container" >/dev/null
signal_exit="$(docker inspect -f '{{.State.ExitCode}}' "$signal_container")"
if [ "$signal_exit" -ne 0 ]; then
    docker logs "$signal_container" >&2 || true
    echo "SIGTERM test: expected exit 0, got $signal_exit" >&2
    exit 1
fi
cleanup_signal_container
docker compose -f "$compose_file" run --rm \
    -e TEST_RECORDING=/artifacts/signal.mp4 \
    -e TEST_MIN_DURATION=2 \
    -e TEST_MAX_DURATION=10 \
    validator
echo "SIGTERM test: graceful MP4 finalization verified"
