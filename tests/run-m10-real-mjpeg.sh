#!/bin/sh
set -eu

stream_url="${WEBOBS_REAL_MJPEG_URL:-}"
image="${WEBOBS_IMAGE:-webobs:m0}"
case "$stream_url" in
  http://*|https://*) ;;
  *) echo 'Set WEBOBS_REAL_MJPEG_URL to an HTTP(S) stream without embedded credentials.' >&2; exit 64 ;;
esac
authority="${stream_url#*://}"
case "${authority%%/*}" in
  *@*) echo 'Embedded credentials are forbidden; use a private Secret integration.' >&2; exit 64 ;;
esac

probe="$({
  docker run --rm -e WEBOBS_REAL_MJPEG_URL --entrypoint /bin/sh "$image" -ec \
    'ffprobe -v error -rw_timeout 8000000 -select_streams v:0 -show_entries stream=codec_name,width,height,r_frame_rate -of csv=p=0 "$WEBOBS_REAL_MJPEG_URL"'
} 2>&1)" || {
  echo 'Private MJPEG probe failed; raw diagnostics were suppressed to protect the endpoint.' >&2
  exit 1
}

old_ifs="$IFS"
IFS=,
set -- $probe
IFS="$old_ifs"
[ "${1:-}" = mjpeg ] && [ "${2:-0}" -gt 0 ] && [ "${3:-0}" -gt 0 ] || {
  echo 'The endpoint did not negotiate a decodable Motion JPEG video stream.' >&2
  exit 1
}

decode="$({
  docker run --rm -e WEBOBS_REAL_MJPEG_URL --entrypoint /bin/sh "$image" -ec \
    'ffmpeg -hide_banner -loglevel error -rw_timeout 8000000 -i "$WEBOBS_REAL_MJPEG_URL" -frames:v 5 -f null -'
} 2>&1)" || {
  echo 'Private MJPEG decode failed; raw diagnostics were suppressed to protect the endpoint.' >&2
  exit 1
}

printf 'Real server-push MJPEG gate passed: codec=mjpeg, %sx%s, rate=%s, decodedFrames=5; endpoint redacted.\n' "$2" "$3" "${4:-unknown}"
