#!/usr/bin/env bash
set -euo pipefail

release_gate=false
private_gate_command="${WEBOBS_PRIVATE_PWA_GATE_COMMAND:-}"
while (($#)); do
  case "$1" in
    --release-gate) release_gate=true ;;
    --private-gate-command)
      shift
      private_gate_command="${1:?--private-gate-command requires an absolute path}"
      ;;
    *) echo "usage: $0 [--release-gate] [--private-gate-command /absolute/path/run-gate.sh]" >&2; exit 64 ;;
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
  [[ "$private_gate_command" == /* ]] || {
    echo "an absolute private gate command is required with --release-gate" >&2
    exit 64
  }
  WEBOBS_PRIVATE_PWA_GATE_COMMAND="$private_gate_command" \
    python3 ./scripts/run-private-pwa-gate.py \
      --platform linux-wsl2-chromium --evidence-dir build/private-gates
fi

echo "WSL2 Linux shell and Chromium qualification passed; Windows owns Docker Desktop image gates."
