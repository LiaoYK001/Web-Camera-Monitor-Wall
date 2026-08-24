#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$repository_root/tests/compose.v2-true-direct.yaml"
project="webobsv2direct$$"
export COMPOSE_PROJECT_NAME="$project"

cleanup() {
  docker compose -f "$compose_file" down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker image inspect "${WEBOBS_TEST_IMAGE:-webobs:v2-m1-dev}" >/dev/null
docker compose -f "$compose_file" up --detach --build

webobs_id="$(docker compose -f "$compose_file" ps --all --quiet webobs)"
[[ -n "$webobs_id" ]]

probe_services=(v2-probe native-rtsp-h264 native-rtsp-h265 native-mjpeg native-hls)
for service in "${probe_services[@]}"; do
  probe_id="$(docker compose -f "$compose_file" ps --all --quiet "$service")"
  [[ -n "$probe_id" ]]
  for _ in $(seq 1 240); do
    probe_state="$(docker inspect --format '{{.State.Status}}' "$probe_id")"
    [[ "$probe_state" == exited ]] && break
    [[ "$probe_state" == running || "$probe_state" == created ]] || break
    sleep 1
  done
  docker compose -f "$compose_file" logs --no-color "$service"
  [[ "$(docker inspect --format '{{.State.Status}}' "$probe_id")" == exited ]]
  [[ "$(docker inspect --format '{{.State.ExitCode}}' "$probe_id")" == 0 ]]
done

network_names="$(docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{"\n"}}{{end}}' "$webobs_id")"
[[ "$network_names" == "${project}_control" ]]

if docker exec "$webobs_id" getent hosts camera >/dev/null 2>&1; then
  echo "True Direct isolation failed: the server can resolve the camera fixture" >&2
  exit 1
fi
if docker exec "$webobs_id" sh -c "pgrep -x ffmpeg || pgrep -x mediamtx || pgrep -x obs-ffmpeg-mux" >/dev/null 2>&1; then
  echo "True Direct isolation failed: a server media helper remained active" >&2
  exit 1
fi
docker compose -f "$compose_file" logs --no-color webobs | grep -F \
  "Gateway Direct-only mode is active; OBS decode, scene composition, and encoding are not initialized" >/dev/null
if docker compose -f "$compose_file" logs --no-color webobs | grep -F "rtsp://camera:8554" >/dev/null; then
  echo "True Direct isolation failed: the camera endpoint appeared in server logs" >&2
  exit 1
fi

echo "v2 deterministic True Direct gate passed: the production client pipeline decoded H.264/H.265 RTSP, Server Push MJPEG and HLS; the control server had no camera network or media helper. WHEP remains an exact-runtime release gate."
