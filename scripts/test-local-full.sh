#!/usr/bin/env bash
set -euo pipefail

image="${WEBOBS_DEV_IMAGE:-webobs:dev}"
include_real_media=false
long=false
allow_partial=false

usage() {
  cat <<'EOF'
Usage: scripts/test-local-full.sh [options]
  --image IMAGE          existing local product image (default: webobs:dev)
  --include-real-media   run private RTSP/MJPEG checks when env vars are set
  --long                 run M7 8/16/32 x 900-second and fault gates
  --allow-partial        allow Linux without pwsh to run the shell subset only
EOF
}

while (($#)); do
  case "$1" in
    --image) shift; image="${1:?--image requires a value}" ;;
    --include-real-media) include_real_media=true ;;
    --long) long=true ;;
    --allow-partial) allow_partial=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 64 ;;
  esac
  shift
done

repo="$(git rev-parse --show-toplevel)"
cd "$repo"
[[ "$(git branch --show-current)" = dev ]] || { echo 'full local validation is restricted to branch dev' >&2; exit 65; }
for command in docker python3 pnpm; do
  command -v "$command" >/dev/null || { echo "required command is unavailable: $command" >&2; exit 69; }
done
docker image inspect "$image" >/dev/null 2>&1 || {
  echo "local test image '$image' is unavailable; build it separately or pass --image" >&2; exit 66;
}

if command -v pwsh >/dev/null; then
  pwsh_args=(-NoProfile -File "$repo/scripts/test-local-full.ps1" -Image "$image")
  [[ "$include_real_media" = true ]] && pwsh_args+=(-IncludeRealMedia)
  [[ "$long" = true ]] && pwsh_args+=(-Long)
  pwsh "${pwsh_args[@]}"
  exit $?
fi

if [[ "$allow_partial" != true ]]; then
  echo 'pwsh 7 is required for the complete cross-platform suite; use --allow-partial only for shell/Python/Web checks' >&2
  exit 69
fi

old_image_id="$(docker image inspect webobs:m0 --format '{{.Id}}' 2>/dev/null || true)"
had_old_image=false
[[ -n "$old_image_id" ]] && had_old_image=true
export WEBOBS_IMAGE="$image" WEBOBS_TEST_IMAGE="$image"
docker tag "$image" webobs:m0
cleanup() {
  if [[ "$had_old_image" = true ]]; then docker tag "$old_image_id" webobs:m0 >/dev/null; else docker image rm webobs:m0 >/dev/null 2>&1 || true; fi
  unset WEBOBS_IMAGE WEBOBS_TEST_IMAGE
}
trap cleanup EXIT INT TERM

./tests/run-public-audit.sh
python3 clients/scripts/verify_dependency_lock.py
python3 clients/tests/test_release_workflow_policy.py
python3 -m unittest discover -s tests -p 'test_*.py'
(cd web && pnpm install --frozen-lockfile && pnpm typecheck && pnpm test:iwa && pnpm build && pnpm test:local)
WEBOBS_SKIP_BUILD=1 ./tests/run-smoke.sh
if [[ "$long" = true ]]; then
  for count in 8 16 32; do WEBOBS_M7_CAMERA_COUNT="$count" WEBOBS_M7_GATE_SECONDS=900 ./tests/m7/run-gate.sh; done
  ./tests/m7/run-fault-gate.sh
else
  echo 'M7 8/16/32 x 900-second and fault gates not run; use --long.'
fi
echo "Full local shell/Python/Web validation passed for $image. No image was built or pushed."
