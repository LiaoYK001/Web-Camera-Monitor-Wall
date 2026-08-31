#!/bin/sh
set -eu

here="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
runtime="${WEBOBS_CONTAINER_RUNTIME:-docker}"
export WEBOBS_IMAGE="${WEBOBS_IMAGE:-webobs:m7-candidate}"
export WEBOBS_M7_CAMERA_COUNT=8
case "$runtime" in docker|podman) ;; *) echo "WEBOBS_CONTAINER_RUNTIME must be docker or podman" >&2; exit 2;; esac
compose() { "$runtime" compose -f "$here/compose.yaml" "$@"; }

"$here/generate-fixture.sh"
compose down --volumes --remove-orphans >/dev/null 2>&1 || true
WEBOBS_M7_RESET=true "$here/generate-fixture.sh"
cleanup() { [ "${WEBOBS_M7_KEEP:-false}" = true ] || compose down --volumes --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM
compose up -d controller mediamtx publisher minio mosquitto
python_bin=python3
python3 --version >/dev/null 2>&1 || python_bin=python
bootstrap="$here/bootstrap-cluster.py"
faults="$here/fault-injection.py"
case "$(uname -s)" in
    MINGW*|MSYS*) bootstrap="$(cygpath -w "$bootstrap")"; faults="$(cygpath -w "$faults")";;
esac
"$python_bin" "$bootstrap"
sleep 25
"$python_bin" "$faults"
