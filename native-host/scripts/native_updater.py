#!/usr/bin/env python3
"""Native Windows update check/download/install with pinned GitHub HTTPS feeds.

The product keeps its own installer and never uses install-on-quit. A user must
close WebOBS Wall, run this tool, and confirm installation. Size and SHA-512 are
validated before an installer is launched; a failed preparation never starts it.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

MAX_FEED = 1024 * 1024
MAX_INSTALLER = 4 * 1024 * 1024 * 1024
VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
                     r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
                     r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$")
ALLOWED_HOSTS = ("github.com", "www.github.com", "objects.githubusercontent.com",
                 "release-assets.githubusercontent.com")
RELEASE_PREFIX = "/LiaoYK001/Web-Camera-Monitor-Wall/releases/download/"
LATEST_PREFIX = "/LiaoYK001/Web-Camera-Monitor-Wall/releases/latest/download/"
MAINTENANCE_KIND = "webobs-private-maintenance-runtime"


class UpdateError(Exception):
    """Bounded public diagnostic; never includes URLs, paths or credentials."""


def cleanup_maintenance(data_root: Path) -> None:
    root = data_root / "run/maintenance"
    if not root.is_dir() or root.is_symlink():
        return
    for directory in root.iterdir():
        marker = directory / ".maintenance.json"
        if (not re.fullmatch(r"tool-[a-z0-9_]{8}", directory.name) or directory.is_symlink() or
                not marker.is_file() or marker.is_symlink() or marker.stat().st_size > 4096):
            continue
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("kind") != MAINTENANCE_KIND or value.get("state") != "completed":
                continue
            if any(p.is_symlink() or getattr(p.lstat(), "st_file_attributes", 0) & 0x400
                   for p in (directory, *directory.rglob("*"))):
                continue
            shutil.rmtree(directory)
        except (OSError, ValueError):
            # A still-exiting maintenance interpreter may hold its executable.
            # A later product start can retry; never terminate another process.
            continue


def prepare_maintenance(runtime: Path, data_root: Path, output: Path) -> dict:
    """Copy a small maintenance interpreter outside the tree NSIS will replace."""
    runtime = runtime.resolve(strict=True)
    root = data_root / "run/maintenance"
    for path in (data_root.absolute(), root.absolute()):
        if any(p.is_symlink() or (p.exists() and getattr(p.lstat(), "st_file_attributes", 0) & 0x400)
               for p in (path, *path.parents)):
            raise UpdateError("maintenance directory must not contain links")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    cleanup_maintenance(data_root)
    capsule = Path(tempfile.mkdtemp(prefix="tool-", dir=root))
    try:
        sources = [(p, Path("python") / p.name) for p in (runtime / "python").iterdir() if p.is_file()]
        sources += [(runtime / name, Path(name)) for name in (
            "services/product/native_updater.py", "services/backup/encrypted_backup.py",
            "services/runtime_support.py", "bin/libsodium.dll", "CHECK-UPDATES.cmd")]
        total = 0
        for source, relative in sources:
            if source.is_symlink() or not source.is_file():
                raise UpdateError("maintenance component is unavailable or linked")
            total += source.stat().st_size
            if total > 128 * 1024 * 1024:
                raise UpdateError("maintenance interpreter exceeds its bound")
            target = capsule / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        if not (capsule / "python/python.exe").is_file():
            raise UpdateError("maintenance interpreter is missing")
        (capsule / ".webobs-maintenance-origin").write_text(str(runtime), encoding="utf-8")
        (capsule / ".maintenance.json").write_text(json.dumps({
            "kind": MAINTENANCE_KIND, "state": "ready", "copiedBytes": total}), encoding="utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as path_file:
            path_file.write(str(capsule))
        return {"schema": 1, "status": "prepared", "copiedBytes": total,
                "outsideInstalledRuntime": True}
    except Exception:
        shutil.rmtree(capsule, ignore_errors=True)
        raise


def finish_maintenance():
    marker = Path(sys.executable).resolve().parent.parent / ".maintenance.json"
    if marker.is_file() and not marker.is_symlink() and marker.stat().st_size <= 4096:
        value = json.loads(marker.read_text(encoding="utf-8"))
        if isinstance(value, dict) and value.get("kind") == MAINTENANCE_KIND:
            value["state"] = "completed"
            marker.write_text(json.dumps(value), encoding="utf-8")


def version_key(value: str):
    if not isinstance(value, str) or len(value) > 128:
        raise UpdateError("invalid update version")
    match = VERSION.fullmatch(value)
    if not match:
        raise UpdateError("invalid update version")
    numbers = tuple(int(part) for part in match.groups()[:3])
    suffix = match.group(4)
    if suffix and any(part.isdigit() and len(part) > 1 and part.startswith("0")
                      for part in suffix.split(".")):
        raise UpdateError("invalid numeric prerelease identifier")
    return numbers, suffix


def runtime_version(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
        raise UpdateError("installed runtime identity is unavailable")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("productIntegration") is not True:
        raise UpdateError("invalid installed runtime identity")
    value = manifest.get("version")
    version_key(value)
    return value


def is_newer(current: str, candidate: str) -> bool:
    left, right = version_key(current), version_key(candidate)
    if right[0] != left[0]:
        return right[0] > left[0]
    if right[1] is None and left[1] is not None:
        return True
    if right[1] is not None and left[1] is None:
        return False
    if left[1] is None:
        return False
    for current_part, candidate_part in zip(left[1].split("."), right[1].split(".")):
        if current_part == candidate_part:
            continue
        if current_part.isdigit() and candidate_part.isdigit():
            return int(candidate_part) > int(current_part)
        if current_part.isdigit() != candidate_part.isdigit():
            return current_part.isdigit()  # numeric identifiers precede text
        return candidate_part > current_part
    return len(right[1].split(".")) > len(left[1].split("."))


def allowed(url: str, *, allow_loopback: bool) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS and
            not parsed.username and not parsed.password):
        if parsed.hostname in ("github.com", "www.github.com") and not parsed.path.startswith((RELEASE_PREFIX, LATEST_PREFIX)):
            raise UpdateError("update source is not a WebOBS release asset")
        return parsed
    if allow_loopback and parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost"):
        return parsed
    raise UpdateError("update source is not an approved HTTPS GitHub origin")


def fetch(url: str, limit: int, *, allow_loopback=False) -> tuple[bytes, str]:
    allowed(url, allow_loopback=allow_loopback)
    request = urllib.request.Request(url, headers={"User-Agent": "WebOBS-Wall-Updater"})
    with urllib.request.urlopen(request, timeout=30) as response:
        allowed(response.geturl(), allow_loopback=allow_loopback)
        data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("update metadata or installer exceeds its bound")
    return data, response.geturl()


def stream_to(url: str, target: Path, limit: int, *, allow_loopback=False) -> tuple[int, str]:
    allowed(url, allow_loopback=allow_loopback)
    request = urllib.request.Request(url, headers={"User-Agent": "WebOBS-Wall-Updater"})
    digest = hashlib.sha512()
    total = 0
    with urllib.request.urlopen(request, timeout=60) as response, target.open("xb") as output:
        allowed(response.geturl(), allow_loopback=allow_loopback)
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            total += len(block)
            if total > limit:
                raise UpdateError("installer exceeds its bound")
            digest.update(block)
            output.write(block)
        output.flush()
        os.fsync(output.fileno())
    return total, base64.b64encode(digest.digest()).decode("ascii")


def parse_feed(text: str) -> dict:
    lines = text.replace("\r\n", "\n").split("\n")
    result = {"version": None, "files": []}
    current = None
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        stripped = raw.lstrip()
        item_indent = len(raw) - len(stripped)
        if stripped.startswith("- "):
            if item_indent == 2:
                current = {}
                result["files"].append(current)
                entry = stripped[2:].strip()
                if ":" in entry:
                    name, item = entry.split(":", 1)
                    current[name.strip()] = item.strip().strip("'\"")
            continue
        match = re.match(r"^(\s*)([A-Za-z0-9]+):\s*(.*)$", raw)
        if not match:
            continue
        indent, key, value = len(match.group(1)), match.group(2), match.group(3).strip().strip("'\"")
        if indent == 0 and key == "version":
            result["version"] = value
        elif indent == 0 and key == "path":
            result["path"] = value
        elif indent == 0 and value == "" and key == "files":
            continue
        elif indent >= 4 and current is not None:
            current[key] = value
    if not result["version"] or not result["files"]:
        raise UpdateError("update feed is incomplete")
    version_key(result["version"])
    return result


def choose_installer(feed: dict) -> dict:
    for item in feed["files"]:
        if str(item.get("url", "")).lower().endswith(".exe"):
            try:
                size = int(item.get("size"))
            except (TypeError, ValueError):
                raise UpdateError("installer size is invalid") from None
            if not 1024 <= size <= MAX_INSTALLER:
                raise UpdateError("installer size is invalid")
            item = dict(item, size=size)
            sha = item.get("sha512")
            if not isinstance(sha, str) or len(sha) < 80:
                raise UpdateError("installer SHA-512 is missing")
            return item
    raise UpdateError("update feed has no Windows installer")


def resolve_installer(feed_url: str, item: dict) -> str:
    return urllib.parse.urljoin(feed_url, item["url"])


def check(feed_url: str, current: str, *, allow_loopback=False) -> dict:
    data, _ = fetch(feed_url, MAX_FEED, allow_loopback=allow_loopback)
    try:
        feed = parse_feed(data.decode("utf-8"))
    except UnicodeError:
        raise UpdateError("update feed is not UTF-8") from None
    item = choose_installer(feed)
    if version_key(current)[1] is None and version_key(feed["version"])[1] is not None:
        raise UpdateError("stable update source returned a prerelease")
    available = is_newer(current, feed["version"])
    return {"schema": 1, "status": "available" if available else "current",
            "version": feed["version"], "current": current,
            "url": resolve_installer(feed_url, item) if available else "",
            "sha512": item["sha512"], "size": item["size"],
            "notes": str(feed.get("releaseNotes", ""))[:4000]}


def download(manifest: dict, output: Path, *, allow_loopback=False) -> dict:
    if manifest.get("status") != "available":
        raise UpdateError("no update is available")
    output.mkdir(parents=True, exist_ok=True)
    target = output / ("WebOBS-Wall-" + manifest["version"] + "-windows-x64.exe")
    if target.exists():
        raise UpdateError("downloaded installer already exists; inspect it before retrying")
    temporary = target.with_suffix(".partial")
    if temporary.exists():
        raise UpdateError("partial download already exists; inspect it before retrying")
    try:
        total, digest = stream_to(manifest["url"], temporary, MAX_INSTALLER,
                                  allow_loopback=allow_loopback)
        if total != manifest["size"]:
            raise UpdateError("installer size mismatch")
        if digest != manifest["sha512"]:
            raise UpdateError("installer SHA-512 mismatch")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    receipt = {"schema": 1, "status": "downloaded", "version": manifest["version"],
               "installer": target.name, "bytes": total, "sha512": digest,
               "verified": True}
    (output / "update-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def stop_required() -> None:
    if os.name != "nt":
        return
    for image in ("webobs-wall.exe", "obs64.exe", "webobsd.exe"):
        result = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        if image in result.stdout.lower():
            raise UpdateError("close WebOBS Wall before installing the update")


def _runtime_root(value: Path | None) -> Path:
    runtime = (Path(value).resolve(strict=True) if value is not None
               else Path(sys.executable).resolve().parent.parent)
    if any(path.is_symlink() for path in (runtime, *runtime.parents)):
        raise UpdateError("maintenance runtime path is unsafe")
    if not (runtime / "python/python.exe").is_file() or not (runtime / "bin/libsodium.dll").is_file():
        raise UpdateError("maintenance runtime components are unavailable")
    return runtime


def backup_config(config_root: Path, data_root: Path, *, runtime_root: Path | None = None) -> None:
    key = data_root / "run/backup.key"
    runtime = _runtime_root(runtime_root)
    module = runtime / "services/backup/encrypted_backup.py"
    if not key.is_file() or not module.is_file():
        if config_root.is_dir() and any(config_root.iterdir()):
            raise UpdateError("configuration backup is unavailable; update was not started")
        return
    # The packaged service uses the same private key and verifies its own output.
    result = subprocess.run([str(runtime / "python/python.exe"), "-B", str(module), "create"],
                            env={**os.environ, "WEBOBS_BACKUP_CONFIG_ROOT": str(config_root),
                                 "WEBOBS_BACKUP_ROOT": str(data_root / "backups"),
                                 "WEBOBS_BACKUP_KEY_FILE": str(key),
                                 "WEBOBS_LIBSODIUM_LIBRARY": str(runtime / "bin/libsodium.dll")},
                            timeout=300, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise UpdateError(_backup_error_code(result.stderr, "backup-create-failed"))


def _backup_error_code(stderr: str, fallback: str) -> str:
    text = (stderr or "").lower()
    for marker, code in (
        ("confirmation", "backup-confirmation-invalid"),
        ("backup key", "backup-key-invalid"),
        ("authentication", "backup-authentication-failed"),
        ("integrity", "backup-integrity-failed"),
        ("unsafe", "backup-archive-unsafe"),
        ("libsodium", "backup-runtime-unavailable"),
        ("no such file", "backup-component-missing"),
    ):
        if marker in text:
            return code
    # BackupError messages are deliberately generic. Keep only a bounded
    # classification, never a path or traceback.
    if "sqlerror" in text or "sqlite" in text:
        return "backup-database-error"
    if "permissionerror" in text or "access is denied" in text:
        return "backup-permission-failed"
    if "filenotfounderror" in text or "cannot find" in text or "no such file" in text:
        return "backup-file-missing"
    if "oserror" in text or "winerror" in text or "ioerror" in text:
        return "backup-filesystem-error"
    return fallback


def restore_backup(archive: Path, data_root: Path, *, confirm: bool,
                   runtime_root: Path | None = None) -> dict:
    if not confirm:
        raise UpdateError("restoring configuration requires explicit confirmation")
    stop_required()
    runtime = _runtime_root(runtime_root)
    module = runtime / "services/backup/encrypted_backup.py"
    key = data_root / "run/backup.key"
    if (archive.is_symlink() or not archive.is_file() or key.is_symlink() or
            not key.is_file() or key.stat().st_size != 32 or not module.is_file()):
        raise UpdateError("backup archive, original key or restore component is unavailable")
    result = subprocess.run([str(runtime / "python/python.exe"), "-B", str(module), "restore", str(archive.resolve()),
                             "--config-root", str((data_root / "config").resolve()),
                             "--key-file", str(key.resolve())], timeout=300,
                            env={**os.environ, "WEBOBS_RESTORE_CONFIRM": "replace-config",
                                 "WEBOBS_LIBSODIUM_LIBRARY": str(runtime / "bin/libsodium.dll")},
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise UpdateError(_backup_error_code(result.stderr, "backup-restore-failed"))
    return {"schema": 1, "status": "restored", "configurationRestored": True}


def verify_installer(installer: Path, manifest: dict) -> dict:
    """A receipt is bookkeeping, never authority for executable bytes."""
    size = manifest.get("size")
    expected = manifest.get("sha512")
    if (type(size) is not int or not 1024 <= size <= MAX_INSTALLER or
            not isinstance(expected, str)):
        raise UpdateError("invalid installer integrity metadata")
    try:
        if len(base64.b64decode(expected, validate=True)) != 64:
            raise ValueError("invalid digest length")
    except ValueError:
        raise UpdateError("invalid installer SHA-512") from None
    if (installer.is_symlink() or not installer.is_file() or
            getattr(installer.lstat(), "st_file_attributes", 0) & 0x400):
        raise UpdateError("verified installer is missing or linked")
    digest = hashlib.sha512()
    total = 0
    with installer.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            total += len(block)
            if total > size:
                raise UpdateError("installer size mismatch")
            digest.update(block)
    if total != size or base64.b64encode(digest.digest()).decode("ascii") != expected:
        raise UpdateError("installer size or SHA-512 mismatch")
    return {"schema": 1, "version": manifest["version"], "sha512": expected,
            "bytes": total, "installer": installer.name, "verified": True}


def install(manifest: dict, output: Path, install_dir: Path | None, data_root: Path, *,
            confirm: bool, allow_loopback=False, runtime_root: Path | None = None) -> dict:
    if not confirm:
        raise UpdateError("installation requires explicit confirmation")
    if manifest.get("status") != "available" or not is_newer(
            manifest.get("current"), manifest.get("version")):
        raise UpdateError("no newer update is available")
    if version_key(manifest["current"])[1] is None and version_key(manifest["version"])[1] is not None:
        raise UpdateError("stable installation cannot install a prerelease update")
    stop_required()
    receipt_path = output / "update-receipt.json"
    installer = output / ("WebOBS-Wall-" + manifest["version"] + "-windows-x64.exe")
    if receipt_path.is_file() and installer.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("version") != manifest["version"] or receipt.get("sha512") != manifest["sha512"]:
            raise UpdateError("existing download does not match the update manifest")
    else:
        receipt = download(manifest, output, allow_loopback=allow_loopback)
        installer = output / receipt["installer"]
    if not installer.is_file():
        raise UpdateError("verified installer is missing")
    receipt = verify_installer(installer, manifest)
    config_root = data_root / "config"
    try:
        backup_config(config_root, data_root, runtime_root=runtime_root)
        # Backup can take time; validate the final cache again before execution.
        receipt = verify_installer(installer, manifest)
        pending = {"schema": 1, "from": manifest.get("current"), "to": manifest["version"],
                   "installer": str(installer), "sha512": receipt["sha512"],
                   "size": receipt["bytes"]}
        (data_root / "run").mkdir(parents=True, exist_ok=True)
        (data_root / "run/pending-update.json").write_text(json.dumps(pending, indent=2) + "\n",
                                                           encoding="utf-8")
        command = [str(installer), "/S"]
        if install_dir is not None:
            command.append("/D=" + str(install_dir))
        subprocess.run(command, check=True, timeout=1800)
    except Exception:
        (data_root / "run/pending-update.json").unlink(missing_ok=True)
        raise
    return {"schema": 1, "status": "installed", "version": manifest["version"],
            "sha512": receipt["sha512"], "installerLaunched": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check")
    check_parser.add_argument("--feed", required=True)
    current_identity = check_parser.add_mutually_exclusive_group(required=True)
    current_identity.add_argument("--current")
    current_identity.add_argument("--current-runtime", type=Path)
    check_parser.add_argument("--exit-code", action="store_true",
                              help="return 2 when no newer update is available")
    check_parser.add_argument("--output", type=Path, required=True)
    check_parser.add_argument("--allow-insecure-loopback-test", action="store_true")
    download_parser = sub.add_parser("download")
    download_parser.add_argument("--manifest", type=Path, required=True)
    download_parser.add_argument("--output", type=Path, required=True)
    download_parser.add_argument("--allow-insecure-loopback-test", action="store_true")
    install_parser = sub.add_parser("install")
    install_parser.add_argument("--manifest", type=Path, required=True)
    install_parser.add_argument("--output", type=Path, required=True)
    install_parser.add_argument("--data-root", type=Path, required=True)
    install_parser.add_argument("--install-dir", type=Path)
    install_parser.add_argument("--current-runtime", type=Path)
    install_parser.add_argument("--confirm", action="store_true")
    install_parser.add_argument("--allow-insecure-loopback-test", action="store_true")
    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("--archive", type=Path, required=True)
    restore_parser.add_argument("--data-root", type=Path, required=True)
    restore_parser.add_argument("--confirm", action="store_true")
    prepare_parser = sub.add_parser("prepare-maintenance")
    prepare_parser.add_argument("--runtime", type=Path, required=True)
    prepare_parser.add_argument("--data-root", type=Path, required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)
    sub.add_parser("finish-maintenance")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "prepare-maintenance":
            result = prepare_maintenance(arguments.runtime, arguments.data_root, arguments.output)
        elif arguments.command == "finish-maintenance":
            result = {"schema": 1, "status": "finished"}
        elif arguments.command == "check":
            current = runtime_version(arguments.current_runtime) if arguments.current_runtime else arguments.current
            result = check(arguments.feed, current,
                           allow_loopback=arguments.allow_insecure_loopback_test)
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        elif arguments.command == "download":
            result = download(json.loads(arguments.manifest.read_text(encoding="utf-8")),
                              arguments.output, allow_loopback=arguments.allow_insecure_loopback_test)
        elif arguments.command == "restore":
            result = restore_backup(arguments.archive, arguments.data_root, confirm=arguments.confirm)
        else:
            manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
            if arguments.current_runtime:
                manifest["current"] = runtime_version(arguments.current_runtime)
            result = install(manifest,
                             arguments.output, arguments.install_dir.resolve() if arguments.install_dir else None,
                             arguments.data_root,
                             confirm=arguments.confirm,
                             allow_loopback=arguments.allow_insecure_loopback_test)
        print(json.dumps(result, sort_keys=True))
        if arguments.command in ("install", "restore", "finish-maintenance") or (
                arguments.command == "check" and result["status"] == "current"):
            finish_maintenance()
        if arguments.command == "check" and arguments.exit_code and result["status"] == "current":
            return 2
        return 0
    except (UpdateError, OSError, ValueError, subprocess.SubprocessError):
        print("WebOBS update check/download/install failed; the current version was kept.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
