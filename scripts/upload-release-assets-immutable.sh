#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: upload-release-assets-immutable.sh TAG ASSET..." >&2
  exit 64
fi

tag=$1
shift
[[ "$tag" =~ ^v[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || {
  echo "release tag is invalid" >&2
  exit 64
}
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GH_TOKEN:?GH_TOKEN is required}"
[[ "$GITHUB_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || {
  echo "GitHub repository identity is invalid" >&2
  exit 64
}
command -v gh >/dev/null

temporary_root=$(mktemp -d)
cleanup() {
  case "$temporary_root" in
    /tmp/*|"${RUNNER_TEMP:-/nonexistent}"/*) rm -rf -- "$temporary_root" ;;
  esac
}
trap cleanup EXIT INT TERM

declare -A local_names=()
for asset in "$@"; do
  [[ -f "$asset" && ! -L "$asset" ]] || {
    echo "release asset must be a regular non-symlink file" >&2
    exit 66
  }
  name=${asset##*/}
  [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$ ]] || {
    echo "release asset name is invalid" >&2
    exit 64
  }
  [[ -z "${local_names[$name]:-}" ]] || {
    echo "duplicate local release asset name" >&2
    exit 64
  }
  local_names[$name]=1

  asset_count=$(gh api "repos/$GITHUB_REPOSITORY/releases/tags/$tag" \
    --jq "[.assets[] | select(.name == \"$name\")] | length")
  [[ "$asset_count" =~ ^[01]$ ]] || {
    echo "release contains duplicate immutable asset names" >&2
    exit 65
  }
  if [[ "$asset_count" == 0 ]]; then
    gh release upload "$tag" "$asset"
    continue
  fi

  existing_directory="$temporary_root/$name"
  mkdir "$existing_directory"
  gh release download "$tag" --pattern "$name" --dir "$existing_directory"
  existing="$existing_directory/$name"
  [[ -f "$existing" && ! -L "$existing" ]] || {
    echo "existing release asset could not be verified" >&2
    exit 65
  }
  cmp --silent -- "$asset" "$existing" || {
    echo "immutable release asset already exists with different content: $name" >&2
    exit 65
  }
  echo "Verified existing immutable release asset: $name"
done
