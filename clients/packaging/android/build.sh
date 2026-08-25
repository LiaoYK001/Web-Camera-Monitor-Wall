#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: build.sh <package-version> <output-directory>" >&2
  exit 2
fi
version=$1
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]] || {
  echo "package version is invalid" >&2
  exit 2
}
output=$(realpath -m "$2")
repo_root=$(git rev-parse --show-toplevel)

: "${QT_ANDROID_ROOT:?QT_ANDROID_ROOT is required}"
: "${ANDROID_SDK_ROOT:?ANDROID_SDK_ROOT is required}"
: "${ANDROID_NDK_ROOT:?ANDROID_NDK_ROOT is required}"
: "${GSTREAMER_ROOT_ANDROID:?GSTREAMER_ROOT_ANDROID is required}"
: "${SODIUM_ANDROID_ROOT:?SODIUM_ANDROID_ROOT is required}"
: "${WEBOBS_ANDROID_QML6_PLUGIN:?WEBOBS_ANDROID_QML6_PLUGIN is required}"
: "${WEBOBS_ANDROID_KEYSTORE:?WEBOBS_ANDROID_KEYSTORE is required}"
: "${WEBOBS_ANDROID_KEY_ALIAS:?WEBOBS_ANDROID_KEY_ALIAS is required}"
: "${QT_ANDROID_KEYSTORE_STORE_PASS:?QT_ANDROID_KEYSTORE_STORE_PASS is required}"
: "${QT_ANDROID_KEYSTORE_KEY_PASS:?QT_ANDROID_KEYSTORE_KEY_PASS is required}"

for variable in QT_SOURCE_ARCHIVE GST_SOURCE_ARCHIVE GST_BASE_SOURCE_ARCHIVE \
  GST_GOOD_SOURCE_ARCHIVE GST_BAD_SOURCE_ARCHIVE GST_UGLY_SOURCE_ARCHIVE \
  GST_LIBAV_SOURCE_ARCHIVE GST_RS_SOURCE_ARCHIVE GST_ANDROID_BUNDLE \
  SODIUM_SOURCE_ARCHIVE; do
  [[ -n "${!variable:-}" && -f "${!variable}" ]] || {
    echo "$variable must name a verified local archive" >&2
    exit 2
  }
done

python3 "$repo_root/clients/scripts/verify_dependency_lock.py" --require-platform android \
  --artifact "qt-source=$QT_SOURCE_ARCHIVE" \
  --artifact "gstreamer-source=$GST_SOURCE_ARCHIVE" \
  --artifact "gstreamer-plugins-base-source=$GST_BASE_SOURCE_ARCHIVE" \
  --artifact "gstreamer-plugins-good-source=$GST_GOOD_SOURCE_ARCHIVE" \
  --artifact "gstreamer-plugins-bad-source=$GST_BAD_SOURCE_ARCHIVE" \
  --artifact "gstreamer-plugins-ugly-source=$GST_UGLY_SOURCE_ARCHIVE" \
  --artifact "gstreamer-libav-source=$GST_LIBAV_SOURCE_ARCHIVE" \
  --artifact "gstreamer-plugins-rs-source=$GST_RS_SOURCE_ARCHIVE" \
  --artifact "gstreamer-android-universal=$GST_ANDROID_BUNDLE" \
  --artifact "libsodium-source=$SODIUM_SOURCE_ARCHIVE"

qmake="$QT_ANDROID_ROOT/bin/qmake6"
[[ -x "$qmake" ]] || qmake="$QT_ANDROID_ROOT/bin/qmake"
[[ -x "$qmake" && "$("$qmake" -query QT_VERSION)" == "6.11.2" ]]
[[ -x "$ANDROID_NDK_ROOT/ndk-build" ]]
grep -Eq '^Pkg\.Revision[[:space:]]*=[[:space:]]*27\.2\.' "$ANDROID_NDK_ROOT/source.properties"
[[ -x "$ANDROID_SDK_ROOT/build-tools/36.0.0/apksigner" ]]
[[ -f "$WEBOBS_ANDROID_QML6_PLUGIN" ]]
[[ -f "$WEBOBS_ANDROID_KEYSTORE" ]]
[[ -d "$SODIUM_ANDROID_ROOT/lib/pkgconfig" ]]
command -v ninja >/dev/null
command -v unzip >/dev/null
[[ "$(javac -version 2>&1)" == javac\ 21.* ]]
grep -Eq '^Version:[[:space:]]*1\.28\.6$' \
  "$GSTREAMER_ROOT_ANDROID/arm64/lib/pkgconfig/gstreamer-1.0.pc"
grep -Eq '^Version:[[:space:]]*1\.0\.22$' "$SODIUM_ANDROID_ROOT/lib/pkgconfig/libsodium.pc"

work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
package_source="$work/package-source"
cp -a "$repo_root/clients/android" "$package_source"
cp -a "$repo_root/clients/packaging/android/jni" "$package_source/jni"
mkdir -p "$package_source/assets/licenses" "$package_source/assets/source-patches"
install -m 0644 "$repo_root/LICENSE" "$package_source/assets/licenses/WebObs-GPL-2.0-or-later.txt"
install -m 0644 "$repo_root/clients/packaging/THIRD_PARTY_NOTICES.md" \
  "$package_source/assets/licenses/THIRD_PARTY_NOTICES.md"
install -m 0644 "$repo_root/clients/dependencies.lock.json" \
  "$package_source/assets/dependencies.lock.json"
install -m 0644 \
  "$repo_root/clients/packaging/android/patches/gst-plugins-good-1.28.6-qml6-android.patch" \
  "$package_source/assets/source-patches/gst-plugins-good-1.28.6-qml6-android.patch"

GSTREAMER_ROOT_ANDROID="$GSTREAMER_ROOT_ANDROID" "$ANDROID_NDK_ROOT/ndk-build" \
  -C "$package_source" NDK_PROJECT_PATH="$package_source" \
  NDK_APPLICATION_MK="$package_source/jni/Application.mk" \
  APP_BUILD_SCRIPT="$package_source/jni/Android.mk" V=0
native_libs="$package_source/libs/arm64-v8a"
[[ -f "$native_libs/libgstreamer_android.so" ]]
[[ "$WEBOBS_ANDROID_QML6_PLUGIN" == *.a ]]

export QT_ANDROID_KEYSTORE_PATH="$WEBOBS_ANDROID_KEYSTORE"
export QT_ANDROID_KEYSTORE_ALIAS="$WEBOBS_ANDROID_KEY_ALIAS"

build="$work/build"
"$QT_ANDROID_ROOT/bin/qt-cmake" -S "$repo_root/clients" -B "$build" -GNinja \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-29 \
  -DANDROID_SDK_ROOT="$ANDROID_SDK_ROOT" -DANDROID_NDK_ROOT="$ANDROID_NDK_ROOT" \
  -DWEBOBS_PACKAGE_VERSION="$version" \
  -DWEBOBS_GSTREAMER_ANDROID_ROOT="$GSTREAMER_ROOT_ANDROID" \
  -DWEBOBS_SODIUM_ANDROID_ROOT="$SODIUM_ANDROID_ROOT" \
  -DWEBOBS_ANDROID_PACKAGE_SOURCE_DIR="$package_source" \
  -DQT_ANDROID_SIGN_APK=ON
cmake --build "$build" --target apk

mapfile -t apks < <(find "$build" -type f -name '*release-signed.apk' -print)
[[ ${#apks[@]} -eq 1 ]]
mkdir -p "$output"
artifact="$output/webobs-native-$version-android-arm64-v8a.apk"
install -m 0644 "${apks[0]}" "$artifact"
"$ANDROID_SDK_ROOT/build-tools/36.0.0/apksigner" verify --verbose --print-certs "$artifact"
unzip -Z1 "$artifact" | grep -q '^lib/arm64-v8a/libgstreamer_android\.so$'
unzip -Z1 "$artifact" | grep -q '^assets/licenses/THIRD_PARTY_NOTICES\.md$'
unzip -Z1 "$artifact" | grep -q '^assets/source-patches/gst-plugins-good-1\.28\.6-qml6-android\.patch$'
if unzip -Z1 "$artifact" | grep -Eq '^lib/(x86|x86_64|armeabi-v7a)/'; then
  echo "APK contains an unsupported ABI" >&2
  exit 2
fi
sha256sum "$artifact" > "$artifact.sha256"
echo "Built and verified signed arm64-v8a APK: $artifact"
