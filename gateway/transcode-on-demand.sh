#!/bin/sh
set -eu

if [ "$#" -ne 2 ] ||
    ! printf '%s\n' "$1" | grep -Eq '^direct-[a-f0-9]{32}$' ||
    ! printf '%s\n' "$2" | grep -Eq '^hybrid-[a-f0-9]{32}$'; then
    echo "invalid internal transcoder path" >&2
    exit 2
fi

exec ffmpeg \
    -hide_banner \
    -loglevel error \
    -nostdin \
    -rtsp_transport tcp \
    -timeout 8000000 \
    -i "rtsp://127.0.0.1:8554/$1" \
    -map 0:v:0 \
    -an \
    -c:v libx264 \
    -preset veryfast \
    -tune zerolatency \
    -profile:v high \
    -pix_fmt yuv420p \
    -bf 0 \
    -sc_threshold 0 \
    -force_key_frames 'expr:gte(t,n_forced*2)' \
    -rtsp_transport tcp \
    -f rtsp \
    "rtsp://127.0.0.1:8554/$2"
