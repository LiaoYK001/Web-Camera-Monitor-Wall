#!/usr/bin/env bash
set -euo pipefail
destination="${1:?usage: rollback-appimage.sh ABSOLUTE_DESTINATION}"
[[ "$destination" = /* && ! -L "$destination" ]]
backup="$destination.previous"
[[ -f "$destination" && -f "$backup" && ! -L "$backup" ]]
temporary="$destination.rollback"
[[ ! -e "$temporary" ]]
mv -- "$destination" "$temporary"
if mv -- "$backup" "$destination"; then
  mv -- "$temporary" "$backup"
  echo "Rolled back WebObs Native and retained the replaced build as the next rollback copy."
else
  mv -- "$temporary" "$destination"
  exit 1
fi
