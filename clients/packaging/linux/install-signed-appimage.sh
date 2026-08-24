#!/usr/bin/env bash
set -euo pipefail

artifact="${1:?usage: install-signed-appimage.sh ARTIFACT SHA256 BUNDLE DESTINATION}"
expected_sha256="${2:?usage: install-signed-appimage.sh ARTIFACT SHA256 BUNDLE DESTINATION}"
bundle="${3:?usage: install-signed-appimage.sh ARTIFACT SHA256 BUNDLE DESTINATION}"
destination="${4:?usage: install-signed-appimage.sh ARTIFACT SHA256 BUNDLE DESTINATION}"
cosign="${WEBOBS_COSIGN:?WEBOBS_COSIGN must point to a reviewed binary}"
cosign_sha256="${WEBOBS_COSIGN_SHA256:?WEBOBS_COSIGN_SHA256 is required}"
identity="${WEBOBS_RELEASE_IDENTITY_REGEXP:-^https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/.github/workflows/release-native-clients.yaml@refs/tags/v2\..+$}"
issuer="${WEBOBS_RELEASE_OIDC_ISSUER:-https://token.actions.githubusercontent.com}"

[[ "$expected_sha256" =~ ^[0-9a-f]{64}$ ]]
[[ "$cosign_sha256" =~ ^[0-9a-f]{64}$ ]]
[[ -f "$artifact" && -f "$bundle" && -f "$cosign" ]]
[[ "$destination" = /* && ! -L "$destination" ]]
echo "$expected_sha256  $artifact" | sha256sum --check
echo "$cosign_sha256  $cosign" | sha256sum --check
chmod +x "$cosign"
"$cosign" verify-blob --bundle "$bundle" --certificate-identity-regexp "$identity" \
  --certificate-oidc-issuer "$issuer" "$artifact" >/dev/null

parent="$(dirname "$destination")"
[[ -d "$parent" && ! -L "$parent" ]]
staging="$(mktemp --tmpdir="$parent" .webobs-native-update.XXXXXXXX)"
trap 'rm -f -- "$staging"' EXIT HUP INT TERM
install -m 0755 "$artifact" "$staging"
QT_QPA_PLATFORM=offscreen "$staging" --version >/dev/null
backup="$destination.previous"
if [[ -e "$backup" && ! -f "$backup" ]]; then
  echo "rollback target is not a regular file" >&2
  exit 1
fi
rm -f -- "$backup"
if [[ -f "$destination" ]]; then mv -- "$destination" "$backup"; fi
if ! mv -- "$staging" "$destination"; then
  if [[ -f "$backup" ]]; then mv -- "$backup" "$destination"; fi
  exit 1
fi
trap - EXIT HUP INT TERM
echo "Signed AppImage update installed; one rollback copy is available at $backup"
