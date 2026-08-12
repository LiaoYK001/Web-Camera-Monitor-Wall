#!/bin/sh
set -eu

url="${TEST_RTSP_URL:-rtsp://mediamtx:8554/m3-hevc}"

while true; do
    ffmpeg \
        -hide_banner \
        -loglevel warning \
        -re \
        -f lavfi \
        -i "testsrc2=size=640x480:rate=10" \
        -an \
        -c:v libx265 \
        -preset ultrafast \
        -tune zerolatency \
        -pix_fmt yuv420p \
        -g 20 \
        -bf 0 \
        -x265-params 'log-level=error:scenecut=0' \
        -rtsp_transport tcp \
        -f rtsp \
        "$url" && exit 0
    echo "HEVC RTSP publisher disconnected; retrying in one second" >&2
    sleep 1
done
