#!/bin/sh
set -eu

script_directory="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repository_root="$(CDPATH= cd -- "$script_directory/.." && pwd)"
compose_file="$script_directory/compose.smoke.yaml"
artifact_directory="$script_directory/artifacts"
build_option="--build"
if [ "${WEBOBS_SKIP_BUILD:-0}" = "1" ]; then
    build_option="--no-build"
fi

"$script_directory/run-public-audit.sh"

mkdir -p "$artifact_directory"
rm -f "$artifact_directory/smoke.mp4"
rm -f "$artifact_directory/multi.mp4"
rm -f "$artifact_directory"/.smoke.mp4.webobsd-*.mkv

cleanup() {
    docker compose -f "$compose_file" down --volumes --remove-orphans
}
trap cleanup EXIT INT TERM

cd "$repository_root"
docker compose -f "$compose_file" down --volumes --remove-orphans
docker compose -f "$compose_file" up "$build_option" --abort-on-container-exit --exit-code-from webobs webobs
docker compose -f "$compose_file" run --rm validator
docker compose -f "$compose_file" up "$build_option" --abort-on-container-exit --exit-code-from webobs-multi webobs-multi
docker compose -f "$compose_file" run --rm \
    -e TEST_RECORDING=/artifacts/multi.mp4 \
    -e TEST_REQUIRE_PILLARBOX=0 \
    -e TEST_REQUIRE_TWO_UP=1 \
    validator
"$script_directory/run-contracts.sh" "$compose_file" "$artifact_directory"
