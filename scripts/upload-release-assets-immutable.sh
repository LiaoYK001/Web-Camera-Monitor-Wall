#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: upload-release-assets-immutable.sh TAG|RELEASE_ID ASSET..." >&2
  exit 64
fi

release_ref=$1
shift
[[ "$release_ref" =~ ^v[0-9]+\.[0-9]+(\.[0-9]+)?$|^[0-9]+$ ]] || {
  echo "release tag or numeric release id is invalid" >&2
  exit 64
}
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GH_TOKEN:?GH_TOKEN is required}"
[[ "$GITHUB_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || {
  echo "GitHub repository identity is invalid" >&2
  exit 64
}
command -v gh >/dev/null

release_id=""
if [[ "$release_ref" =~ ^[0-9]+$ ]]; then
  release_id="$release_ref"
  release_api="repos/$GITHUB_REPOSITORY/releases/$release_id"
  upload_api="$(gh api "$release_api" --jq .upload_url | sed 's/{?name,label}$//')"
else
  release_api="repos/$GITHUB_REPOSITORY/releases/tags/$release_ref"
  upload_api=""
fi

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

  asset_count=$(gh api "$release_api" \
    --jq "[.assets[] | select(.name == \"$name\")] | length")
  [[ "$asset_count" =~ ^[01]$ ]] || {
    echo "release contains duplicate immutable asset names" >&2
    exit 65
  }
  if [[ "$asset_count" == 0 ]]; then
    if [ -n "$release_id" ]; then
      # Draft release assets are uploaded through uploads.github.com.  The
      # regular api.github.com path returns 404 for this operation.
      gh api --method POST "${upload_api}?name=${name}" \
        -H "Content-Type: application/octet-stream" --input "$asset" >/dev/null
    else
      gh release upload "$release_ref" "$asset"
    fi
    continue
  fi

  existing_directory="$temporary_root/$name"
  mkdir "$existing_directory"
  if [ -n "$release_id" ]; then
    asset_id=$(gh api "$release_api" --jq ".assets[] | select(.name == \"$name\") | .id")
    # gh api has no --output flag; request the binary representation and
    # redirect stdout without allowing metadata or credentials into logs.
    gh api "repos/$GITHUB_REPOSITORY/releases/assets/$asset_id" \
      -H "Accept: application/octet-stream" > "$existing_directory/$name"
  else
    gh release download "$release_ref" --pattern "$name" --dir "$existing_directory"
  fi
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
