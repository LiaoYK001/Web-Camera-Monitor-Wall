#!/usr/bin/env bash
set -euo pipefail

release_gate=false
private_gate_command="${WEBOBS_PRIVATE_PWA_GATE_COMMAND:-}"
v3_milestone=""
private_v3_gate_command="${WEBOBS_PRIVATE_V3_GATE_COMMAND:-}"
while (($#)); do
  case "$1" in
    --release-gate) release_gate=true ;;
    --private-gate-command)
      shift
      private_gate_command="${1:?--private-gate-command requires an absolute path}"
      ;;
    --v3-milestone)
      shift
      v3_milestone="${1:?--v3-milestone requires v3-M1 or v3-M2}"
      [[ "$v3_milestone" == v3-M1 || "$v3_milestone" == v3-M2 ]] || {
        echo "--v3-milestone must be v3-M1 or v3-M2" >&2; exit 64;
      }
      ;;
    --private-v3-gate-command)
      shift
      private_v3_gate_command="${1:?--private-v3-gate-command requires an absolute path}"
      ;;
    *) echo "usage: $0 [--release-gate --private-gate-command /absolute/path/run-gate.sh] [--v3-milestone v3-M1|v3-M2 --private-v3-gate-command /absolute/path/run-v3-gate.sh]" >&2; exit 64 ;;
  esac
  shift
done

repository="$(git rev-parse --show-toplevel)"
cd "$repository"
for command in git node pnpm python3; do
  command -v "$command" >/dev/null || { echo "required command is unavailable: $command" >&2; exit 69; }
done
chromium_binary="$(command -v chromium || command -v chromium-browser || true)"
[[ -n "$chromium_binary" ]] || { echo "required command is unavailable: chromium" >&2; exit 69; }
export WEBOBS_PLAYWRIGHT_CHROMIUM_EXECUTABLE="$chromium_binary"

./tests/run-public-audit.sh
python3 ./clients/tests/test_release_workflow_policy.py
python3 ./clients/tests/test_local_gate_receipts.py
(
  cd web
  rm -rf node_modules
  pnpm install --frozen-lockfile
  pnpm typecheck
  pnpm test:iwa
  pnpm build
  pnpm test:local
  pnpm exec playwright test --project=chromium
)
if [[ "$release_gate" == true ]]; then
  [[ -z "$v3_milestone" ]] || { echo "--release-gate and --v3-milestone are mutually exclusive" >&2; exit 64; }
  [[ "$private_gate_command" == /* ]] || {
    echo "an absolute private gate command is required with --release-gate" >&2
    exit 64
  }
  WEBOBS_PRIVATE_PWA_GATE_COMMAND="$private_gate_command" \
    python3 ./scripts/run-private-pwa-gate.py \
    --platform linux-wsl2-chromium --evidence-dir build/private-gates
fi

if [[ -n "$v3_milestone" ]]; then
  [[ "$private_v3_gate_command" == /* ]] || {
    echo "an absolute private v3 gate command is required with --v3-milestone" >&2
    exit 64
  }
  WEBOBS_PRIVATE_V3_GATE_COMMAND="$private_v3_gate_command" \
    python3 ./scripts/run-private-v3-gate.py \
      --milestone "$v3_milestone" --platform linux \
      --command "$private_v3_gate_command" --evidence-dir build/private-gates
fi

echo "WSL2 Linux shell and Chromium qualification passed; Windows owns Docker Desktop image gates."
