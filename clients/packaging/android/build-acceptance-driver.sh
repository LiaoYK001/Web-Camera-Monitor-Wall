#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: build-acceptance-driver.sh <private-output-apk>" >&2
  exit 2
fi
: "${ANDROID_SDK_ROOT:?ANDROID_SDK_ROOT is required}"
: "${WEBOBS_ANDROID_KEYSTORE:?WEBOBS_ANDROID_KEYSTORE is required}"
: "${WEBOBS_ANDROID_KEY_ALIAS:?WEBOBS_ANDROID_KEY_ALIAS is required}"
: "${QT_ANDROID_KEYSTORE_STORE_PASS:?QT_ANDROID_KEYSTORE_STORE_PASS is required}"
: "${QT_ANDROID_KEYSTORE_KEY_PASS:?QT_ANDROID_KEYSTORE_KEY_PASS is required}"

output=$(realpath -m "$1")
repo_root=$(git rev-parse --show-toplevel)
source_root="$repo_root/clients/packaging/android/acceptance-driver"
tools="$ANDROID_SDK_ROOT/build-tools/36.0.0"
platform="$ANDROID_SDK_ROOT/platforms/android-36/android.jar"
for executable in aapt d8 zipalign apksigner; do [[ -x "$tools/$executable" ]]; done
[[ -f "$platform" && -f "$WEBOBS_ANDROID_KEYSTORE" ]]
command -v javac >/dev/null

work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
mkdir -p "$work/classes" "$(dirname "$output")"
javac --release 17 -classpath "$platform" -d "$work/classes" \
  "$source_root/src/org/webobs/nativeclient/acceptance/WebObsAcceptanceInstrumentation.java"
"$tools/d8" --release --lib "$platform" --output "$work/dex" \
  $(find "$work/classes" -type f -name '*.class' -print)
"$tools/aapt" package -f -M "$source_root/AndroidManifest.xml" -I "$platform" \
  -F "$work/unsigned.apk"
(cd "$work/dex" && "$tools/aapt" add "$work/unsigned.apk" classes.dex)
"$tools/zipalign" -f -p 4 "$work/unsigned.apk" "$work/aligned.apk"
"$tools/apksigner" sign --ks "$WEBOBS_ANDROID_KEYSTORE" \
  --ks-key-alias "$WEBOBS_ANDROID_KEY_ALIAS" \
  --ks-pass env:QT_ANDROID_KEYSTORE_STORE_PASS \
  --key-pass env:QT_ANDROID_KEYSTORE_KEY_PASS \
  --out "$output" "$work/aligned.apk"
"$tools/apksigner" verify --verbose --print-certs "$output"
chmod 0600 "$output"
echo "Built private signature-matched Android acceptance driver. Do not upload this artifact."
