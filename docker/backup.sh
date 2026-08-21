#!/bin/sh
set -eu
umask 077

config_root="${WEBOBS_BACKUP_CONFIG_ROOT:-/config/webobs}"
backup_root="${WEBOBS_BACKUP_ROOT:-/backups}"
scene_path="$config_root/scene.json"
studio_path="$config_root/studio.json"
nvr_path="$config_root/nvr.json"

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
        BEGIN { scene = 0; studio = 0; nvr = 0 }
        $0 == "webobs/" { next }
        $0 == "webobs/scene.json" { scene++; next }
        $0 == "webobs/studio.json" { studio++; next }
        $0 == "webobs/nvr.json" { nvr++; next }
        { exit 1 }
        END { if (scene != 1 || studio > 1 || nvr > 1) exit 1 }
    ' "$listing" || fail "archive contains unexpected paths"
    safe_remove_temp "$listing"
    trap - EXIT HUP INT TERM
}

create_backup() {
    [ -f "$scene_path" ] && [ ! -L "$scene_path" ] || fail "scene.json is missing or unsafe"
    /opt/obs/bin/webobs-scene-tool validate "$scene_path" >/dev/null || fail "scene validation failed"
    include_studio=0
    include_nvr=0
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
    staged="$temporary/scene.json.staged"
    install -m 0600 "$extracted" "$staged"
    if [ -f "$temporary/studio.json.staged" ]; then
        mv -f "$temporary/studio.json.staged" "$studio_path"
    fi
    if [ -f "$temporary/nvr.json.staged" ]; then
        mv -f "$temporary/nvr.json.staged" "$nvr_path"
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
