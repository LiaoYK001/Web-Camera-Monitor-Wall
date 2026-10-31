#!/usr/bin/env python3
"""Install or remove a frozen WebOBS native prototype bundle, privately.

This is a prototype installer, not a signed product installer: it copies a
verified prototype ZIP into a private directory, keeps the portable OBS
profile (`config/`) across reinstall or upgrade, rejects archives that would
ship a configured profile or unsafe paths, and writes a bounded receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid
import zipfile

VERSION = re.compile(r"^\d+\.\d+\.\d+-dev\.[0-9A-Za-z.-]+$")
MANIFEST = "webobs-native-prototype.json"
LAUNCHER = "launch-native.ps1"
OBS_EXECUTABLE = "bin/64bit/obs64.exe"
REQUIRED_ENTRIES = (MANIFEST, LAUNCHER, OBS_EXECUTABLE)


class InstallError(RuntimeError):
    """A bounded installer failure with a fixed, path-free code."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entry_parts(info: zipfile.ZipInfo) -> list[str]:
    name = info.filename.replace("\\", "/")
    parts = [part for part in name.split("/") if part]
    if name.startswith("/") or not parts:
        raise InstallError("bundle-path-unsafe")
    if any(part in (".", "..") for part in parts):
        raise InstallError("bundle-path-unsafe")
    if ":" in parts[0]:
        raise InstallError("bundle-path-unsafe")
    if parts[0] == "config":
        raise InstallError("bundle-contains-config")
    return parts


def validate_archive(package: Path) -> dict:
    """Validate entry names and the prototype manifest without extracting."""
    if not package.is_file():
        raise InstallError("package-missing")
    try:
        with zipfile.ZipFile(package) as archive:
            names = set()
            for info in archive.infolist():
                _entry_parts(info)
                names.add(info.filename.replace("\\", "/"))
            missing = [entry for entry in REQUIRED_ENTRIES if entry not in names]
            if missing:
                raise InstallError("bundle-incomplete")
            manifest = json.loads(archive.read(MANIFEST).decode("utf-8"))
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InstallError("bundle-unreadable") from error
    if not isinstance(manifest, dict) or not VERSION.match(str(manifest.get("version", ""))):
        raise InstallError("bundle-manifest-invalid")
    if manifest.get("defaultProduct") is not False:
        raise InstallError("bundle-manifest-invalid")
    if manifest.get("servicesStarted") != []:
        raise InstallError("bundle-manifest-invalid")
    return manifest


def _write_receipt(receipt: Path | None, payload: dict) -> None:
    if receipt is None:
        return
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


def install(package: Path, root: Path, receipt: Path | None) -> dict:
    """Install or replace a bundle at root, preserving an existing portable profile."""
    package = package.resolve()
    root = Path(os.path.abspath(root))
    if root.parent == root or root.name in ("", ".", ".."):
        raise InstallError("install-root-unsafe")
    if root.exists() and not (root / MANIFEST).is_file():
        raise InstallError("install-root-not-bundle")
    manifest = validate_archive(package)
    digest = sha256_file(package)
    previous = None
    if root.exists():
        previous = json.loads((root / MANIFEST).read_text(encoding="utf-8"))["version"]
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = root.parent / f"{root.name}.staging-{uuid.uuid4().hex[:12]}"
    backup = root.parent / f"{root.name}.backup-{uuid.uuid4().hex[:12]}"
    config_preserved = False
    try:
        staging.mkdir()
        with zipfile.ZipFile(package) as archive:
            archive.extractall(staging)
        if (root / "config").is_dir():
            shutil.copytree(root / "config", staging / "config", symlinks=False)
            config_preserved = True
        if root.exists():
            shutil.move(str(root), str(backup))
        shutil.move(str(staging), str(root))
        if backup.exists():
            shutil.rmtree(backup)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if not root.exists() and backup.exists():
            shutil.move(str(backup), str(root))
        raise
    payload = {
        "schema": 1,
        "action": "install",
        "version": manifest["version"],
        "previousVersion": previous,
        "configPreserved": config_preserved,
        "packageSha256": digest,
        "packageBytes": package.stat().st_size,
        "fileCount": sum(1 for path in root.rglob("*") if path.is_file()),
        "installedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "scope": "private-portable-prototype",
    }
    _write_receipt(receipt, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return payload


def uninstall(root: Path, receipt: Path | None) -> dict:
    """Remove a previously installed prototype bundle; never touches anything else."""
    root = Path(os.path.abspath(root))
    if not (root / MANIFEST).is_file():
        raise InstallError("install-root-not-bundle")
    version = json.loads((root / MANIFEST).read_text(encoding="utf-8"))["version"]
    shutil.rmtree(root)
    payload = {
        "schema": 1,
        "action": "uninstall",
        "version": version,
        "uninstalledAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "scope": "private-portable-prototype",
    }
    _write_receipt(receipt, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, help="frozen prototype ZIP")
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.uninstall:
            uninstall(args.install_root, args.receipt)
        else:
            if args.package is None:
                raise InstallError("package-missing")
            install(args.package, args.install_root, args.receipt)
    except InstallError as error:
        print(json.dumps({"schema": 1, "status": "failed", "code": str(error)}))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
