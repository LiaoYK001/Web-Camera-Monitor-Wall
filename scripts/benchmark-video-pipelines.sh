#!/bin/sh
set -eu

usage() {
    cat <<'EOF'
Usage: benchmark-video-pipelines.sh --label NAME [options]

Options:
  --container NAME       WebOBS container (default: web-camera-monitor-wall)
  --runtime docker|podman Container CLI (auto-detected by default)
  --duration SECONDS     Sampling duration, 10-3600 (default: 60)
  --interval SECONDS     Sampling interval, 1-60 (default: 2)
  --output PATH          CSV output (default: benchmark-<label>-<utc>.csv)

Run the same fixture separately for 1/4/9 cameras and labels such as
direct-4, composite-vaapi-4, hybrid-cpu-4, and hybrid-vaapi-4.
EOF
}

label=""
container="web-camera-monitor-wall"
runtime=""
duration=60
interval=2
output=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --label) label="${2:-}"; shift 2 ;;
        --container) container="${2:-}"; shift 2 ;;
        --runtime) runtime="${2:-}"; shift 2 ;;
        --duration) duration="${2:-}"; shift 2 ;;
        --interval) interval="${2:-}"; shift 2 ;;
        --output) output="${2:-}"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

case "$label" in ''|*[!A-Za-z0-9._-]*) echo "--label must be a safe identifier" >&2; exit 2 ;; esac
case "$container" in ''|*[!A-Za-z0-9_.-]*) echo "--container must be a safe name" >&2; exit 2 ;; esac
case "$duration" in ''|*[!0-9]*) echo "--duration must be an integer" >&2; exit 2 ;; esac
case "$interval" in ''|*[!0-9]*) echo "--interval must be an integer" >&2; exit 2 ;; esac
[ "$duration" -ge 10 ] && [ "$duration" -le 3600 ] || { echo "--duration must be 10-3600" >&2; exit 2; }
[ "$interval" -ge 1 ] && [ "$interval" -le 60 ] || { echo "--interval must be 1-60" >&2; exit 2; }

if [ -z "$runtime" ]; then
    if command -v podman >/dev/null 2>&1; then runtime=podman
    elif command -v docker >/dev/null 2>&1; then runtime=docker
    else echo "docker or podman is required" >&2; exit 2
    fi
fi
case "$runtime" in docker|podman) ;; *) echo "--runtime must be docker or podman" >&2; exit 2 ;; esac
command -v "$runtime" >/dev/null 2>&1 || { echo "$runtime is unavailable" >&2; exit 2; }
"$runtime" inspect "$container" >/dev/null 2>&1 || { echo "container is unavailable: $container" >&2; exit 3; }

if [ -z "$output" ]; then
    output="benchmark-${label}-$(date -u +%Y%m%dT%H%M%SZ).csv"
fi
output_directory=$(dirname -- "$output")
[ -d "$output_directory" ] || { echo "output directory does not exist" >&2; exit 2; }

printf '%s\n' 'utc,label,container_cpu_percent,memory_usage,network_input,network_output,webobsd_cpu,mediamtx_cpu,ffmpeg_cpu,caddy_cpu,browser_cpu,webobsd_rss_kib,mediamtx_rss_kib,ffmpeg_rss_kib,ffmpeg_processes,rtsp_tcp_sessions,gpu_busy_percent' > "$output"

samples=$((duration / interval))
index=0
while [ "$index" -lt "$samples" ]; do
    stats=$("$runtime" stats --no-stream --format '{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}' "$container" 2>/dev/null || printf '0%%|0B / 0B|0B / 0B')
    process_stats=$("$runtime" exec "$container" ps -eo comm=,pcpu=,rss= 2>/dev/null || true)
    aggregate() {
        process_name="$1"
        printf '%s\n' "$process_stats" | awk -v name="$process_name" '$1 ~ name {cpu += $2; rss += $3; count += 1} END {printf "%.2f|%d|%d", cpu, rss, count}'
    }
    webobs=$(aggregate '^webobsd$')
    mediamtx=$(aggregate '^mediamtx$')
    ffmpeg=$(aggregate '^ffmpeg$')
    caddy=$(aggregate '^caddy$')
    browser=$(aggregate '^obs-browser')
    rtsp_sessions=$("$runtime" exec "$container" sh -c "awk 'NR>1 && \$4==\"01\" && (\$3 ~ /:022A$/ || \$3 ~ /:216A$/) {n++} END {print n+0}' /proc/net/tcp /proc/net/tcp6" 2>/dev/null || printf '0')
    gpu_busy=$("$runtime" exec "$container" sh -c 'for path in /sys/class/drm/card*/device/gpu_busy_percent; do [ -r "$path" ] && { cat "$path"; exit; }; done; echo -1' 2>/dev/null || printf '%s' '-1')

    cpu=$(printf '%s' "$stats" | cut -d'|' -f1 | tr -d ' %')
    memory=$(printf '%s' "$stats" | cut -d'|' -f2 | cut -d'/' -f1 | tr -d ' ')
    network_input=$(printf '%s' "$stats" | cut -d'|' -f3 | cut -d'/' -f1 | tr -d ' ')
    network_output=$(printf '%s' "$stats" | cut -d'|' -f3 | cut -d'/' -f2 | tr -d ' ')
    utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$utc" "$label" "$cpu" "$memory" "$network_input" "$network_output" \
        "$(printf '%s' "$webobs" | cut -d'|' -f1)" \
        "$(printf '%s' "$mediamtx" | cut -d'|' -f1)" \
        "$(printf '%s' "$ffmpeg" | cut -d'|' -f1)" \
        "$(printf '%s' "$caddy" | cut -d'|' -f1)" \
        "$(printf '%s' "$browser" | cut -d'|' -f1)" \
        "$(printf '%s' "$webobs" | cut -d'|' -f2)" \
        "$(printf '%s' "$mediamtx" | cut -d'|' -f2)" \
        "$(printf '%s' "$ffmpeg" | cut -d'|' -f2)" \
        "$(printf '%s' "$ffmpeg" | cut -d'|' -f3)" "$rtsp_sessions" "$gpu_busy" >> "$output"
    index=$((index + 1))
    [ "$index" -ge "$samples" ] || sleep "$interval"
done

echo "Benchmark written to $output"
