#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: build-qml6-plugin.sh <verified-gst-good-1.28.6.tar.xz> <qt-android-root> <output-dir>" >&2
  exit 2
fi

archive=$(realpath "$1")
qt_root=$(realpath "$2")
output=$(realpath -m "$3")
repo_root=$(git rev-parse --show-toplevel)
patch_file="$repo_root/clients/packaging/android/patches/gst-plugins-good-1.28.6-qml6-android.patch"
: "${ANDROID_NDK_ROOT:?ANDROID_NDK_ROOT is required}"
: "${GSTREAMER_ROOT_ANDROID:?GSTREAMER_ROOT_ANDROID is required}"

python3 "$repo_root/clients/scripts/verify_dependency_lock.py" \
  --artifact "gstreamer-plugins-good-source=$archive"
[[ -x "$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android29-clang" ]]
grep -Eq '^Pkg\.Revision[[:space:]]*=[[:space:]]*27\.2\.' "$ANDROID_NDK_ROOT/source.properties"
[[ -d "$qt_root/lib/cmake/Qt6" ]]
[[ -d "$GSTREAMER_ROOT_ANDROID/arm64/lib/pkgconfig" ]]
command -v meson >/dev/null
command -v ninja >/dev/null
command -v patch >/dev/null

work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
mkdir -p "$output"
tar -xJf "$archive" -C "$work"
source_dir="$work/gst-plugins-good-1.28.6"
patch -d "$source_dir" -p1 --forward --reject-file=- < "$patch_file"

toolchain="$work/android-arm64.ini"
compiler_root="$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/linux-x86_64/bin"
cat > "$toolchain" <<EOF
[binaries]
c = '$compiler_root/aarch64-linux-android29-clang'
cpp = '$compiler_root/aarch64-linux-android29-clang++'
ar = '$compiler_root/llvm-ar'
strip = '$compiler_root/llvm-strip'
pkg-config = 'pkg-config'
cmake = 'cmake'

[host_machine]
system = 'android'
cpu_family = 'aarch64'
cpu = 'armv8-a'
endian = 'little'
EOF

export PKG_CONFIG_LIBDIR="$GSTREAMER_ROOT_ANDROID/arm64/lib/pkgconfig"
export PKG_CONFIG_SYSROOT_DIR="$GSTREAMER_ROOT_ANDROID/arm64"
export CMAKE_PREFIX_PATH="$qt_root"
meson setup "$work/build" "$source_dir" \
  --cross-file "$toolchain" --buildtype release --default-library static --wrap-mode nodownload \
  --prefix "$work/stage" -Dauto_features=disabled -Dqt6=enabled
meson compile -C "$work/build" gstqml6
meson install -C "$work/build"

plugin=$(find "$work/stage" -type f -name 'libgstqml6.a' -print -quit)
[[ -n "$plugin" && -f "$plugin" ]]
"$compiler_root/llvm-ar" t "$plugin" | grep -q '\.o$'
install -m 0644 "$plugin" "$output/libgstqml6.a"
sha256sum "$output/libgstqml6.a" > "$output/libgstqml6.a.sha256"
echo "Built the audited qml6 Android EGL plug-in from verified GStreamer 1.28.6 source."
