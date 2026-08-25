#!/usr/bin/env bash
set -euo pipefail

root="$(mktemp -d)"
trap 'rm -rf -- "$root"' EXIT HUP INT TERM
destination="$root/webobs-native.AppImage"
backup="$destination.previous"
printf '%s' 'current-build' >"$destination"
printf '%s' 'previous-build' >"$backup"
chmod 0755 "$destination" "$backup"

"$(dirname "$0")/../packaging/linux/rollback-appimage.sh" "$destination" >/dev/null
[[ "$(<"$destination")" == 'previous-build' ]]
[[ "$(<"$backup")" == 'current-build' ]]

"$(dirname "$0")/../packaging/linux/rollback-appimage.sh" "$destination" >/dev/null
[[ "$(<"$destination")" == 'current-build' ]]
[[ "$(<"$backup")" == 'previous-build' ]]
