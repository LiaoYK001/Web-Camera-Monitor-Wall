#!/usr/bin/env bash
set -euo pipefail
command -v node >/dev/null || { echo '[ERROR] 请先安装 Node.js 24 LTS，再重新打开终端。' >&2; exit 1; }
exec node "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/dev.mjs" "$@"
