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
  artifact_name="${artifact##*/}"
  (cd "$artifact_dir" && sha256sum "$artifact_name" > "$artifact_name.sha256")
  "$syft" "$artifact" -o "spdx-json=$artifact.spdx.json"
  "$cosign" sign-blob --yes --bundle "$artifact.sigstore.json" "$artifact"
  [[ -s "$artifact.sha256" && -s "$artifact.spdx.json" && -s "$artifact.sigstore.json" ]]
  (cd "$artifact_dir" && sha256sum --check "$artifact_name.sha256" >/dev/null)
done < <(find "$artifact_dir" -maxdepth 1 -type f -print0)
