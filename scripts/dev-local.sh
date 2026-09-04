#!/usr/bin/env bash
set -euo pipefail

# Fast local dev helper for the protected dev branch. It never tags, pushes or
# publishes an image. Private endpoints must remain in a Git-ignored .env or in
# the current process environment.

action="start"
no_build=false
frontend=false
full=false
include_real_media=false
long=false
open_browser=false
allow_non_dev=false
image="${WEBOBS_DEV_IMAGE:-webobs:dev}"
frontend_port="${WEBOBS_DEV_FRONTEND_PORT:-5173}"
tail_lines="${WEBOBS_DEV_LOG_TAIL:-200}"
env_file="${WEBOBS_DEV_ENV_FILE:-.env}"

usage() {
  cat <<'EOF'
Usage: scripts/dev-local.sh [action] [options]

Actions: start stop restart status logs debug frontend test build hotfix shell
Options:
  --no-build          reuse the local image for start/restart
  --frontend          start Vite in the background with start/restart
  --full              run the complete local no-build suite against --image
  --include-real-media include private RTSP/MJPEG checks when env vars are set
  --long              run M7 8/16/32 x 900-second and fault gates
  --open              open the local frontend URL when supported
  --allow-non-dev     allow an explicit experiment outside branch dev
  --image IMAGE       local image tag (default: webobs:dev)
  --frontend-port N   Vite port (default: 5173)
  --tail N            log lines (default: 200)
  --env-file PATH     private env file (default: .env)
EOF
}

while (($#)); do
  case "$1" in
    start|stop|restart|status|logs|debug|frontend|test|build|hotfix|shell) action="$1" ;;
    --no-build) no_build=true ;;
    --frontend) frontend=true ;;
    --full) full=true ;;
    --include-real-media) include_real_media=true ;;
    --long) long=true ;;
    --open) open_browser=true ;;
    --allow-non-dev) allow_non_dev=true ;;
    --image) shift; image="${1:?--image requires a value}" ;;
    --frontend-port) shift; frontend_port="${1:?--frontend-port requires a value}" ;;
    --tail) shift; tail_lines="${1:?--tail requires a value}" ;;
    --env-file) shift; env_file="${1:?--env-file requires a value}" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 64 ;;
  esac
  shift
done

command -v git >/dev/null || { echo 'required command is unavailable: git' >&2; exit 69; }
repo="$(git rev-parse --show-toplevel)"
cd "$repo"
branch="$(git branch --show-current)"
if [[ "$branch" != dev && "$allow_non_dev" != true ]]; then
  echo "this helper is restricted to branch dev (current: '$branch'); use --allow-non-dev only for an explicit experiment" >&2
  exit 65
fi
for command in docker; do
  command -v "$command" >/dev/null || { echo "required command is unavailable: $command" >&2; exit 69; }
done

if [[ "$env_file" = /* ]]; then
  env_path="$env_file"
else
  env_path="$repo/$env_file"
fi
if [[ ! -f "$env_path" ]]; then
  [[ "$env_file" = .env ]] || { echo "environment file does not exist: $env_path" >&2; exit 66; }
  cp "$repo/.env.example" "$env_path"
  chmod 600 "$env_path" 2>/dev/null || true
  echo "created local .env from .env.example (Git-ignored)"
fi

compose=(docker compose --env-file "$env_path" -f "$repo/compose.yaml")
state_key="$(printf '%s' "$repo" | tr -c 'A-Za-z0-9' '_')"
state_dir="${TMPDIR:-/tmp}/webobs-dev-${state_key}"
frontend_pid_file="$state_dir/vite.pid"
frontend_log_file="$state_dir/vite.log"

compose_run() { "${compose[@]}" "$@"; }
ensure_config() { compose_run config --quiet; }
set_local_image() { export WEBOBS_IMAGE="$image"; }

start_frontend() {
  command -v pnpm >/dev/null || { echo 'required command is unavailable: pnpm' >&2; exit 69; }
  mkdir -p "$state_dir"
  if [[ -s "$frontend_pid_file" ]]; then
    pid="$(cat "$frontend_pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "Vite is already running (PID $pid): http://127.0.0.1:${frontend_port}/"
      return
    fi
    rm -f "$frontend_pid_file"
  fi
  (cd "$repo/web" && exec pnpm dev -- --host 127.0.0.1 --port "$frontend_port") \
    >"$frontend_log_file" 2>&1 &
  echo $! >"$frontend_pid_file"
  echo "Vite started in background (PID $(cat "$frontend_pid_file")): http://127.0.0.1:${frontend_port}/"
  echo "Vite log: $frontend_log_file"
}

stop_frontend() {
  if [[ ! -s "$frontend_pid_file" ]]; then
    echo 'Vite is not tracked as running'
    return
  fi
  pid="$(cat "$frontend_pid_file")"
  rm -f "$frontend_pid_file"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in {1..20}; do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
    kill -9 "$pid" 2>/dev/null || true
  fi
  echo "stopped Vite process (PID $pid)"
}

wait_health() {
  for _ in {1..30}; do
    if command -v curl >/dev/null && curl -fsS --max-time 2 http://127.0.0.1:8080/api/v1/health >/dev/null 2>&1; then return; fi
    sleep 1
  done
  echo 'webobs health endpoint did not become ready within 30 seconds' >&2
  exit 70
}

start_backend() {
  ensure_config
  set_local_image
  if [[ "$1" = true ]]; then compose_run build webobs; fi
  compose_run up -d --no-build webobs
  wait_health
  echo "backend ready: http://127.0.0.1:8080/ (local image: $image)"
}

show_status() {
  ensure_config
  compose_run ps
  if command -v curl >/dev/null && curl -fsS --max-time 3 http://127.0.0.1:8080/api/v1/health >/dev/null 2>&1; then
    echo 'health: ok'
  else
    echo 'health: unavailable at http://127.0.0.1:8080'
  fi
  if [[ -s "$frontend_pid_file" ]] && kill -0 "$(cat "$frontend_pid_file")" 2>/dev/null; then
    echo "frontend: http://127.0.0.1:${frontend_port} (PID $(cat "$frontend_pid_file"))"
  else
    echo 'frontend: not started by this helper'
  fi
}

run_tests() {
  command -v pnpm >/dev/null || { echo 'required command is unavailable: pnpm' >&2; exit 69; }
  command -v python3 >/dev/null || { echo 'required command is unavailable: python3' >&2; exit 69; }
  if [[ "$full" = true ]]; then
    full_args=(--image "$image")
    [[ "$include_real_media" = true ]] && full_args+=(--include-real-media)
    [[ "$long" = true ]] && full_args+=(--long)
    ./scripts/test-local-full.sh "${full_args[@]}"
    return
  fi
  ./tests/run-public-audit.sh
  (cd web && pnpm typecheck && pnpm test:iwa && pnpm test:local)
}

case "$action" in
  start)
    if [[ "$no_build" = true ]]; then start_backend false; else start_backend true; fi
    if [[ "$frontend" = true ]]; then start_frontend; else echo 'for hot reload run: scripts/dev-local.sh frontend'; fi
    if [[ "$open_browser" = true ]]; then
      if command -v xdg-open >/dev/null; then xdg-open "http://127.0.0.1:${frontend_port}/" >/dev/null 2>&1 &
      else echo "open http://127.0.0.1:${frontend_port}/ in your browser"; fi
    fi
    ;;
  stop) stop_frontend; ensure_config; compose_run stop ;;
  restart) stop_frontend; if [[ "$no_build" = true ]]; then start_backend false; else start_backend true; fi; [[ "$frontend" = true ]] && start_frontend ;;
  status) show_status ;;
  logs) ensure_config; compose_run logs --tail "$tail_lines" -f webobs ;;
  debug) show_status; ensure_config; compose_run logs --tail "$tail_lines" webobs ;;
  frontend) start_frontend ;;
  test) run_tests ;;
  build) ensure_config; set_local_image; compose_run build webobs ;;
  hotfix) ensure_config; set_local_image; compose_run build webobs; compose_run up -d --force-recreate --no-build webobs; wait_health; echo "hotfix image is running locally as $image; nothing was pushed" ;;
  shell) ensure_config; compose_run exec webobs sh ;;
esac
