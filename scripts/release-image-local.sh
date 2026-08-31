#!/usr/bin/env bash
set -euo pipefail

image="${1:-}"
version="${2:-}"
[[ "$image" =~ ^ghcr\.io/[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}$ ]] || {
  echo "usage: $0 ghcr.io/owner/repository <vX.Y|vX.Y.Z|dev>" >&2
  exit 64
}
[[ "$version" == dev || "$version" =~ ^v[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || {
  echo "version must be dev, vX.Y, or vX.Y.Z" >&2
  exit 64
}

repository_root="$(git rev-parse --show-toplevel)"
cd "$repository_root"
python_command="python3"
if ! python3 --version >/dev/null 2>&1; then
    command -v python >/dev/null 2>&1 || {
        echo "Python 3 is required for release receipt verification" >&2
        exit 69
    }
    python_command="python"
fi
git diff --quiet --ignore-submodules=none
git diff --cached --quiet --ignore-submodules=none
./scripts/check-executable-bits.sh
./tests/run-public-audit.sh
"$python_command" ./scripts/verify-local-gate-receipts.py
if [[ "$version" =~ ^v2\.3(\.|$) ]]; then
    "$python_command" ./scripts/verify-m7-gate-receipts.py
fi

revision="$(git rev-parse HEAD)"
short_revision="$(git rev-parse --short=12 HEAD)"
cache_root="${repository_root}/build/release-cache"
next_cache="${repository_root}/build/release-cache-next"
rm -rf -- "$next_cache"

tags=(--tag "${image}:sha-${short_revision}")
if [ "$version" = dev ]; then
    tags+=(--tag "${image}:dev")
    build_version="2.3.0-dev.${short_revision}"
    build_milestone="v2-M7-dev"
else
    [ "$(git branch --show-current)" = main ] || { echo "stable publication must run from main" >&2; exit 65; }
    [ "$(git rev-parse "${version}^{commit}")" = "$revision" ] || {
        echo "release tag must resolve to HEAD" >&2; exit 65;
    }
    remote_refs="$(git ls-remote --tags origin "refs/tags/${version}" "refs/tags/${version}^{}")"
    remote_revision="$(printf '%s\n' "$remote_refs" | awk -v tag="refs/tags/${version}^{}" '$2==tag {print $1}')"
    [ -n "$remote_revision" ] || remote_revision="$(printf '%s\n' "$remote_refs" | awk -v tag="refs/tags/${version}" '$2==tag {print $1}')"
    [ "$remote_revision" = "$revision" ] || {
        echo "the immutable release tag must exist on origin and resolve to HEAD" >&2; exit 65;
    }
    : "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required for a stable release}"
    : "${GH_TOKEN:?GH_TOKEN is required for a stable release}"
    command -v gh >/dev/null
    build_version="${version#v}"
    [[ "$build_version" =~ ^[0-9]+\.[0-9]+$ ]] && build_version="${build_version}.0"
    if [[ "$version" =~ ^v2\.3(\.|$) ]]; then
        build_milestone="v2-M7"
    elif [[ "$version" =~ ^v2\.2(\.|$) ]]; then
        build_milestone="v2-M6"
    elif [[ "$version" =~ ^v2\.1(\.|$) ]]; then
        build_milestone="v2-M5"
    else
        build_milestone="v2-M3"
    fi
fi

cache_arguments=()
[ ! -d "$cache_root" ] || cache_arguments+=(--cache-from "type=local,src=${cache_root}")
cache_arguments+=(--cache-to "type=local,dest=${next_cache},mode=max")
docker buildx build --platform linux/amd64 --file docker/Dockerfile \
  --build-arg "WEBOBS_BUILD_VERSION=${build_version}" \
  --build-arg "WEBOBS_BUILD_MILESTONE=${build_milestone}" \
  --label "org.opencontainers.image.revision=${revision}" \
  --label "org.opencontainers.image.version=${version}" \
  "${cache_arguments[@]}" --provenance=mode=max --sbom=true "${tags[@]}" --push .

rm -rf -- "$cache_root"
mv -- "$next_cache" "$cache_root"
inspect="$(docker buildx imagetools inspect "${image}:sha-${short_revision}")"
digest="$(printf '%s\n' "$inspect" | awk '$1=="Digest:" && $2 ~ /^sha256:[0-9a-f]{64}$/ {print $2; exit}')"
[ -n "$digest" ] || { echo "candidate OCI digest could not be verified" >&2; exit 65; }

if [ "$version" = dev ]; then
    echo "published ${image}:dev and ${image}:sha-${short_revision} at ${digest}"
    exit 0
fi

release_root="${repository_root}/build/release-assets/${version}"
mkdir -p "$release_root"
./scripts/create-source-bundle.sh "$version" "$release_root"
source_archive="${release_root}/webobs-source-${version}.tar.gz"
./scripts/verify-source-bundle.sh "$source_archive"
notes="${release_root}/RELEASE-NOTES.md"
cat > "$notes" <<EOF
# Web Camera Monitor Wall ${version}

- Source revision: \`${revision}\`
- OCI candidate: \`${image}:sha-${short_revision}\`
- OCI digest: \`${digest}\`
- Milestone: \`${build_milestone}\`

The version and latest tags are promoted from this exact candidate digest only after this draft and its corresponding-source assets are published.
EOF

if ! gh release view "$version" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
    gh release create "$version" --repo "$GITHUB_REPOSITORY" --verify-tag --draft \
        --title "$version" --notes-file "$notes"
fi
is_draft="$(gh release view "$version" --repo "$GITHUB_REPOSITORY" --json isDraft --jq .isDraft)"
[ "$is_draft" = true ] || { echo "refusing to mutate an already-published release" >&2; exit 65; }
./scripts/upload-release-assets-immutable.sh "$version" "$source_archive" "${source_archive}.sha256"
gh release edit "$version" --repo "$GITHUB_REPOSITORY" --draft=false

docker buildx imagetools create \
    --tag "${image}:${version}" --tag "${image}:latest" "${image}@${digest}"
for promoted in "$version" latest; do
    promoted_digest="$(docker buildx imagetools inspect "${image}:${promoted}" | \
        awk '$1=="Digest:" && $2 ~ /^sha256:[0-9a-f]{64}$/ {print $2; exit}')"
    [ "$promoted_digest" = "$digest" ] || {
        echo "promoted ${promoted} tag does not match the candidate digest" >&2; exit 65;
    }
done
gh release edit "$version" --repo "$GITHUB_REPOSITORY" --latest
echo "published ${version}, latest, and sha-${short_revision} from ${digest}"
