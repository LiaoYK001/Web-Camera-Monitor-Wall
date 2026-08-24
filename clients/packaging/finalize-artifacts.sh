#!/usr/bin/env bash
set -euo pipefail

artifact_dir="${1:?usage: finalize-artifacts.sh ARTIFACT_DIR}"
syft="${WEBOBS_SYFT:?WEBOBS_SYFT must point to a reviewed syft binary}"
syft_sha256="${WEBOBS_SYFT_SHA256:?WEBOBS_SYFT_SHA256 is required}"
cosign="${WEBOBS_COSIGN:?WEBOBS_COSIGN must point to a reviewed cosign binary}"
cosign_sha256="${WEBOBS_COSIGN_SHA256:?WEBOBS_COSIGN_SHA256 is required}"
for specification in "$syft_sha256  $syft" "$cosign_sha256  $cosign"; do
  [[ "$specification" =~ ^[0-9a-f]{64}[[:space:]][[:space:]] ]] || exit 1
  echo "$specification" | sha256sum --check
done
chmod +x "$syft" "$cosign"
while IFS= read -r -d '' artifact; do
  case "$artifact" in *.sha256|*.spdx.json|*.sigstore.json) continue;; esac
  sha256sum "$artifact" > "$artifact.sha256"
  "$syft" "$artifact" -o "spdx-json=$artifact.spdx.json"
  "$cosign" sign-blob --yes --bundle "$artifact.sigstore.json" "$artifact"
done < <(find "$artifact_dir" -maxdepth 1 -type f -print0)
