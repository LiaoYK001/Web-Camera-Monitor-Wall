#!/usr/bin/env bash
set -euo pipefail

image="${1:-}"
version="${2:-}"
release_mode="${3:-}"
[[ "$image" =~ ^ghcr\.io/[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}$ ]] || {
  echo "usage: $0 ghcr.io/owner/repository <vX.Y|vX.Y.Z|dev> [--prerelease]" >&2
  exit 64
}
[[ "$version" == dev || "$version" =~ ^v[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || {
  echo "version must be dev, vX.Y, or vX.Y.Z" >&2
  exit 64
}
[[ -z "$release_mode" || "$release_mode" == --prerelease ]] || {
  echo "the optional release mode must be --prerelease" >&2
  exit 64
}
prerelease=false
prepare_only="${WEBOBS_RELEASE_PREPARE_ONLY:-false}"
[[ "$prepare_only" == true || "$prepare_only" == false ]] || {
    echo "WEBOBS_RELEASE_PREPARE_ONLY must be true or false" >&2; exit 64;
}
[ "$version" != dev ] || [ "$prepare_only" = false ] || {
    echo "prepare-only requires a versioned release" >&2; exit 64;
}
if [[ "$release_mode" == --prerelease || "${WEBOBS_PRERELEASE:-false}" == true ]]; then
    prerelease=true
fi
if [ "$prerelease" = true ]; then
    [[ "$version" == v3.0 || "$version" == v3.0.1 ]] || {
        echo "--prerelease is restricted to v3.0 and v3.0.1; v3.1 and later are stable releases" >&2
        exit 64
    }
fi

repository_root="$(git rev-parse --show-toplevel)"
cd "$repository_root"
git diff --quiet --ignore-submodules=none
git diff --cached --quiet --ignore-submodules=none
./scripts/check-executable-bits.sh
./tests/run-public-audit.sh
# Release flow v3.3: platform and container verification is a manual step owned
# by the releaser (docs/release-flow.md).  It is deliberately no longer a
# machine-checked receipt gate, so nothing outside this checkout can block a
# publication.  Every remaining check below is automatic and secret-free.
cat <<'CHECKLIST'
发布前人工清单 / Manual pre-release checklist (docs/release-flow.md):
  1. dev 开发已在 Windows 和/或 Linux 上验证
     dev development verified on Windows and/or Linux
  2. Windows 装有 WSL 时，已在 WSL 中复验
     re-verified inside WSL when WSL is installed
  3. Linux 主机已原生验证
     verified natively on the Linux host
  4. 已在 Docker Desktop(WSL2) 或 Podman/Linux 完成容器基本测试
     basic container check done on Docker Desktop (WSL2) or Podman/Linux
CHECKLIST

revision="$(git rev-parse HEAD)"
short_revision="$(git rev-parse --short=12 HEAD)"
cache_root="${repository_root}/build/release-cache"
next_cache="${repository_root}/build/release-cache-next"
rm -rf -- "$next_cache"

tags=(--tag "${image}:sha-${short_revision}")
if [ "$version" = dev ]; then
    tags+=(--tag "${image}:dev")
    build_milestone="${WEBOBS_TARGET_MILESTONE:-v4-M1-dev}"
    source ./scripts/release-identity.sh
    webobs_dev_identity "$build_milestone" || exit 64
    build_version="${WEBOBS_DEV_VERSION:-${default_dev_version}}.${short_revision}"
elif [ "$prerelease" = true ]; then
    [ "$(git branch --show-current)" = dev ] || {
        echo "${version} preview publication must run from dev" >&2
        exit 65
    }
    remote_dev_revision="$(git ls-remote origin refs/heads/dev | awk '$2=="refs/heads/dev" {print $1}')"
    [ "$remote_dev_revision" = "$revision" ] || {
        echo "${version} preview requires HEAD to equal origin/dev" >&2
        exit 65
    }
    : "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required for a preview release}"
    : "${GH_TOKEN:?GH_TOKEN is required for a preview release}"
    command -v gh >/dev/null
    remote_refs="$(git ls-remote --tags origin "refs/tags/${version}" "refs/tags/${version}^{}")"
    [ -z "$remote_refs" ] || {
        echo "the immutable preview tag already exists; use a new preview version" >&2
        exit 65
    }
    if [ "$version" = v3.0.1 ]; then
        default_prerelease_version="3.0.1-pre.1"
    else
        default_prerelease_version="3.0.0-pre.1"
    fi
    build_version="${WEBOBS_PRERELEASE_BUILD_VERSION:-$default_prerelease_version}"
    # Keep the public milestone contract valid; the pre-release SemVer below
    # distinguishes this candidate from the eventual v3.1 stable release.
    build_milestone="v3-M2"
    draft_tag="release-draft-${version#v}-${short_revision}"
else
    [ "$(git branch --show-current)" = main ] || { echo "stable publication must run from main" >&2; exit 65; }
    remote_refs="$(git ls-remote --tags origin "refs/tags/${version}" "refs/tags/${version}^{}")"
    remote_revision="$(printf '%s\n' "$remote_refs" | awk -v tag="refs/tags/${version}^{}" '$2==tag {print $1}')"
    [ -n "$remote_revision" ] || remote_revision="$(printf '%s\n' "$remote_refs" | awk -v tag="refs/tags/${version}" '$2==tag {print $1}')"
    if [ -n "$remote_revision" ] && [ "$remote_revision" != "$revision" ]; then
        echo "an existing release tag must resolve to HEAD; refusing to overwrite it" >&2
        exit 65
    fi
    : "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required for a stable release}"
    : "${GH_TOKEN:?GH_TOKEN is required for a stable release}"
    command -v gh >/dev/null
    source ./scripts/release-identity.sh
    webobs_release_identity "$version"
    # GitHub may create the tag named in a Draft immediately. Use a
    # deterministic, non-release tag until the source assets are verified;
    # an existing stable tag is reused only when it already points at HEAD.
    draft_tag=""
    if [ -z "$remote_revision" ]; then
        draft_tag="release-draft-${version#v}-${short_revision}"
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

# `git rev-parse --show-toplevel` returns a drive-letter path under Git Bash
# on Windows (for example `D:/repo`), while the source-bundle helper requires
# a POSIX absolute path.  Resolve the already-selected repository through the
# shell so both Git Bash and native Linux pass the same contract.
release_root="$(pwd -P)/build/release-assets/${version}"
mkdir -p "$release_root"
./scripts/create-source-bundle.sh "$version" "$release_root"
source_archive="${release_root}/webobs-source-${version}.tar.gz"
./scripts/verify-source-bundle.sh "$source_archive"
notes="${release_root}/RELEASE-NOTES.md"
cat > "$notes" <<EOF
# Web Camera Monitor Wall ${version}

- 源码提交 / Source revision: \`${revision}\`
- OCI 候选镜像 / OCI candidate: \`${image}:sha-${short_revision}\`
- OCI digest: \`${digest}\`
- 里程碑 / Milestone: \`${build_milestone}\`

EOF
release_scope_notes="docs/release-notes-${version}.md"
if [ -f "$release_scope_notes" ]; then
    cat "$release_scope_notes" >> "$notes"
fi
if [ "$prerelease" = true ]; then
    cat >> "$notes" <<EOF
这是 v3-M1/v3-M2 分析功能的预览版，并非 v3.1 稳定版。 / This is a preview release for the v3-M1/v3-M2 analytics line, not the v3.1 stable release.
只有预发布草稿及源码附件发布后，才会从该候选 digest 提升 ${version} 标签。 / The ${version} tag is promoted from this candidate digest only after the pre-release draft and source assets are published.
latest 保持不变；此预览版不代表生产稳定性验收。 / The latest tag is unchanged; this preview does not claim production stability.
EOF
else
    cat >> "$notes" <<EOF
版本标签与 latest 只有在草稿及对应源码附件发布后才会提升到此候选 digest。 / The version and latest tags are promoted to this candidate digest only after the draft and corresponding source assets are published.
EOF
fi

release_lookup_tag="${draft_tag:-$version}"
release_id="$(gh api "repos/$GITHUB_REPOSITORY/releases?per_page=100" --jq ".[] | select(.tag_name == \"$release_lookup_tag\") | .id" | head -n 1)"
if [ -z "$release_id" ] && [ "$prerelease" = true ]; then
    # A prior retry may have advanced HEAD and therefore changed draft_tag.
    # Reuse the newest matching preview Draft instead of creating clutter.
    release_id="$(gh api "repos/$GITHUB_REPOSITORY/releases?per_page=100" \
        --jq "[.[] | select(.draft == true and .prerelease == true and .name == \"$version\")] | sort_by(.created_at) | last | .id // empty")"
fi
if [ -z "$release_id" ]; then
    release_id="$(gh api --method POST "repos/$GITHUB_REPOSITORY/releases" \
        -f "tag_name=$release_lookup_tag" -f "target_commitish=$revision" -f "name=$version" -f "body=$(<"$notes")" \
        -F draft=true -F "prerelease=$prerelease" --jq .id)"
else
    # A retry may reuse the existing Draft.  Refresh its revision and notes so
    # every asset remains tied to the candidate being published now.
    gh api --method PATCH "repos/$GITHUB_REPOSITORY/releases/$release_id" \
        -f "target_commitish=$revision" -f "name=$version" -f "body=$(<"$notes")" \
        -F draft=true -F "prerelease=$prerelease" >/dev/null
fi
[[ "$release_id" =~ ^[0-9]+$ ]] || { echo "could not resolve a GitHub Release database id" >&2; exit 65; }
is_draft="$(gh api "repos/$GITHUB_REPOSITORY/releases/$release_id" --jq .draft)"
[ "$is_draft" = true ] || { echo "refusing to mutate an already-published release" >&2; exit 65; }
./scripts/upload-release-assets-immutable.sh "$release_id" "$source_archive" "${source_archive}.sha256"
if [ "$prepare_only" = true ]; then
    echo "prepared Draft release $release_id ($release_lookup_tag), candidate ${image}:sha-${short_revision} at ${digest}"
    echo "Release remains unpublished; version/latest and the stable Git tag are unchanged. Resume from this same revision without prepare-only after all attachments are verified."
    exit 0
fi
if [ -n "$draft_tag" ]; then
    # Create the immutable annotated release tag only after the Draft assets
    # have been uploaded and re-verified. Never move or delete a stable tag.
    if git show-ref --verify --quiet "refs/tags/$version"; then
        [ "$(git rev-parse "${version}^{commit}")" = "$revision" ] || {
            echo "local release tag already points at a different revision" >&2; exit 65;
        }
    else
        git tag -a "$version" "$revision" -m "Web Camera Monitor Wall $version"
    fi
    git push origin "refs/tags/$version"
    remote_release_revision="$(git ls-remote --tags origin "refs/tags/${version}^{}" | awk -v tag="refs/tags/${version}^{}" '$2==tag {print $1}')"
    [ "$remote_release_revision" = "$revision" ] || {
        echo "annotated release tag did not resolve to HEAD after push" >&2; exit 65;
    }
    gh api --method PATCH "repos/$GITHUB_REPOSITORY/releases/$release_id" \
        -f "tag_name=$version" -f "target_commitish=$revision" >/dev/null
    [ "$(gh api "repos/$GITHUB_REPOSITORY/releases/$release_id" --jq .tag_name)" = "$version" ] || {
        echo "Draft release tag could not be switched to the stable tag" >&2; exit 65;
    }
    git push origin ":refs/tags/$draft_tag" >/dev/null 2>&1 || true
fi
if [ "$prerelease" = true ]; then
    gh api --method PATCH "repos/$GITHUB_REPOSITORY/releases/$release_id" \
        -F draft=false -F prerelease=true >/dev/null
    docker buildx imagetools create \
        --tag "${image}:${version}" "${image}@${digest}"
    promoted_digest="$(docker buildx imagetools inspect "${image}:${version}" | \
        awk '$1=="Digest:" && $2 ~ /^sha256:[0-9a-f]{64}$/ {print $2; exit}')"
    [ "$promoted_digest" = "$digest" ] || {
        echo "promoted ${version} tag does not match the candidate digest" >&2; exit 65;
    }
    echo "published preview ${version} and sha-${short_revision} from ${digest}; latest was not changed"
else
    gh api --method PATCH "repos/$GITHUB_REPOSITORY/releases/$release_id" -F draft=false >/dev/null

    docker buildx imagetools create \
        --tag "${image}:${version}" --tag "${image}:latest" "${image}@${digest}"
    for promoted in "$version" latest; do
        promoted_digest="$(docker buildx imagetools inspect "${image}:${promoted}" | \
            awk '$1=="Digest:" && $2 ~ /^sha256:[0-9a-f]{64}$/ {print $2; exit}')"
        [ "$promoted_digest" = "$digest" ] || {
            echo "promoted ${promoted} tag does not match the candidate digest" >&2; exit 65;
        }
    done
    gh api --method PATCH "repos/$GITHUB_REPOSITORY/releases/$release_id" -F make_latest=true >/dev/null
    echo "published ${version}, latest, and sha-${short_revision} from ${digest}"
fi
