#!/bin/sh
set -eu

file="${TEST_RECORDING:-/artifacts/smoke.mp4}"
expected_dimensions="${TEST_DIMENSIONS:-640x360}"
expected_frame_rate="${TEST_FRAME_RATE:-10/1}"
minimum_duration="${TEST_MIN_DURATION:-8}"
maximum_duration="${TEST_MAX_DURATION:-15}"

test -s "$file"

codec="$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1:nk=1 "$file")"
dimensions="$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$file")"
frame_rate="$(ffprobe -v error -select_streams v:0 -show_entries stream=avg_frame_rate -of default=nw=1:nk=1 "$file")"
audio_streams="$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$file")"
duration="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$file")"

test "$codec" = "h264"
test "$dimensions" = "$expected_dimensions"
test "$frame_rate" = "$expected_frame_rate"
test -z "$audio_streams"
awk -v duration="$duration" -v minimum="$minimum_duration" -v maximum="$maximum_duration" \
    'BEGIN { exit !(duration >= minimum && duration <= maximum) }'

yavg="$(ffmpeg -hide_banner -loglevel info -i "$file" -frames:v 1 -vf signalstats,metadata=print -f null - 2>&1 \
    | awk -F= '/lavfi.signalstats.YAVG=/{print $2; exit}')"
test -n "$yavg"
awk -v yavg="$yavg" 'BEGIN { exit !(yavg > 5) }'

ffmpeg -v error -i "$file" -map 0:v:0 -f null -
echo "M0 smoke recording verified: codec=$codec dimensions=$dimensions fps=$frame_rate duration=$duration yavg=$yavg"
