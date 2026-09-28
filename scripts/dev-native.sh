#!/usr/bin/env bash
set -euo pipefail
command -v python3 >/dev/null || { echo '[ERROR] 请先安装 Python 3.12+' >&2; exit 1; }
exec python3 "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/dev-native.py" "$@"
