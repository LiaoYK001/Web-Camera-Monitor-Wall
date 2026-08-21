#!/bin/sh
set -eu

if [ "$#" -ne 4 ] ||
    ! printf '%s\n' "$1" | grep -Eq '^direct-[a-f0-9]{32}$' ||
    ! printf '%s\n' "$2" | grep -Eq '^hybrid-[a-f0-9]{32}$' ||
    ! printf '%s\n' "$3" | grep -Eq '^(copy|transcode)$' ||
    ! printf '%s\n' "$4" | grep -Eq '^(copy|transcode)$'; then
    echo "invalid internal transcoder path" >&2
    exit 2
fi

source_path="$1"
target_path="$2"
video_mode="$3"
audio_mode="$4"
vaapi_device="${WEBOBS_VAAPI_DEVICE:-/dev/dri/renderD128}"

run_ffmpeg() {
    encoder="$1"
    set -- ffmpeg -hide_banner -loglevel error -nostdin -rtsp_transport tcp -timeout 8000000
    if [ "$video_mode" = transcode ] && [ "$encoder" = vaapi ]; then
        set -- "$@" -hwaccel vaapi -hwaccel_device "$vaapi_device" -hwaccel_output_format vaapi
    fi
    set -- "$@" -i "rtsp://127.0.0.1:8554/$source_path" -map 0:v:0 -map '0:a:0?'
    if [ "$video_mode" = copy ]; then
        set -- "$@" -c:v copy
    elif [ "$encoder" = vaapi ]; then
        set -- "$@" -vf scale_vaapi=format=nv12 -c:v h264_vaapi -profile:v high -rc_mode CBR \
            -b:v "${WEBOBS_HYBRID_BITRATE_KBPS:-4000}k" -maxrate "${WEBOBS_HYBRID_BITRATE_KBPS:-4000}k" \
            -bufsize "${WEBOBS_HYBRID_BITRATE_KBPS:-4000}k" -bf 0 -g 60
    else
        set -- "$@" -c:v libx264 -preset veryfast -tune zerolatency -profile:v high \
            -pix_fmt yuv420p -bf 0 -sc_threshold 0 -force_key_frames 'expr:gte(t,n_forced*2)'
    fi
    if [ "$audio_mode" = copy ]; then
        set -- "$@" -c:a copy
    else
        set -- "$@" -c:a libopus -b:a 96k -ar 48000 -ac 2
    fi
    set -- "$@" -rtsp_transport tcp -f rtsp "rtsp://127.0.0.1:8554/$target_path"
    "$@"
}

if [ "$video_mode" = transcode ] &&
   [ "${WEBOBS_HYBRID_VIDEO_ENCODER:-auto}" != x264 ] &&
   [ "${WEBOBS_VAAPI_RUNTIME_PROBE_PASSED:-false}" = true ] &&
   [ "${WEBOBS_VAAPI_ENCODE_SUPPORTED:-false}" = true ] &&
   [ "${WEBOBS_VAAPI_DECODE_SUPPORTED:-false}" = true ]; then
    if run_ffmpeg vaapi; then
        exit 0
    fi
    echo "VA-API hybrid pipeline failed; falling back to libx264" >&2
fi

exec_ffmpeg() {
    run_ffmpeg x264
}
exec_ffmpeg
