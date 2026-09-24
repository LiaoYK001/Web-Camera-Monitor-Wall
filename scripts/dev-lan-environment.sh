#!/usr/bin/env bash
# dev-lan-environment.sh — 局域网联调入口 / LAN co-dev entry.
# 与 scripts/dev.sh 相同流程，额外开启 LAN 端口转发：
#   Vite 监听 0.0.0.0，/api 代理把 Host/Origin 改写回 127.0.0.1；
#   后端仍只绑定本机回环。局域网成员访问 http://<本机IPv4>:<端口>/。
# Same pipeline as scripts/dev.sh, plus a LAN port-forward:
#   Vite binds 0.0.0.0 and the /api proxy rewrites Host/Origin back to
#   loopback so the backend stays local-only. LAN peers use
#   http://<host-IPv4>:<port>/.
set -euo pipefail
command -v node >/dev/null || { echo '[ERROR] 请先安装 Node.js 24 LTS，再重新打开终端。' >&2; exit 1; }

lan_host=''
args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --lan-host)
      shift
      lan_host="${1:?--lan-host requires a dotted IPv4 address}"
      ;;
    -h|--help)
      args+=(--help)
      shift
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done

if [ -n "$lan_host" ] && ! printf '%s' "$lan_host" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$'; then
  echo '[ERROR] --lan-host 必须是点分 IPv4（例如 192.168.1.20）。' >&2
  exit 1
fi

echo '[WebOBS] LAN mode：仅限受信任局域网联调，不要对公网暴露 / Trusted LAN only; never expose to the public Internet.' >&2

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
launch_args=(--lan)
if [ -n "$lan_host" ]; then
  launch_args+=(--lan-host "$lan_host")
fi
exec node "${script_dir}/dev.mjs" "${launch_args[@]}" "${args[@]}"
