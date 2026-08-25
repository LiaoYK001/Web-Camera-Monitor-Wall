#!/usr/bin/env bash
set -euo pipefail

version="${1:?usage: build-flatpak.sh VERSION APPIMAGE OUTPUT_DIR}"
appimage="${2:?usage: build-flatpak.sh VERSION APPIMAGE OUTPUT_DIR}"
output_dir="${3:?usage: build-flatpak.sh VERSION APPIMAGE OUTPUT_DIR}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]]
[[ -f "$appimage" ]]
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
build="$root/clients/build-flatpak"
rm -rf -- "$build"
mkdir -p "$build/extract" "$build/repo" "$output_dir"
(cd "$build/extract" && chmod +x "$appimage" && "$appimage" --appimage-extract >/dev/null)
flatpak build-init "$build/app" io.github.liaoyk001.WebObsNative \
  org.freedesktop.Sdk org.freedesktop.Platform 25.08
mkdir -p "$build/app/files/extra"
cp -a "$build/extract/squashfs-root/." "$build/app/files/extra/"
flatpak build-finish "$build/app" \
  --command=/app/extra/AppRun --share=ipc --socket=wayland --socket=fallback-x11 \
  --device=dri --filesystem=xdg-videos:create --talk-name=org.freedesktop.secrets \
  --share=network
flatpak build-export "$build/repo" "$build/app" "$version"
flatpak build-bundle "$build/repo" \
  "$output_dir/webobs-native-$version-linux-x86_64.flatpak" \
  io.github.liaoyk001.WebObsNative "$version"
(cd "$output_dir" && sha256sum "webobs-native-$version-linux-x86_64.flatpak" > \
  "webobs-native-$version-linux-x86_64.flatpak.sha256")
