#!/bin/sh
set -eu

script_directory="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repository_root="$(CDPATH= cd -- "$script_directory/.." && pwd)"
expected_obs_commit="fb4d98bf88fae5fc85cb11fc57f7c5e309282194"
expected_obs_url="https://github.com/obsproject/obs-studio.git"

command -v git >/dev/null 2>&1
cd "$repository_root"

git_root="$(git rev-parse --show-toplevel)"
if [ "$(CDPATH= cd -- "$git_root" && pwd)" != "$repository_root" ]; then
    echo "The public-repository audit must run from this repository." >&2
    exit 1
fi

path_violations="$(
    git -c core.quotepath=false ls-files | while IFS= read -r path; do
        leaf="${path##*/}"
        lower_path="$(printf '%s' "$path" | tr '[:upper:]' '[:lower:]')"
        case "$leaf" in
            .env*) [ "$path" = ".env.example" ] || printf '%s\n' "$path" ;;
        esac
        case "$lower_path" in
            secrets/*|*/secrets/*|backups/*) printf '%s\n' "$path" ;;
            build/*|build-*/*|web/node_modules/*|web/dist/*) printf '%s\n' "$path" ;;
            recordings/*) [ "$path" = "recordings/.gitkeep" ] || printf '%s\n' "$path" ;;
            tests/artifacts/*) [ "$path" = "tests/artifacts/.gitkeep" ] || printf '%s\n' "$path" ;;
            *.key|*.pem|*.p12|*.pfx|*.mp4|*.mkv|*.mov|*.avi|*.m4v|*.log) printf '%s\n' "$path" ;;
        esac
    done
)"
if [ -n "$path_violations" ]; then
    echo "Public-repository audit failed: sensitive or generated paths are tracked:" >&2
    printf '%s\n' "$path_violations" >&2
    exit 1
fi

assert_index_line() {
    path="$1"
    required_line="$2"
    if ! git show ":$path" | grep -F -x "$required_line" >/dev/null; then
        echo "Public-repository audit failed: '$path' is missing required protection '$required_line'." >&2
        exit 1
    fi
}

for required_line in \
    '/.env*' \
    '!/.env.example' \
    '/secrets/' \
    '/backups/' \
    '*.key' \
    '*.pem' \
    '*.p12' \
    '*.pfx' \
    '/build/' \
    '/build-*/' \
    '/web/node_modules/' \
    '/web/dist/' \
    '/recordings/*' \
    '!/recordings/.gitkeep' \
    '/tests/artifacts/*' \
    '!/tests/artifacts/.gitkeep'
do
    assert_index_line '.gitignore' "$required_line"
done

for required_line in \
    '.git' \
    '**/.env*' \
    '!.env.example' \
    '**/secrets/**' \
    'backups' \
    '**/*.key' \
    '**/*.pem' \
    '**/*.p12' \
    '**/*.pfx' \
    'build' \
    'build-*' \
    'web/node_modules' \
    'web/dist' \
    'recordings/*' \
    '!recordings/.gitkeep' \
    'tests/artifacts/*' \
    '!tests/artifacts/.gitkeep'
do
    assert_index_line '.dockerignore' "$required_line"
done

secret_pattern='-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-(proj-)?[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}'
set +e
secret_files="$(git grep --cached -I -l -E -- "$secret_pattern" -- . 2>/dev/null)"
secret_status=$?
set -e
case "$secret_status" in
    0)
        echo "Public-repository audit failed: high-confidence credential or private-key material exists in the Git index:" >&2
        printf '%s\n' "$secret_files" >&2
        exit 1
        ;;
    1) ;;
    *) echo "Public-repository audit failed while scanning indexed content." >&2; exit 1 ;;
esac

allowed_rtsp_references=' .env.example|user:password
docker/Dockerfile|user:password
docker/Dockerfile|***:***
README.md|user:password
README.md|***:***
core/tests/common_tests.cpp|user:password
core/tests/common_tests.cpp|***:***
core/tests/common_tests.cpp|user
core/tests/common_tests.cpp|***
core/tests/common_tests.cpp|name:p%40ss
core/tests/common_tests.cpp|u:p
core/tests/common_tests.cpp|x:y
tests/run-contracts.ps1|test-user:supersecret
tests/run-contracts.ps1|***:***
tests/run-contracts.sh|test-user:supersecret
tests/run-contracts.sh|***:***
tests/run-real-camera.ps1|user:password
tests/run-real-camera.sh|user:password'
allowed_rtsp_references="${allowed_rtsp_references# }"
rtsp_pattern='rtsps?://[^[:space:]/@]+(:[^[:space:]/@]*)?@'
set +e
rtsp_records="$(git grep --cached -I -n -o -E -- "$rtsp_pattern" -- . 2>/dev/null)"
rtsp_status=$?
set -e
case "$rtsp_status" in
    0)
        rtsp_violations="$(
            printf '%s\n' "$rtsp_records" | while IFS= read -r record; do
                path="${record%%:*}"
                remainder="${record#*:}"
                line_number="${remainder%%:*}"
                url="${remainder#*:}"
                userinfo="${url#*://}"
                userinfo="${userinfo%@}"
                if ! printf '%s\n' "$allowed_rtsp_references" | grep -F -x "$path|$userinfo" >/dev/null; then
                    printf '%s:%s\n' "$path" "$line_number"
                fi
            done
        )"
        if [ -n "$rtsp_violations" ]; then
            echo "Public-repository audit failed: non-placeholder RTSP credentials exist in the Git index at:" >&2
            printf '%s\n' "$rtsp_violations" >&2
            exit 1
        fi
        ;;
    1) ;;
    *) echo "Public-repository audit failed while scanning RTSP references." >&2; exit 1 ;;
esac

submodule_entries="$(git ls-files --stage | awk '$1 == "160000" { print $1 " " $2 " " $3 " " $4 }')"
expected_submodule_entry="160000 $expected_obs_commit 0 obs/obs-studio"
if [ "$submodule_entries" != "$expected_submodule_entry" ]; then
    echo "Public-repository audit failed: OBS must be the only root submodule and remain pinned to the approved commit." >&2
    exit 1
fi
for executable_path in \
    tests/run-contracts.sh \
    tests/run-public-audit.sh \
    tests/run-m1-real-camera.sh \
    tests/run-m10-real-mjpeg.sh \
    tests/run-real-camera.sh \
    tests/run-smoke.sh
do
    executable_mode="$(git ls-files --stage -- "$executable_path" | awk '{ print $1 }')"
    if [ "$executable_mode" != "100755" ]; then
        echo "Public-repository audit failed: '$executable_path' must remain executable in the Git index." >&2
        exit 1
    fi
done
if ! git show ':.gitmodules' | sed 's/^[[:space:]]*//' | grep -F -x 'path = obs/obs-studio' >/dev/null ||
    ! git show ':.gitmodules' | sed 's/^[[:space:]]*//' | grep -F -x "url = $expected_obs_url" >/dev/null
then
    echo "Public-repository audit failed: the OBS submodule path or public upstream URL changed." >&2
    exit 1
fi

checkout_status="$(git submodule status --recursive)"
if [ -z "$checkout_status" ] || printf '%s\n' "$checkout_status" | grep -E '^[+U-]' >/dev/null; then
    echo "Public-repository audit failed: recursively initialize submodules and restore their pinned commits." >&2
    exit 1
fi

tracked_count="$(git ls-files | wc -l | tr -d '[:space:]')"
echo "Public repository audit passed: $tracked_count indexed paths, approved RTSP placeholders only, OBS pin $expected_obs_commit."
