#!/bin/sh
set -eu

url="${TEST_RTSP_URL:-rtsp://mediamtx:8554/m0-test}"

while true; do
    ffmpeg \
        -hide_banner \
        -loglevel warning \
        -re \
        -f lavfi \
        -i "testsrc2=size=640x360:rate=10" \
        -an \
        -c:v libx264 \
        -preset ultrafast \
        -tune zerolatency \
        -profile:v high \
        -pix_fmt yuv420p \
        -g 20 \
        -bf 0 \
        -rtsp_transport tcp \
        -f rtsp \
        "$url" && exit 0
    echo "RTSP publisher disconnected; retrying in one second" >&2
    sleep 1
done
