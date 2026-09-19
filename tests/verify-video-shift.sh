#!/usr/bin/env bash
# Verifies that a negative per-track sync offset really delays the video by
# B = max(0, -min(d_i)) in the gateway's audio-mix command.
#
# It runs the same filter graph and the same setts bitstream filter the
# transcoder uses, but writes to a file instead of to MediaMTX.  A file output
# is required because an RTSP/WebRTC receiver re-bases each stream onto its own
# RTP timeline, which hides the offset (ffprobe then reports both streams
# starting near zero).  Comparing the maximum PTS of the two runs isolates the
# applied shift exactly.
#
# It owns its own MediaMTX on 8554/9997 and refuses to run while another
# instance listens.  Usage: bash tests/verify-video-shift.sh
set -u

RTSP_PORT=8554
API_PORT=9997
CACHE="${WEBOBS_CACHE:-$HOME/.cache/webobs-dev/$(ls "$HOME/.cache/webobs-dev" | head -1)}"
WORK="$(mktemp -d /tmp/webobs-shift-XXXXXX)"
B=2000

cleanup() {
  [ -n "${PUB:-}" ] && kill "$PUB" 2>/dev/null
  [ -n "${MTX:-}" ] && kill "$MTX" 2>/dev/null
  sleep 1
  rm -rf "$WORK"
}
trap cleanup EXIT

port_free() {
  python3 - "$1" <<'PY'
import socket, sys
port = int(sys.argv[1])
s = socket.socket(); s.settimeout(1)
try:
    s.connect(("127.0.0.1", port)); print("busy"); raise SystemExit(1)
except Exception:
    print("free")
finally:
    s.close()
PY
}

[ "$(port_free "$RTSP_PORT")" = free ] || { echo "port $RTSP_PORT is busy; stop the development session first" >&2; exit 2; }
[ "$(port_free "$API_PORT")" = free ] || { echo "port $API_PORT is busy; stop the development session first" >&2; exit 2; }

cat > "$WORK/mtx.yml" <<YML
logLevel: warn
rtsp: yes
rtspAddress: :$RTSP_PORT
rtspTransports: [tcp]
api: yes
apiAddress: 127.0.0.1:$API_PORT
webrtc: no
hls: no
paths:
  all_others:
YML

"$CACHE/bin/mediamtx" "$WORK/mtx.yml" >"$WORK/mtx.log" 2>&1 &
MTX=$!
sleep 2

ffmpeg -hide_banner -loglevel error -re -f lavfi -i testsrc2=size=320x240:rate=25 \
  -f lavfi -i sine=frequency=440:sample_rate=48000 -f lavfi -i sine=frequency=880:sample_rate=48000 \
  -map 0:v -map 1:a -map 2:a -c:v libx264 -preset ultrafast -tune zerolatency -g 25 -bf 0 -pix_fmt yuv420p \
  -c:a libopus -b:a 96k -ar 48000 -ac 1 -t 90 -rtsp_transport tcp -f rtsp "rtsp://127.0.0.1:$RTSP_PORT/synth" \
  >"$WORK/synth.log" 2>&1 &
PUB=$!
sleep 5

# Track 0 gets offset -B so its delay normalises to 0, track 1 keeps 0 so its
# delay becomes B; the video must move by the same B.
GRAPH="[0:a:0]volume=1.0[m0];[0:a:1]adelay=delays=${B}:all=1,volume=1.0[m1];[m0][m1]amix=inputs=2:normalize=0[amixed]"

ffmpeg -hide_banner -loglevel error -y -rtsp_transport tcp -i "rtsp://127.0.0.1:$RTSP_PORT/synth" \
  -filter_complex "$GRAPH" -map 0:v -map "[amixed]" -c:v copy -t 8 -c:a libopus -ar 48000 -ac 2 \
  "$WORK/without-shift.mkv" 2>&1 | head -3
ffmpeg -hide_banner -loglevel error -y -rtsp_transport tcp -i "rtsp://127.0.0.1:$RTSP_PORT/synth" \
  -filter_complex "$GRAPH" -map 0:v -map "[amixed]" -c:v copy \
  -bsf:v "setts=ts=TS+${B}/(1000*TB)" -t 8 -c:a libopus -ar 48000 -ac 2 \
  "$WORK/with-shift.mkv" 2>&1 | head -3

python3 - "$WORK" "$B" <<'PY'
import subprocess, sys
work, expected = sys.argv[1], float(sys.argv[2]) / 1000.0

def extrema(path, stream, which):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', stream,
                          '-show_entries', 'packet=pts_time', '-of', 'csv=p=0', path],
                         capture_output=True, text=True).stdout
    values = sorted(float(v.strip().rstrip(',')) for v in out.split() if v.strip().strip(','))
    if not values:
        return None
    return values[0] if which == 'min' else values[-1]

video_shift = extrema(f'{work}/with-shift.mkv', 'v', 'max') - extrema(f'{work}/without-shift.mkv', 'v', 'max')
audio_shift = extrema(f'{work}/with-shift.mkv', 'a', 'max') - extrema(f'{work}/without-shift.mkv', 'a', 'max')
print(f'video max PTS shift: {video_shift:.3f} s (expected {expected:.3f})')
print(f'audio max PTS shift: {audio_shift:.3f} s (expected 0.000)')
ok = abs(video_shift - expected) < 0.05 and abs(audio_shift) < 0.05
print('PASS: the video is delayed by exactly B while the audio stays put' if ok
      else 'FAIL: the applied shift does not match B')
raise SystemExit(0 if ok else 1)
PY
