#!/usr/bin/env bash
# Pure version/engineering-gate selection, shared by local stable publication.
webobs_release_identity() {
    local tag="$1" major
    [[ "$tag" =~ ^v(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})(\.(0|[1-9][0-9]{0,8}))?$ ]] || {
        echo 'stable product tag must be vA.B or vA.B.C without leading zeros' >&2; return 64;
    }
    [[ "$tag" == "${BASH_REMATCH[0]}" ]] || { echo 'unexpected characters in release tag' >&2; return 64; }
    major="${BASH_REMATCH[1]}"
    build_version="${tag#v}"
    [[ "$build_version" =~ ^[0-9]+\.[0-9]+$ ]] && build_version="${build_version}.0"
    if ((major >= 4)); then
        build_milestone="${WEBOBS_TARGET_MILESTONE:-}"
        [[ "$build_milestone" =~ ^v${major}-M[1-9][0-9]*$ ]] || {
            echo 'v4+ stable publication requires an explicit matching reviewed WEBOBS_TARGET_MILESTONE (no -dev suffix)' >&2; return 64;
        }
        [[ "$build_milestone" == "${BASH_REMATCH[0]}" ]] || return 64
    elif [[ "$tag" =~ ^v3\.[1-9][0-9]*(\.|$) ]]; then build_milestone="v3-M2"
    elif [[ "$tag" =~ ^v3\.0(\.|$) ]]; then build_milestone="v3-M1"
    elif [[ "$tag" =~ ^v2\.3(\.|$) ]]; then build_milestone="v2-M7"
    elif [[ "$tag" =~ ^v2\.2(\.|$) ]]; then build_milestone="v2-M6"
    elif [[ "$tag" =~ ^v2\.1(\.|$) ]]; then build_milestone="v2-M5"
    else build_milestone="v2-M3"
    fi
}
