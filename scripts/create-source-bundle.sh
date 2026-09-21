#!/bin/sh
set -eu
umask 022

usage() {
    echo "Usage: create-source-bundle.sh <version> <absolute-output-directory>" >&2
    exit 64
}

[ "$#" -eq 2 ] || usage
version="$1"
output_directory="$2"

case "$version" in
    ''|*[!A-Za-z0-9._-]*) echo "Version contains unsupported characters" >&2; exit 64 ;;
esac
case "$output_directory" in
    /*) ;;
    *) echo "Output directory must be absolute" >&2; exit 64 ;;
esac

repository_root="$(git rev-parse --show-toplevel)"
# Git Bash reports the repository root with a drive-letter path while
# `pwd -P` uses the POSIX `/d/...` form.  Canonicalize that comparison so the
# root-directory guard remains strict on both Windows Git Bash and Linux.
case "$repository_root" in
    [A-Za-z]:/*)
        if command -v cygpath >/dev/null 2>&1; then
            repository_root="$(cygpath -u "$repository_root")"
        fi
        ;;
esac
[ "$(pwd -P)" = "$repository_root" ] || {
    echo "Run this command from the repository root" >&2
    exit 64
}
git diff --quiet --ignore-submodules=none
git diff --cached --quiet --ignore-submodules=none

expected_obs_commit="fb4d98bf88fae5fc85cb11fc57f7c5e309282194"
actual_obs_commit="$(git -C obs/obs-studio rev-parse HEAD)"
[ "$actual_obs_commit" = "$expected_obs_commit" ] || {
    echo "OBS submodule pin does not match the reviewed commit" >&2
    exit 65
}
if git submodule status --recursive | grep -Eq '^[+-U]'; then
    echo "A recursive submodule is missing or does not match the Git index" >&2
    exit 65
fi

mkdir -p "$output_directory"
temporary_root="$(mktemp -d)"
cleanup() {
    case "$temporary_root" in
        /tmp/*) rm -rf -- "$temporary_root" ;;
    esac
}
trap cleanup EXIT INT TERM

bundle_name="webobs-source-${version}"
staging_directory="$temporary_root/$bundle_name"
file_list="$temporary_root/tracked-files"
mkdir -p "$staging_directory"
git ls-files --recurse-submodules -z > "$file_list"
tar --null --files-from "$file_list" -cf - | tar -xf - -C "$staging_directory"

root_revision="$(git rev-parse HEAD)"
source_epoch="$(git show -s --format=%ct HEAD)"
{
    echo "version=$version"
    echo "revision=$root_revision"
    echo "obs_revision=$actual_obs_commit"
    echo "source_date_epoch=$source_epoch"
} > "$staging_directory/SOURCE-REVISION"

archive_path="$output_directory/${bundle_name}.tar.gz"
checksum_path="${archive_path}.sha256"
tar --sort=name \
    --mtime="@$source_epoch" \
    --owner=0 --group=0 --numeric-owner \
    -C "$temporary_root" -cf - "$bundle_name" \
    | gzip -n > "$archive_path"
archive_hash="$(sha256sum "$archive_path" | awk '{print $1}')"
printf '%s  %s\n' "$archive_hash" "$(basename "$archive_path")" > "$checksum_path"
chmod 0644 "$archive_path" "$checksum_path"

tar -tzf "$archive_path" | grep -Fx "$bundle_name/SOURCE-REVISION" >/dev/null
tar -tzf "$archive_path" | grep -Fx "$bundle_name/LICENSE" >/dev/null
tar -tzf "$archive_path" | grep -Fx "$bundle_name/docker/Dockerfile" >/dev/null
tar -tzf "$archive_path" | grep -Fx "$bundle_name/obs/obs-studio/libobs/obs.c" >/dev/null
if tar -tzf "$archive_path" | grep -Eq '(^|/)\.git(/|$)|(^|/)\.env$|(^|/)secrets(/|$)'; then
    echo "Source bundle contains forbidden repository metadata or private paths" >&2
    exit 65
fi

echo "Created corresponding-source bundle and SHA-256 sidecar for $version"
