#!/bin/sh
set -eu

script_directory="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repository_root="$(CDPATH= cd -- "$script_directory/.." && pwd)"
compose_file="$script_directory/compose.smoke.yaml"
artifact_directory="$script_directory/artifacts"

mkdir -p "$artifact_directory"
rm -f "$artifact_directory/smoke.mp4"

cleanup() {
    docker compose -f "$compose_file" down --volumes --remove-orphans
}
trap cleanup EXIT INT TERM

cd "$repository_root"
docker compose -f "$compose_file" down --volumes --remove-orphans
docker compose -f "$compose_file" up --build --abort-on-container-exit --exit-code-from webobs webobs
docker compose -f "$compose_file" run --rm validator
"$script_directory/run-contracts.sh" "$compose_file" "$artifact_directory"
