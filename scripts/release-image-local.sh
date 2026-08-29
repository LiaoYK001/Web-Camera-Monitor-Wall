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
git diff --quiet --ignore-submodules=none
git diff --cached --quiet --ignore-submodules=none
./scripts/check-executable-bits.sh
./tests/run-public-audit.sh
python3 ./scripts/verify-local-gate-receipts.py

revision="$(git rev-parse HEAD)"
short_revision="$(git rev-parse --short=12 HEAD)"
cache_root="${repository_root}/build/release-cache"
next_cache="${repository_root}/build/release-cache-next"
rm -rf -- "$next_cache"

tags=(--tag "${image}:${version}" --tag "${image}:sha-${short_revision}")
if [ "$version" = dev ]; then
    tags+=(--tag "${image}:dev")
    build_version="2.2.0-dev.${short_revision}"
    build_milestone="v2-M6-dev"
else
    tags+=(--tag "${image}:latest")
    build_version="${version#v}"
    if [[ "$version" =~ ^v2\.2(\.|$) ]]; then
        build_milestone="v2-M6"
    elif [[ "$version" =~ ^v2\.1(\.|$) ]]; then
        build_milestone="v2-M5"
    else
        build_milestone="v2-M3"
    fi
fi

docker buildx build --platform linux/amd64 --file docker/Dockerfile \
  --build-arg "WEBOBS_BUILD_VERSION=${build_version}" \
  --build-arg "WEBOBS_BUILD_MILESTONE=${build_milestone}" \
  --label "org.opencontainers.image.revision=${revision}" \
  --label "org.opencontainers.image.version=${version}" \
  --cache-from "type=local,src=${cache_root}" \
  --cache-to "type=local,dest=${next_cache},mode=max" \
  --provenance=mode=max --sbom=true "${tags[@]}" --push .

rm -rf -- "$cache_root"
mv -- "$next_cache" "$cache_root"
docker buildx imagetools inspect "${image}:sha-${short_revision}" >/dev/null
echo "published ${image}:${version} and ${image}:sha-${short_revision}"
