#!/bin/sh
set -eu
umask 077

config_root="${WEBOBS_BACKUP_CONFIG_ROOT:-/config/webobs}"
backup_root="${WEBOBS_BACKUP_ROOT:-/backups}"
scene_path="$config_root/scene.json"
studio_path="$config_root/studio.json"
nvr_path="$config_root/nvr.json"
camera_db_path="$config_root/cameras.db"
v2_db_path="$config_root/v2-clients.db"
shared_scenes_path="$config_root/shared-scenes-v2.json"
grant_key_path="$config_root/keys/client-grant-signing.key"

fail() {
    echo "webobs-backup: $*" >&2
    exit 2
}

validate_roots() {
    case "$config_root" in
        /*/webobs) ;;
        *) fail "config root must be an absolute path ending in /webobs" ;;
    esac
    case "$backup_root" in
        /*/backups|/backups) ;;
        *) fail "backup root must be an absolute path ending in /backups" ;;
    esac
    [ -d "$config_root" ] || fail "config root is unavailable"
    [ ! -L "$config_root" ] || fail "config root must not be a symbolic link"
    mkdir -p "$backup_root"
    [ -d "$backup_root" ] && [ ! -L "$backup_root" ] || fail "backup root is unsafe"
}

safe_archive_path() {
    value="$1"
    case "$value" in
        "$backup_root"/*.tar.gz) ;;
        *) fail "archive must be a .tar.gz file directly under the backup root" ;;
    esac
    base="${value##*/}"
    case "$base" in
        .*|*[!A-Za-z0-9._-]*|*.tar.gz.tar.gz) fail "archive name contains unsafe characters" ;;
    esac
}

safe_remove_temp() {
    value="$1"
    case "$value" in
        "$backup_root"/.webobs-backup.*|"$config_root"/.webobs-restore.*) rm -rf -- "$value" ;;
        *) fail "refusing to remove an unexpected temporary path" ;;
    esac
}

validate_sqlite() {
    database_path="$1"
    python3 - "$database_path" <<'PY'
import sqlite3
import sys

path = sys.argv[1]
connection = sqlite3.connect(path, timeout=3)
try:
    busy, _log, _checkpointed = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if busy:
        raise SystemExit("database has an active writer")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("database integrity check failed")
finally:
    connection.close()
PY
}

validate_shared_scenes() {
    document_path="$1"
    python3 - "$document_path" <<'PY'
import json
import math
import sys

def reject_constant(_value):
    raise ValueError("non-finite number")

with open(sys.argv[1], "r", encoding="utf-8") as source:
    value = json.load(source, parse_constant=reject_constant)
if not isinstance(value, dict) or set(value) != {"schemaVersion", "scenes"} or value["schemaVersion"] != 1:
    raise SystemExit("shared Scene wrapper is invalid")
if not isinstance(value["scenes"], list) or len(value["scenes"]) > 64:
    raise SystemExit("shared Scene count is invalid")
PY
}

verify_archive() {
    archive="$1"
    safe_archive_path "$archive"
    [ -f "$archive" ] && [ ! -L "$archive" ] || fail "archive is missing or unsafe"
    checksum="$archive.sha256"
    [ -f "$checksum" ] && [ ! -L "$checksum" ] || fail "checksum sidecar is missing or unsafe"
    archive_base="${archive##*/}"
    checksum_base="${checksum##*/}"
    awk -v name="$archive_base" '
        NF == 2 && $1 ~ /^[0-9a-f]{64}$/ && $2 == name { valid++ }
        END { if (valid != 1 || NR != 1) exit 1 }
    ' "$checksum" || fail "checksum sidecar has an unsafe format"
    (cd "$backup_root" && sha256sum -c "$checksum_base" >/dev/null) || fail "archive checksum verification failed"

    listing="$(mktemp "$backup_root/.webobs-backup.XXXXXX")"
    trap 'safe_remove_temp "$listing"' EXIT HUP INT TERM
    tar -tzf "$archive" > "$listing" || fail "archive cannot be listed"
    awk '
        BEGIN { scene = 0; studio = 0; nvr = 0; cameras = 0; v2 = 0; shared = 0; key = 0 }
        $0 == "webobs/" { next }
        $0 == "webobs/keys/" { next }
        $0 == "webobs/scene.json" { scene++; next }
        $0 == "webobs/studio.json" { studio++; next }
        $0 == "webobs/nvr.json" { nvr++; next }
        $0 == "webobs/cameras.db" { cameras++; next }
        $0 == "webobs/v2-clients.db" { v2++; next }
        $0 == "webobs/shared-scenes-v2.json" { shared++; next }
        $0 == "webobs/keys/client-grant-signing.key" { key++; next }
        { exit 1 }
        END { if (scene != 1 || studio > 1 || nvr > 1 || cameras > 1 || v2 > 1 || shared > 1 || key > 1 || v2 != key) exit 1 }
    ' "$listing" || fail "archive contains unexpected paths"
    safe_remove_temp "$listing"
    trap - EXIT HUP INT TERM
}

create_backup() {
    [ -f "$scene_path" ] && [ ! -L "$scene_path" ] || fail "scene.json is missing or unsafe"
    /opt/obs/bin/webobs-scene-tool validate "$scene_path" >/dev/null || fail "scene validation failed"
    include_studio=0
    include_nvr=0
    include_camera_db=0
    include_v2=0
    include_shared_scenes=0
    if [ -e "$studio_path" ]; then
        [ -f "$studio_path" ] && [ ! -L "$studio_path" ] || fail "studio.json is unsafe"
        /opt/obs/bin/webobs-scene-tool validate-studio "$studio_path" >/dev/null || fail "studio validation failed"
        include_studio=1
    fi
    if [ -e "$nvr_path" ]; then
        [ -f "$nvr_path" ] && [ ! -L "$nvr_path" ] || fail "nvr.json is unsafe"
        /opt/webobs/bin/webobs-nvrd --config "$nvr_path" --validate-config >/dev/null || fail "NVR validation failed"
        include_nvr=1
    fi
    if [ -e "$camera_db_path" ]; then
        [ -f "$camera_db_path" ] && [ ! -L "$camera_db_path" ] || fail "Camera Registry database is unsafe"
        validate_sqlite "$camera_db_path" || fail "Camera Registry database validation failed"
        include_camera_db=1
    fi
    if [ -e "$v2_db_path" ] || [ -e "$grant_key_path" ]; then
        [ -f "$v2_db_path" ] && [ ! -L "$v2_db_path" ] || fail "v2 client database is missing or unsafe"
        [ -f "$grant_key_path" ] && [ ! -L "$grant_key_path" ] || fail "v2 Grant signing key is missing or unsafe"
        [ "$(wc -c < "$grant_key_path")" = "96" ] || fail "v2 Grant signing key length is invalid"
        validate_sqlite "$v2_db_path" || fail "v2 client database validation failed"
        include_v2=1
    fi
    if [ -e "$shared_scenes_path" ]; then
        [ -f "$shared_scenes_path" ] && [ ! -L "$shared_scenes_path" ] || fail "shared Scene document is unsafe"
        validate_shared_scenes "$shared_scenes_path" || fail "shared Scene document validation failed"
        include_shared_scenes=1
    fi
    timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    name="${1:-webobs-config-$timestamp.tar.gz}"
    case "$name" in
        *.tar.gz) ;;
        *) fail "backup name must end in .tar.gz" ;;
    esac
    archive="$backup_root/$name"
    safe_archive_path "$archive"
    [ ! -e "$archive" ] && [ ! -e "$archive.sha256" ] || fail "backup already exists"

    temporary="$(mktemp -d "$backup_root/.webobs-backup.XXXXXX")"
    trap 'safe_remove_temp "$temporary"' EXIT HUP INT TERM
    set -- webobs/scene.json
    [ "$include_studio" -eq 0 ] || set -- "$@" webobs/studio.json
    [ "$include_nvr" -eq 0 ] || set -- "$@" webobs/nvr.json
    [ "$include_camera_db" -eq 0 ] || set -- "$@" webobs/cameras.db
    if [ "$include_v2" -ne 0 ]; then
        set -- "$@" webobs/v2-clients.db webobs/keys/client-grant-signing.key
    fi
    [ "$include_shared_scenes" -eq 0 ] || set -- "$@" webobs/shared-scenes-v2.json
    tar -C "${config_root%/webobs}" -czf "$temporary/$name" "$@"
    hash="$(sha256sum "$temporary/$name" | awk '{print $1}')"
    printf '%s  %s\n' "$hash" "$name" > "$temporary/$name.sha256"
    chmod 0600 "$temporary/$name" "$temporary/$name.sha256"
    mv "$temporary/$name" "$archive"
    mv "$temporary/$name.sha256" "$archive.sha256"
    safe_remove_temp "$temporary"
    trap - EXIT HUP INT TERM
    echo "Backup created: $archive"
}

restore_backup() {
    archive="$1"
    [ "${WEBOBS_RESTORE_CONFIRM:-}" = "replace-scene" ] ||
        fail "restore requires WEBOBS_RESTORE_CONFIRM=replace-scene"
    verify_archive "$archive"
    temporary="$(mktemp -d "$config_root/.webobs-restore.XXXXXX")"
    trap 'safe_remove_temp "$temporary"' EXIT HUP INT TERM
    tar -xzf "$archive" -C "$temporary" --no-same-owner --no-same-permissions
    extracted="$temporary/webobs/scene.json"
    [ -f "$extracted" ] && [ ! -L "$extracted" ] || fail "restored scene is missing or unsafe"
    [ "$(stat -c '%h' "$extracted")" = "1" ] || fail "restored scene must not be a hard link"
    /opt/obs/bin/webobs-scene-tool validate "$extracted" >/dev/null || fail "restored scene validation failed"
    extracted_studio="$temporary/webobs/studio.json"
    if [ -e "$extracted_studio" ]; then
        [ -f "$extracted_studio" ] && [ ! -L "$extracted_studio" ] || fail "restored Studio collection is unsafe"
        [ "$(stat -c '%h' "$extracted_studio")" = "1" ] || fail "restored Studio collection must not be a hard link"
        /opt/obs/bin/webobs-scene-tool validate-studio "$extracted_studio" >/dev/null || fail "restored Studio validation failed"
        install -m 0600 "$extracted_studio" "$temporary/studio.json.staged"
    fi
    extracted_nvr="$temporary/webobs/nvr.json"
    if [ -e "$extracted_nvr" ]; then
        [ -f "$extracted_nvr" ] && [ ! -L "$extracted_nvr" ] || fail "restored NVR configuration is unsafe"
        [ "$(stat -c '%h' "$extracted_nvr")" = "1" ] || fail "restored NVR configuration must not be a hard link"
        /opt/webobs/bin/webobs-nvrd --config "$extracted_nvr" --validate-config >/dev/null || fail "restored NVR validation failed"
        install -m 0600 "$extracted_nvr" "$temporary/nvr.json.staged"
    fi
    extracted_camera_db="$temporary/webobs/cameras.db"
    if [ -e "$extracted_camera_db" ]; then
        [ -f "$extracted_camera_db" ] && [ ! -L "$extracted_camera_db" ] || fail "restored Camera Registry database is unsafe"
        [ "$(stat -c '%h' "$extracted_camera_db")" = "1" ] || fail "restored Camera Registry database must not be a hard link"
        validate_sqlite "$extracted_camera_db" || fail "restored Camera Registry database validation failed"
        install -m 0600 "$extracted_camera_db" "$temporary/cameras.db.staged"
    fi
    extracted_v2_db="$temporary/webobs/v2-clients.db"
    extracted_grant_key="$temporary/webobs/keys/client-grant-signing.key"
    if [ -e "$extracted_v2_db" ] || [ -e "$extracted_grant_key" ]; then
        [ -f "$extracted_v2_db" ] && [ ! -L "$extracted_v2_db" ] || fail "restored v2 client database is missing or unsafe"
        [ -f "$extracted_grant_key" ] && [ ! -L "$extracted_grant_key" ] || fail "restored Grant signing key is missing or unsafe"
        [ "$(stat -c '%h' "$extracted_v2_db")" = "1" ] && [ "$(stat -c '%h' "$extracted_grant_key")" = "1" ] || fail "restored v2 identity files must not be hard links"
        [ "$(wc -c < "$extracted_grant_key")" = "96" ] || fail "restored Grant signing key length is invalid"
        validate_sqlite "$extracted_v2_db" || fail "restored v2 client database validation failed"
        install -m 0600 "$extracted_v2_db" "$temporary/v2-clients.db.staged"
        install -m 0600 "$extracted_grant_key" "$temporary/client-grant-signing.key.staged"
    fi
    extracted_shared_scenes="$temporary/webobs/shared-scenes-v2.json"
    if [ -e "$extracted_shared_scenes" ]; then
        [ -f "$extracted_shared_scenes" ] && [ ! -L "$extracted_shared_scenes" ] || fail "restored shared Scene document is unsafe"
        [ "$(stat -c '%h' "$extracted_shared_scenes")" = "1" ] || fail "restored shared Scene document must not be a hard link"
        validate_shared_scenes "$extracted_shared_scenes" || fail "restored shared Scene document validation failed"
        install -m 0600 "$extracted_shared_scenes" "$temporary/shared-scenes-v2.json.staged"
    fi
    staged="$temporary/scene.json.staged"
    install -m 0600 "$extracted" "$staged"
    if [ -f "$temporary/studio.json.staged" ]; then
        mv -f "$temporary/studio.json.staged" "$studio_path"
    fi
    if [ -f "$temporary/nvr.json.staged" ]; then
        mv -f "$temporary/nvr.json.staged" "$nvr_path"
    fi
    if [ -f "$temporary/cameras.db.staged" ]; then
        rm -f -- "$camera_db_path-wal" "$camera_db_path-shm"
        mv -f "$temporary/cameras.db.staged" "$camera_db_path"
    fi
    if [ -f "$temporary/v2-clients.db.staged" ]; then
        mkdir -p "$config_root/keys"
        chmod 0700 "$config_root/keys"
        rm -f -- "$v2_db_path-wal" "$v2_db_path-shm"
        mv -f "$temporary/v2-clients.db.staged" "$v2_db_path"
        mv -f "$temporary/client-grant-signing.key.staged" "$grant_key_path"
    fi
    if [ -f "$temporary/shared-scenes-v2.json.staged" ]; then
        mv -f "$temporary/shared-scenes-v2.json.staged" "$shared_scenes_path"
    fi
    mv -f "$staged" "$scene_path"
    safe_remove_temp "$temporary"
    trap - EXIT HUP INT TERM
    echo "Configuration restored and validated"
}

validate_roots
action="${1:-}"
case "$action" in
    create)
        create_backup "${2:-}"
        ;;
    verify)
        [ "$#" -eq 2 ] || fail "verify requires one archive path"
        verify_archive "$2"
        echo "Backup verified"
        ;;
    restore)
        [ "$#" -eq 2 ] || fail "restore requires one archive path"
        restore_backup "$2"
        ;;
    *)
        fail "usage: webobs-backup create [name.tar.gz] | verify /backups/name.tar.gz | restore /backups/name.tar.gz"
        ;;
esac
