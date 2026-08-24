#!/usr/bin/env bash
set -euo pipefail

version="${1:?usage: build-appimage.sh VERSION OUTPUT_DIR}"
output_dir="${2:?usage: build-appimage.sh VERSION OUTPUT_DIR}"
linuxdeploy="${WEBOBS_LINUXDEPLOY:?WEBOBS_LINUXDEPLOY must point to a reviewed linuxdeploy AppImage}"
linuxdeploy_sha256="${WEBOBS_LINUXDEPLOY_SHA256:?WEBOBS_LINUXDEPLOY_SHA256 is required}"
linuxdeploy_qt="${WEBOBS_LINUXDEPLOY_QT_PLUGIN:?WEBOBS_LINUXDEPLOY_QT_PLUGIN must point to a reviewed Qt plugin}"
linuxdeploy_qt_sha256="${WEBOBS_LINUXDEPLOY_QT_PLUGIN_SHA256:?WEBOBS_LINUXDEPLOY_QT_PLUGIN_SHA256 is required}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]]
[[ "$linuxdeploy_sha256" =~ ^[0-9a-f]{64}$ ]]
[[ "$linuxdeploy_qt_sha256" =~ ^[0-9a-f]{64}$ ]]
[[ -f "$linuxdeploy" ]]
[[ -f "$linuxdeploy_qt" ]]
echo "$linuxdeploy_sha256  $linuxdeploy" | sha256sum --check
echo "$linuxdeploy_qt_sha256  $linuxdeploy_qt" | sha256sum --check
[[ "$(gst-launch-1.0 --version | awk '/GStreamer/{print $2; exit}')" == "1.28.6" ]]
[[ "$(pkg-config --modversion libsodium)" == "1.0.22" ]]

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
build="$root/clients/build-appimage"
appdir="$build/AppDir"
rm -rf -- "$build"
mkdir -p "$appdir" "$output_dir"
cmake -S "$root/clients" -B "$build/cmake" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
  -DWEBOBS_PACKAGE_VERSION="$version" -DWEBOBS_ENFORCE_LOCKED_DEPENDENCIES=ON
cmake --build "$build/cmake" --parallel
ctest --test-dir "$build/cmake" --output-on-failure
DESTDIR="$appdir" cmake --install "$build/cmake" --strip

mkdir -p "$appdir/usr/lib/gstreamer-1.0" "$appdir/usr/share/icons/hicolor/scalable/apps"
cp "$root/clients/packaging/io.github.liaoyk001.WebObsNative.svg" \
  "$appdir/usr/share/icons/hicolor/scalable/apps/io.github.liaoyk001.WebObsNative.svg"
cp "$(command -v gst-launch-1.0)" "$appdir/usr/bin/gst-launch-1.0"

plugins=(rtspsrc uridecodebin3 decodebin3 qml6glsink whepclientsrc rtph264depay rtph265depay \
         h264parse h265parse matroskamux matroskademux mp4mux autoaudiosink autoaudiosrc \
         audioconvert audioresample wavenc appsink vah264dec vah265dec)
declare -A copied=()
libraries=()
for element in "${plugins[@]}"; do
  plugin="$(gst-inspect-1.0 "$element" | awk -F': +' '/^[[:space:]]*Filename/{print $2; exit}')"
  [[ -n "$plugin" && -f "$plugin" ]] || { echo "missing required GStreamer element: $element" >&2; exit 1; }
  if [[ -z "${copied[$plugin]:-}" ]]; then
    target="$appdir/usr/lib/gstreamer-1.0/$(basename "$plugin")"
    cp "$plugin" "$target"
    libraries+=(--library "$target")
    copied[$plugin]=1
  fi
done

chmod +x "$linuxdeploy"
export QMAKE="${QMAKE:-$(command -v qmake6)}"
export QML_SOURCES_PATHS="$root/clients/qml"
plugin_dir="$build/linuxdeploy-plugins"
mkdir -p "$plugin_dir"
cp "$linuxdeploy_qt" "$plugin_dir/linuxdeploy-plugin-qt"
chmod 0755 "$plugin_dir/linuxdeploy-plugin-qt"
export PATH="$plugin_dir:$PATH"
"$linuxdeploy" --appdir "$appdir" \
  --executable "$appdir/usr/bin/webobs-native" \
  --executable "$appdir/usr/bin/gst-launch-1.0" \
  --desktop-file "$root/clients/packaging/io.github.liaoyk001.WebObsNative.desktop" \
  --icon-file "$root/clients/packaging/io.github.liaoyk001.WebObsNative.svg" \
  "${libraries[@]}" --plugin qt --output appimage
artifact="$(find . -maxdepth 1 -type f -name '*.AppImage' -printf '%p\n' | head -n 1)"
[[ -n "$artifact" ]]
mv "$artifact" "$output_dir/webobs-native-$version-linux-x86_64.AppImage"
sha256sum "$output_dir/webobs-native-$version-linux-x86_64.AppImage" > \
  "$output_dir/webobs-native-$version-linux-x86_64.AppImage.sha256"
