#!/bin/sh
set -eu

required='docker/backup.sh
docker/entrypoint.sh
gateway/transcode-on-demand.sh
scripts/check-executable-bits.sh
scripts/benchmark-video-pipelines.sh
scripts/create-source-bundle.sh
scripts/release-image-local.sh
scripts/verify-source-bundle.sh
clients/packaging/finalize-artifacts.sh
clients/packaging/android/build-acceptance-driver.sh
clients/packaging/android/build-qml6-plugin.sh
clients/packaging/android/build.sh
clients/packaging/linux/build-appimage.sh
clients/packaging/linux/build-flatpak.sh
clients/packaging/linux/install-signed-appimage.sh
clients/packaging/linux/rollback-appimage.sh
clients/tests/run-android-reference-gate.py
tests/rtsp-fixture/m1-real-control.sh
tests/rtsp-fixture/probe.sh
tests/rtsp-fixture/publish-audio.sh
tests/rtsp-fixture/publish-hevc.sh
tests/rtsp-fixture/publish.sh
tests/run-contracts.sh
tests/run-m1-real-camera.sh
tests/run-m10-real-mjpeg.sh
tests/run-public-audit.sh
tests/run-real-camera.sh
tests/run-smoke.sh
tests/run-v2-true-direct.sh'

failed=0
printf '%s\n' "$required" | while IFS= read -r path; do
    mode="$(git ls-files -s -- "$path" | awk '{print $1}')"
    if [ "$mode" != 100755 ]; then
        echo "$path must be committed with Git mode 100755 (found ${mode:-missing})" >&2
        failed=1
    fi
done

# The loop runs in a subshell on POSIX sh, so perform a single authoritative
# check as well and keep its result in this shell.
for path in $required; do
    mode="$(git ls-files -s -- "$path" | awk '{print $1}')"
    [ "$mode" = 100755 ] || failed=1
done
[ "$failed" -eq 0 ]
