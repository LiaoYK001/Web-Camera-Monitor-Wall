#!/bin/sh
set -eu

base_url="${CONTROL_BASE_URL:-http://webobs-real-control:8080}"
host_header="${CONTROL_HOST:-127.0.0.1:8080}"
origin="${CONTROL_ORIGIN:-http://127.0.0.1:8080}"
width="${CONTROL_WIDTH:-1920}"
height="${CONTROL_HEIGHT:-1080}"
transport="${CONTROL_RTSP_TRANSPORT:-tcp}"
two_up_seconds="${CONTROL_TWO_UP_SECONDS:-3}"

case "${CONTROL_RTSP_URL:-}" in
    '') echo "CONTROL_RTSP_URL is required" >&2; exit 2 ;;
esac
for numeric_value in "$width" "$height" "$two_up_seconds"; do
    case "$numeric_value" in
        ''|*[!0-9]*) echo "Control dimensions and delay must be non-negative integers" >&2; exit 2 ;;
    esac
done
case "$transport" in
    tcp|udp) ;;
    *) echo "CONTROL_RTSP_TRANSPORT must be tcp or udp" >&2; exit 2 ;;
esac

temporary_directory="$(mktemp -d)"
trap 'rm -rf -- "$temporary_directory"' EXIT HUP INT TERM

health_deadline=$(( $(date +%s) + 60 ))
while :; do
    health_status="$(curl --silent --connect-timeout 2 --max-time 3 \
        --header "Host: $host_header" \
        --output /dev/null --write-out '%{http_code}' \
        "$base_url/api/v1/health" || true)"
    if [ "$health_status" = "200" ]; then
        break
    fi
    if [ "$(date +%s)" -ge "$health_deadline" ]; then
        echo "M1 real-camera control endpoint did not become healthy" >&2
        exit 1
    fi
    sleep 1
done

scene="$temporary_directory/scene.json"
headers="$temporary_directory/headers.txt"
status="$(curl --silent --show-error --output "$scene" --dump-header "$headers" \
    --header "Host: $host_header" --write-out '%{http_code}' "$base_url/api/v1/scene")"
test "$status" = "200"
jq -e '.sources | length == 1' "$scene" >/dev/null
jq -e '.items | length == 1' "$scene" >/dev/null
etag="$(awk 'tolower($1) == "etag:" { gsub("\r", "", $2); print $2; exit }' "$headers")"
test -n "$etag"

half_width=$((width / 2))
right_width=$((width - half_width))
added_candidate="$temporary_directory/added-candidate.json"
jq \
    --argjson half_width "$half_width" \
    --argjson right_width "$right_width" \
    --argjson height "$height" \
    '.sources[0].muted = false
     | .sources[0].volume = 0.25
     | .items[0].x = 0
     | .items[0].y = 0
     | .items[0].width = $half_width
     | .items[0].height = $height
     | .items[0].zIndex = 0
     | .sources += [{
         id: "m1-real-added",
         kind: "rtsp",
         name: "M1 Real Camera Added",
         rtspUrl: env.CONTROL_RTSP_URL,
         transport: env.CONTROL_RTSP_TRANSPORT,
         muted: true,
         volume: 0.6
       }]
     | .items += [{
         id: "m1-real-added-item",
         sourceId: "m1-real-added",
         x: $half_width,
         y: 0,
         width: $right_width,
         height: $height,
         scaleMode: "contain",
         crop: {top: 0, right: 0, bottom: 0, left: 0},
         zIndex: 1,
         visible: true
       }]' "$scene" >"$added_candidate"

added_response="$temporary_directory/added-response.json"
added_headers="$temporary_directory/added-headers.txt"
status="$(curl --silent --show-error --output "$added_response" --dump-header "$added_headers" \
    --write-out '%{http_code}' --request PUT \
    --header 'Content-Type: application/json' \
    --header "Host: $host_header" \
    --header "Origin: $origin" \
    --header "If-Match: $etag" \
    --data-binary "@$added_candidate" \
    "$base_url/api/v1/scene")"
if [ "$status" != "200" ]; then
    echo "Adding the real RTSP source through the M1 API failed with HTTP $status" >&2
    exit 1
fi
jq -e '.sources | length == 2' "$added_response" >/dev/null
jq -e '.items | length == 2' "$added_response" >/dev/null
added_etag="$(awk 'tolower($1) == "etag:" { gsub("\r", "", $2); print $2; exit }' "$added_headers")"
test -n "$added_etag"

sleep "$two_up_seconds"

final_candidate="$temporary_directory/final-candidate.json"
jq \
    --argjson width "$width" \
    --argjson height "$height" \
    '.sources |= map(select(.id == "m1-real-added"))
     | .items |= map(select(.sourceId == "m1-real-added"))
     | .items[0].x = 0
     | .items[0].y = 0
     | .items[0].width = $width
     | .items[0].height = $height
     | .items[0].zIndex = 0' "$added_response" >"$final_candidate"

final_response="$temporary_directory/final-response.json"
final_headers="$temporary_directory/final-headers.txt"
status="$(curl --silent --show-error --output "$final_response" --dump-header "$final_headers" \
    --write-out '%{http_code}' --request PUT \
    --header 'Content-Type: application/json' \
    --header "Host: $host_header" \
    --header "Origin: $origin" \
    --header "If-Match: $added_etag" \
    --data-binary "@$final_candidate" \
    "$base_url/api/v1/scene")"
if [ "$status" != "200" ]; then
    echo "Removing the original RTSP source through the M1 API failed with HTTP $status" >&2
    exit 1
fi
jq -e '(.sources | length) == 1 and .sources[0].id == "m1-real-added"' "$final_response" >/dev/null
jq -e --argjson width "$width" --argjson height "$height" \
    '.items | length == 1 and .[0].width == $width and .[0].height == $height' \
    "$final_response" >/dev/null

final_etag="$(awk 'tolower($1) == "etag:" { gsub("\r", "", $2); print $2; exit }' "$final_headers")"
test -n "$final_etag"
echo "M1 real-camera control mutations passed: source add/remove, move/resize, mute, volume, and revision $final_etag."
