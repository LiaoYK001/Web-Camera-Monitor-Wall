#!/bin/sh
set -eu

# $1 is either a MediaMTX direct route (`direct-<32 hex>`) or, for the
# audio-only per-track mode, an explicit RTSP(S) source URL.  The URL form lets
# the engine extract one input track without a pre-existing direct route; it is
# restricted to printable ASCII without spaces so a caller cannot smuggle extra
# ffmpeg arguments through the same field.
validate_mix_spec() {
    spec="$1"
    count=0
    old_ifs="$IFS"
    IFS=','
    for entry in $spec; do
        IFS="$old_ifs"
        case "$entry" in
        *:*:*) ;;
        *) return 1 ;;
        esac
        index="${entry%%:*}"
        remainder="${entry#*:}"
        gain="${remainder%%:*}"
        remainder="${remainder#*:}"
        muted="${remainder%%:*}"
        delay=""
        if [ "$remainder" != "$muted" ]; then
            delay="${remainder#*:}"
        fi
        printf '%s' "$index" | grep -Eq '^([0-9]|1[0-9]|2[0-9]|3[01])$' || return 1
        printf '%s' "$gain" | grep -Eq '^(0(\.[0-9]{1,4})?|1(\.0{1,4})?)$' || return 1
        printf '%s' "$muted" | grep -Eq '^[01]$' || return 1
        if [ -n "$delay" ]; then
            printf '%s' "$delay" | grep -Eq '^(0|[1-9][0-9]{0,4})$' || return 1
            [ "$delay" -le 10000 ] || return 1
        fi
        count=$((count + 1))
        [ "$count" -le 8 ] || return 1
        IFS=','
    done
    IFS="$old_ifs"
    [ "$count" -ge 1 ]
}

if [ "$#" -ne 4 ] ||
    ! printf '%s\n' "$1" | grep -Eq '^(direct-[a-f0-9]{32}|rtsps?://[!-~]{1,2048})$' ||
    ! printf '%s\n' "$3" | grep -Eq '^(copy|transcode|audio-track|audio-mix)$'; then
    echo "invalid internal transcoder path" >&2
    exit 2
fi

case "$3" in
audio-track)
    # Audio-only per-track route: <direct-src> <audio-dst> audio-track <index>.
    if ! printf '%s\n' "$2" | grep -Eq '^audio-[a-f0-9]{32}-t([0-9]|1[0-9]|2[0-9]|3[01])$' ||
        ! printf '%s\n' "$4" | grep -Eq '^([0-9]|1[0-9]|2[0-9]|3[01])$' ||
        ! printf '%s\n' "$2" | grep -Eq -- "-t$4$"; then
        echo "invalid internal audio-only track path" >&2
        exit 2
    fi
    ;;
audio-mix)
    # Mix several input tracks into the single audio stream a scene source can
    # consume: <src> <mix-dst> audio-mix <index:gain:muted,...>
    if ! printf '%s\n' "$2" | grep -Eq '^mix-[a-f0-9]{32}$' || ! validate_mix_spec "$4"; then
        echo "invalid internal audio-mix spec" >&2
        exit 2
    fi
    ;;
*)
    if ! printf '%s\n' "$1" | grep -Eq '^direct-[a-f0-9]{32}$' ||
        ! printf '%s\n' "$2" | grep -Eq '^hybrid-[a-f0-9]{32}$' ||
        ! printf '%s\n' "$4" | grep -Eq '^(copy|transcode)$'; then
        echo "invalid internal transcoder path" >&2
        exit 2
    fi
    ;;
esac

source_path="$1"
target_path="$2"
video_mode="$3"
audio_mode="$4"
vaapi_device="${WEBOBS_VAAPI_DEVICE:-/dev/dri/renderD128}"
bitrate="${WEBOBS_HYBRID_BITRATE_KBPS:-4000}k"

# MediaMTX 1.18.2 maps a single audio output per path, so every independently
# controllable track gets its own audio-only path.  Only Opus/G.711 survive
# WebRTC, therefore each track is transcoded (or re-encoded) to Opus.
if [ "$video_mode" = audio-mix ]; then
    case "$source_path" in
    direct-*) input_url="rtsp://127.0.0.1:8554/$source_path" ;;
    *) input_url="$source_path" ;;
    esac
    graph=""
    inputs=""
    count=0
    old_ifs="$IFS"
    IFS=','
    for entry in $audio_mode; do
        IFS="$old_ifs"
        index="${entry%%:*}"
        remainder="${entry#*:}"
        gain="${remainder%%:*}"
        remainder="${remainder#*:}"
        muted="${remainder%%:*}"
        delay=""
        if [ "$remainder" != "$muted" ]; then
            delay="${remainder#*:}"
        fi
        [ "$muted" = "1" ] && gain="0"
        filter="volume=$gain"
        if [ -n "$delay" ] && [ "$delay" -gt 0 ]; then
            filter="adelay=$delay|$delay,$filter"
        fi
        graph="$graph[0:a:$index]$filter[m$count];"
        inputs="$inputs[m$count]"
        count=$((count + 1))
        IFS=','
    done
    IFS="$old_ifs"
    exec ffmpeg -hide_banner -loglevel error -nostdin -rtsp_transport tcp -timeout 8000000 \
        -i "$input_url" -filter_complex "${graph}${inputs}amix=inputs=$count:normalize=0[amixed]" \
        -map 0:v -map "[amixed]" -c:v copy -c:a libopus -b:a "${WEBOBS_AUDIO_TRACK_BITRATE_KBPS:-96}k" \
        -ar 48000 -ac 2 -rtsp_transport tcp -f rtsp "rtsp://127.0.0.1:8554/$target_path"
fi

if [ "$video_mode" = audio-track ]; then
    case "$source_path" in
    direct-*) input_url="rtsp://127.0.0.1:8554/$source_path" ;;
    *) input_url="$source_path" ;;
    esac
    exec ffmpeg -hide_banner -loglevel error -nostdin -rtsp_transport tcp -timeout 8000000 \
        -i "$input_url" -map "0:a:$audio_mode" -vn \
        -c:a libopus -b:a "${WEBOBS_AUDIO_TRACK_BITRATE_KBPS:-96}k" -ar 48000 -ac 2 \
        -rtsp_transport tcp -f rtsp "rtsp://127.0.0.1:8554/$target_path"
fi

run_ffmpeg() {
    encoder="$1"
    set -- ffmpeg -hide_banner -loglevel error -nostdin -rtsp_transport tcp -timeout 8000000
    if [ "$video_mode" = transcode ]; then
        if [ "$encoder" = vaapi ]; then
            set -- "$@" -hwaccel vaapi -hwaccel_device "$vaapi_device" -hwaccel_output_format vaapi
        elif [ "$encoder" = nvenc ] && [ "${WEBOBS_NVIDIA_DECODE_SUPPORTED:-false}" = true ]; then
            # CUDA decode when the runtime probe passed; otherwise software
            # decode + NVENC encode is still used and reported as partial.
            set -- "$@" -hwaccel cuda
        fi
    fi
    set -- "$@" -i "rtsp://127.0.0.1:8554/$source_path" -map 0:v:0 -map '0:a:0?'
    if [ "$video_mode" = copy ]; then
        set -- "$@" -c:v copy
    elif [ "$encoder" = nvenc ]; then
        # Low-latency NVENC: fastest preset, no B-frames, two-second keyframes.
        set -- "$@" -c:v h264_nvenc -preset p1 -tune ll -rc cbr \
            -b:v "$bitrate" -maxrate "$bitrate" -bufsize "$bitrate" \
            -bf 0 -g 60 -pix_fmt yuv420p
    elif [ "$encoder" = vaapi ]; then
        set -- "$@" -vf scale_vaapi=format=nv12 -c:v h264_vaapi -profile:v high -rc_mode CBR \
            -b:v "$bitrate" -maxrate "$bitrate" -bufsize "$bitrate" -bf 0 -g 60
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

if [ "$video_mode" = transcode ] && [ "${WEBOBS_HYBRID_VIDEO_ENCODER:-auto}" != x264 ]; then
    if [ "${WEBOBS_NVIDIA_ENCODE_SUPPORTED:-false}" = true ]; then
        if [ "${WEBOBS_NVIDIA_DECODE_SUPPORTED:-false}" != true ]; then
            echo "NVENC encode with software decode (部分加速 / partial acceleration)" >&2
        fi
        if run_ffmpeg nvenc; then
            exit 0
        fi
        echo "NVENC hybrid pipeline failed; trying the VA-API path" >&2
    fi
    if [ "${WEBOBS_VAAPI_RUNTIME_PROBE_PASSED:-false}" = true ] &&
       [ "${WEBOBS_VAAPI_ENCODE_SUPPORTED:-false}" = true ] &&
       [ "${WEBOBS_VAAPI_DECODE_SUPPORTED:-false}" = true ]; then
        if run_ffmpeg vaapi; then
            exit 0
        fi
        echo "VA-API hybrid pipeline failed; falling back to libx264" >&2
    fi
fi

exec_ffmpeg() {
    run_ffmpeg x264
}
exec_ffmpeg
