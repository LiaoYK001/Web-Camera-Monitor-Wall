#!/bin/sh
set -eu

[ "$#" -eq 1 ] || {
    echo "Usage: verify-source-bundle.sh <absolute-archive.tar.gz>" >&2
    exit 64
}
archive_path="$1"
case "$archive_path" in
    /*) ;;
    *) echo "Archive path must be absolute" >&2; exit 64 ;;
esac
[ -f "$archive_path" ] && [ -f "${archive_path}.sha256" ] || {
    echo "Archive or SHA-256 sidecar is missing" >&2
    exit 66
}

archive_name="$(basename "$archive_path")"
case "$archive_name" in
    webobs-source-*.tar.gz) ;;
    *) echo "Unexpected source archive name" >&2; exit 65 ;;
esac
expected_line="$(cat -- "${archive_path}.sha256")"
[ "${#expected_line}" -eq $((64 + 2 + ${#archive_name})) ] || {
    echo "Invalid SHA-256 sidecar length" >&2
    exit 65
}
printf '%s\n' "$expected_line" | grep -Eq "^[0-9a-f]{64}  ${archive_name}$" || {
    echo "Invalid SHA-256 sidecar format" >&2
    exit 65
}
(cd "$(dirname "$archive_path")" && sha256sum -c "$(basename "${archive_path}.sha256")") >/dev/null

bundle_root="${archive_name%.tar.gz}"
listing="$(tar -tzf "$archive_path")"
printf '%s\n' "$listing" | grep -Fx "$bundle_root/SOURCE-REVISION" >/dev/null
printf '%s\n' "$listing" | grep -Fx "$bundle_root/LICENSE" >/dev/null
printf '%s\n' "$listing" | grep -Fx "$bundle_root/docker/Dockerfile" >/dev/null
printf '%s\n' "$listing" | grep -Fx "$bundle_root/obs/obs-studio/libobs/obs.c" >/dev/null
if printf '%s\n' "$listing" | grep -Eq '(^|/)\.git(/|$)|(^|/)\.env$|(^|/)secrets(/|$)|(^|/)\.\.?(/|$)'; then
    echo "Source archive contains an unsafe or private path" >&2
    exit 65
fi

echo "Corresponding-source bundle verified"
