#!/bin/sh
set -eu

here="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
runtime="${WEBOBS_CONTAINER_RUNTIME:-docker}"
image="${WEBOBS_IMAGE:-webobs:m7-candidate}"
duration="${WEBOBS_M7_GATE_SECONDS:-900}"
export WEBOBS_M7_CAMERA_COUNT="${WEBOBS_M7_CAMERA_COUNT:-8}"
case "$runtime" in docker|podman) ;; *) echo "WEBOBS_CONTAINER_RUNTIME must be docker or podman" >&2; exit 2;; esac
case "$duration" in ''|*[!0-9]*) echo "WEBOBS_M7_GATE_SECONDS must be an integer" >&2; exit 2;; esac
[ "$duration" -ge 60 ] && [ "$duration" -le 21600 ] || {
    echo "WEBOBS_M7_GATE_SECONDS must be between 60 and 21600" >&2; exit 2;
}

export WEBOBS_IMAGE="$image"
compose() { "$runtime" compose -f "$here/compose.yaml" "$@"; }
# Materialize placeholder env files so Compose can parse a first-time `down`,
# then recreate the bounded fixture from a clean state for deterministic runs.
"$here/generate-fixture.sh"
compose down --volumes --remove-orphans >/dev/null 2>&1 || true
WEBOBS_M7_RESET=true "$here/generate-fixture.sh"
cleanup() { [ "${WEBOBS_M7_KEEP:-false}" = true ] || compose down --volumes --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM
compose up -d controller mediamtx publisher minio mosquitto
python_bin=python3
python3 --version >/dev/null 2>&1 || python_bin=python
bootstrap="$here/bootstrap-cluster.py"
case "$(uname -s)" in MINGW*|MSYS*) bootstrap="$(cygpath -w "$bootstrap")";; esac
"$python_bin" "$bootstrap"

sleep "$duration"
compose ps
verify="$here/verify-scale.py"
case "$(uname -s)" in MINGW*|MSYS*) verify="$(cygpath -w "$verify")";; esac
receipt_argument=""
[ "$duration" -lt 900 ] || receipt_argument="--write-receipt"
# shellcheck disable=SC2086
"$python_bin" "$verify" --camera-count "$WEBOBS_M7_CAMERA_COUNT" \
    --duration-seconds "$duration" $receipt_argument
echo "M7 ${WEBOBS_M7_CAMERA_COUNT}-camera mixed-load gate passed for ${duration}s."
