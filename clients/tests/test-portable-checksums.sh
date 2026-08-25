#!/usr/bin/env bash
set -euo pipefail

root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT

mkdir -p "$temporary/output"
printf 'portable release artifact\n' > "$temporary/output/example.AppImage"
(
  cd "$temporary/output"
  sha256sum example.AppImage > example.AppImage.sha256
)

mkdir -p "$temporary/download"
cp "$temporary/output/example.AppImage" "$temporary/output/example.AppImage.sha256" \
  "$temporary/download/"
(cd "$temporary/download" && sha256sum --check example.AppImage.sha256)

if grep -F "$temporary" "$temporary/output/example.AppImage.sha256" >/dev/null; then
  echo "Portable checksum unexpectedly contains a builder-local path." >&2
  exit 1
fi

grep -F '(cd "$output_dir" && sha256sum "webobs-native-$version-linux-x86_64.AppImage"' \
  "$root/clients/packaging/linux/build-appimage.sh" >/dev/null
grep -F '(cd "$output_dir" && sha256sum "webobs-native-$version-linux-x86_64.flatpak"' \
  "$root/clients/packaging/linux/build-flatpak.sh" >/dev/null
grep -F 'sha256sum "$artifact_name" > "$artifact_name.sha256"' \
  "$root/clients/packaging/finalize-artifacts.sh" >/dev/null

echo "Portable release checksum gate passed."
