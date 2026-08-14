#!/bin/sh
set -eu

url="${TEST_RTSP_URL:-rtsp://mediamtx:8554/m5-audio-a}"
frequency="${TEST_AUDIO_FREQUENCY:-440}"
codec="${TEST_AUDIO_CODEC:-opus}"

case "$frequency" in
    440|880) ;;
    *) echo "TEST_AUDIO_FREQUENCY must be 440 or 880" >&2; exit 2 ;;
esac
case "$codec" in
    opus) set -- -c:a libopus -b:a 96k ;;
    aac) set -- -c:a aac -b:a 128k ;;
    *) echo "TEST_AUDIO_CODEC must be opus or aac" >&2; exit 2 ;;
esac

audio="aevalsrc=exprs='if(lt(mod(t\,1)\,0.20)\,0.70*sin(2*PI*${frequency}*t)\,0)|if(lt(mod(t\,1)\,0.20)\,0.70*sin(2*PI*${frequency}*t)\,0)':s=48000"
video="color=c=black:s=640x360:r=20,drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='lt(mod(t,1),0.20)'"

while true; do
    ffmpeg \
        -hide_banner \
        -loglevel warning \
        -re \
        -f lavfi \
        -i "$video" \
        -f lavfi \
        -i "$audio" \
        -map 0:v:0 \
        -map 1:a:0 \
        -c:v libx264 \
        -preset ultrafast \
        -tune zerolatency \
        -profile:v high \
        -pix_fmt yuv420p \
        -g 40 \
        -bf 0 \
        "$@" \
        -ar 48000 \
        -ac 2 \
        -rtsp_transport tcp \
        -f rtsp \
        "$url" && exit 0
    echo "RTSP AV publisher disconnected; retrying in one second" >&2
    sleep 1
done
