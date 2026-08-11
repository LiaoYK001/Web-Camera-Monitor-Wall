#!/bin/sh
set -eu

file="${TEST_RECORDING:-/artifacts/smoke.mp4}"
expected_dimensions="${TEST_DIMENSIONS:-640x360}"
expected_frame_rate="${TEST_FRAME_RATE:-10/1}"
minimum_duration="${TEST_MIN_DURATION:-8}"
maximum_duration="${TEST_MAX_DURATION:-15}"
require_pillarbox="${TEST_REQUIRE_PILLARBOX:-0}"
require_two_up="${TEST_REQUIRE_TWO_UP:-0}"

case "$require_pillarbox" in
    0|1) ;;
    *) echo "TEST_REQUIRE_PILLARBOX must be 0 or 1" >&2; exit 2 ;;
esac
case "$require_two_up" in
    0|1) ;;
    *) echo "TEST_REQUIRE_TWO_UP must be 0 or 1" >&2; exit 2 ;;
esac

test -s "$file"

codec="$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1:nk=1 "$file")"
dimensions="$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$file")"
nominal_frame_rate="$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=nw=1:nk=1 "$file")"
average_frame_rate="$(ffprobe -v error -select_streams v:0 -show_entries stream=avg_frame_rate -of default=nw=1:nk=1 "$file")"
audio_streams="$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$file")"
duration="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$file")"

test "$codec" = "h264"
test "$dimensions" = "$expected_dimensions"
test "$nominal_frame_rate" = "$expected_frame_rate"
test -z "$audio_streams"
awk -v actual="$average_frame_rate" -v expected="$expected_frame_rate" '
    function rate(value, parts, count) {
        count = split(value, parts, "/")
        if (count == 2) {
            if (parts[2] == 0) return -1
            return parts[1] / parts[2]
        }
        return value + 0
    }
    BEGIN {
        actual_rate = rate(actual)
        expected_rate = rate(expected)
        tolerance = expected_rate * 0.005
        if (tolerance < 0.02) tolerance = 0.02
        delta = actual_rate - expected_rate
        if (delta < 0) delta = -delta
        exit !(actual_rate > 0 && expected_rate > 0 && delta <= tolerance)
    }'
awk -v duration="$duration" -v minimum="$minimum_duration" -v maximum="$maximum_duration" \
    'BEGIN { exit !(duration >= minimum && duration <= maximum) }'

yavg="$(ffmpeg -hide_banner -loglevel info -i "$file" -frames:v 1 -vf signalstats,metadata=print -f null - 2>&1 \
    | awk -F= '/lavfi.signalstats.YAVG=/{print $2; exit}')"
test -n "$yavg"
awk -v yavg="$yavg" 'BEGIN { exit !(yavg > 5) }'

pillarbox_report=""
if [ "$require_pillarbox" = "1" ]; then
    left_yavg="$(ffmpeg -hide_banner -loglevel info -i "$file" -frames:v 1 \
        -vf 'crop=40:ih:0:0,signalstats,metadata=print' -f null - 2>&1 \
        | awk -F= '/lavfi.signalstats.YAVG=/{print $2; exit}')"
    right_yavg="$(ffmpeg -hide_banner -loglevel info -i "$file" -frames:v 1 \
        -vf 'crop=40:ih:iw-40:0,signalstats,metadata=print' -f null - 2>&1 \
        | awk -F= '/lavfi.signalstats.YAVG=/{print $2; exit}')"
    center_yavg="$(ffmpeg -hide_banner -loglevel info -i "$file" -frames:v 1 \
        -vf 'crop=320:180:(iw-ow)/2:(ih-oh)/2,signalstats,metadata=print' -f null - 2>&1 \
        | awk -F= '/lavfi.signalstats.YAVG=/{print $2; exit}')"
    test -n "$left_yavg"
    test -n "$right_yavg"
    test -n "$center_yavg"
    awk -v left="$left_yavg" -v right="$right_yavg" -v center="$center_yavg" '
        BEGIN {
            edge_delta = left - right
            if (edge_delta < 0) edge_delta = -edge_delta
            exit !(left < 24 && right < 24 && center > 40 &&
                   center - left > 30 && center - right > 30 && edge_delta < 3)
        }'
    pillarbox_report=" pillarbox_left_yavg=$left_yavg pillarbox_center_yavg=$center_yavg pillarbox_right_yavg=$right_yavg"
fi

two_up_report=""
if [ "$require_two_up" = "1" ]; then
    top_yavg="$(ffmpeg -hide_banner -loglevel info -i "$file" -frames:v 1 \
        -vf 'crop=iw:40:0:0,signalstats,metadata=print' -f null - 2>&1 \
        | awk -F= '/lavfi.signalstats.YAVG=/{print $2; exit}')"
    bottom_yavg="$(ffmpeg -hide_banner -loglevel info -i "$file" -frames:v 1 \
        -vf 'crop=iw:40:0:ih-40,signalstats,metadata=print' -f null - 2>&1 \
        | awk -F= '/lavfi.signalstats.YAVG=/{print $2; exit}')"
    left_center_yavg="$(ffmpeg -hide_banner -loglevel info -i "$file" -frames:v 1 \
        -vf 'crop=40:180:0:(ih-oh)/2,signalstats,metadata=print' -f null - 2>&1 \
        | awk -F= '/lavfi.signalstats.YAVG=/{print $2; exit}')"
    right_center_yavg="$(ffmpeg -hide_banner -loglevel info -i "$file" -frames:v 1 \
        -vf 'crop=40:180:iw-40:(ih-oh)/2,signalstats,metadata=print' -f null - 2>&1 \
        | awk -F= '/lavfi.signalstats.YAVG=/{print $2; exit}')"
    test -n "$top_yavg"
    test -n "$bottom_yavg"
    test -n "$left_center_yavg"
    test -n "$right_center_yavg"
    awk -v top="$top_yavg" -v bottom="$bottom_yavg" -v left="$left_center_yavg" -v right="$right_center_yavg" '
        BEGIN {
            exit !(top < 24 && bottom < 24 && left > 40 && right > 40 &&
                   left - top > 25 && right - top > 25)
        }'
    two_up_report=" two_up_top_yavg=$top_yavg two_up_bottom_yavg=$bottom_yavg two_up_left_yavg=$left_center_yavg two_up_right_yavg=$right_center_yavg"
fi

ffmpeg -v error -i "$file" -map 0:v:0 -f null -
echo "Recording verified: codec=$codec dimensions=$dimensions nominal_fps=$nominal_frame_rate average_fps=$average_frame_rate duration=$duration yavg=$yavg$pillarbox_report$two_up_report"
