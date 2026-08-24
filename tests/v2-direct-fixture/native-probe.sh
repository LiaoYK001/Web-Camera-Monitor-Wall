#!/usr/bin/env bash
set -euo pipefail

adapter="${WEBOBS_PROBE_ADAPTER:?WEBOBS_PROBE_ADAPTER is required}"
codec="${WEBOBS_PROBE_CODEC:?WEBOBS_PROBE_CODEC is required}"
endpoint="${WEBOBS_PROBE_ENDPOINT:?WEBOBS_PROBE_ENDPOINT is required}"
attempt=0
while (( attempt < 30 )); do
  attempt=$((attempt + 1))
  recording_arguments=()
  if [[ "$adapter" == rtsp && "$codec" == h264 ]]; then
    rm -f -- /tmp/webobs-probe.mkv /tmp/webobs-probe.mp4
    recording_arguments=(--probe-record-mkv /tmp/webobs-probe.mkv)
  fi
  if /build/clients/webobs-native \
      --probe-adapter "$adapter" \
      --probe-codec "$codec" \
      --probe-endpoint "$endpoint" \
      --probe-seconds 5 "${recording_arguments[@]}"; then
    if (( ${#recording_arguments[@]} > 0 )); then
      [[ -s /tmp/webobs-probe.mkv ]]
      gst-launch-1.0 -q -e filesrc location=/tmp/webobs-probe.mkv \
        ! matroskademux ! parsebin ! mp4mux faststart=true \
        ! filesink location=/tmp/webobs-probe.mp4
      [[ -s /tmp/webobs-probe.mp4 ]]
      gst-launch-1.0 -q filesrc location=/tmp/webobs-probe.mp4 \
        ! qtdemux ! parsebin ! fakesink
    fi
    printf '{"adapter":"%s","codec":"%s","result":"passed"}\n' "$adapter" "$codec"
    exit 0
  fi
  sleep 1
done
printf 'native protocol probe failed after bounded retries: adapter=%s codec=%s\n' \
  "$adapter" "$codec" >&2
exit 1
