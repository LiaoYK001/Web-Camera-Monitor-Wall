#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
temporary=$(mktemp -d)
cleanup() {
  case "$temporary" in /tmp/*) rm -rf -- "$temporary";; esac
}
trap cleanup EXIT INT TERM

mkdir -p "$temporary/bin" "$temporary/server"
cat > "$temporary/bin/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  api)
    if [[ "${FAKE_MODE:?}" == draft-* ]]; then
      case "$2" in
        repos/example/project/releases/42)
          case "$4" in
            .upload_url) echo 'https://uploads.github.com/repos/example/project/releases/42/assets{?name,label}' ;;
            *.id) echo 77 ;;
            *) case "$FAKE_MODE" in draft-absent) echo 0;; draft-same|draft-different) echo 1;; esac ;;
          esac
          ;;
        --method)
          [[ "$3" == POST && "$4" == 'https://uploads.github.com/repos/example/project/releases/42/assets?name=artifact.bin' ]]
          while [[ "$1" != --input ]]; do shift; done
          printf 'draft-upload:%s\n' "${2##*/}" >> "$FAKE_CALLS"
          cp -- "$2" "$FAKE_SERVER/${2##*/}"
          ;;
        repos/example/project/releases/assets/77)
          [[ "$3" == -H && "$4" == 'Accept: application/octet-stream' ]]
          cat "$FAKE_SERVER/artifact.bin"
          ;;
        *) exit 44 ;; # Draft lookup by tag must never be needed.
      esac
      exit
    fi
    case "${FAKE_MODE:?}" in absent) echo 0;; same|different) echo 1;; esac
    ;;
  release)
    case "$2" in
      upload)
        asset=$4
        printf 'upload:%s\n' "${asset##*/}" >> "$FAKE_CALLS"
        cp -- "$asset" "$FAKE_SERVER/${asset##*/}"
        ;;
      download)
        name=$5
        directory=$7
        cp -- "$FAKE_SERVER/$name" "$directory/$name"
        ;;
      *) exit 90;;
    esac
    ;;
  *) exit 91;;
esac
EOF
chmod 0755 "$temporary/bin/gh"

export PATH="$temporary/bin:$PATH"
export GH_TOKEN=fixture-token
export GITHUB_REPOSITORY=example/project
export FAKE_SERVER="$temporary/server"
export FAKE_CALLS="$temporary/calls"
asset="$temporary/artifact.bin"
printf 'reviewed-content' > "$asset"

FAKE_MODE=absent "$root/scripts/upload-release-assets-immutable.sh" v2.0 "$asset"
cmp --silent "$asset" "$temporary/server/artifact.bin"
grep -Fx 'upload:artifact.bin' "$FAKE_CALLS" >/dev/null

: > "$FAKE_CALLS"
FAKE_MODE=same "$root/scripts/upload-release-assets-immutable.sh" v2.0 "$asset"
[[ ! -s "$FAKE_CALLS" ]]

printf 'different-content' > "$temporary/server/artifact.bin"
if FAKE_MODE=different "$root/scripts/upload-release-assets-immutable.sh" v2.0 "$asset"; then
  echo 'different immutable release content was accepted' >&2
  exit 1
fi
grep -Fx 'different-content' "$temporary/server/artifact.bin" >/dev/null

# A Draft is addressable only by its numeric Release ID in this fixture.
: > "$FAKE_CALLS"
FAKE_MODE=draft-absent "$root/scripts/upload-release-assets-immutable.sh" 42 "$asset"
cmp --silent "$asset" "$temporary/server/artifact.bin"
grep -Fx 'draft-upload:artifact.bin' "$FAKE_CALLS" >/dev/null
: > "$FAKE_CALLS"
FAKE_MODE=draft-same "$root/scripts/upload-release-assets-immutable.sh" 42 "$asset"
[[ ! -s "$FAKE_CALLS" ]]
printf 'different-draft-content' > "$temporary/server/artifact.bin"
if FAKE_MODE=draft-different "$root/scripts/upload-release-assets-immutable.sh" 42 "$asset"; then
  echo 'different immutable Draft content was accepted' >&2
  exit 1
fi
grep -Fx 'different-draft-content' "$temporary/server/artifact.bin" >/dev/null

ln -s "$asset" "$temporary/link.bin"
if FAKE_MODE=absent "$root/scripts/upload-release-assets-immutable.sh" v2.0 "$temporary/link.bin"; then
  echo 'symlink release asset was accepted' >&2
  exit 1
fi

echo 'immutable release upload contract passed'
