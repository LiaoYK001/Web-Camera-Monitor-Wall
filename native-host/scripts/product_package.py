#!/usr/bin/env python3
"""Verify a clean internal product payload and generate owned NSIS removals.

This packages the integrated R1 entry, not the historical portable prototype.
The internal marker forbids publication and does not qualify the full release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

OBS_COMMIT = "fb4d98bf88fae5fc85cb11fc57f7c5e309282194"
REQUIRED = {"bin/webobs-wall.exe", "bin/webobsd.exe", "bin/64bit/obs64.exe",
            "obs-plugins/64bit/webobs-native-host.dll", "python/python.exe",
            "services/product/supervisor.py", "web/index.html"}


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def bounded_json(path, limit):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("missing or oversized product receipt")
    return json.loads(path.read_text(encoding="utf-8"))


def verify(runtime, *, installed=False):
    runtime = Path(runtime).absolute()
    if runtime.is_symlink() or not runtime.is_dir():
        raise ValueError("product runtime must be a real directory")
    manifest = bounded_json(runtime / "webobs-native-prototype.json", 16384)
    receipt = bounded_json(runtime / "product-components.json", 16 * 1024 * 1024)
    if (manifest.get("productIntegration") is not True or manifest.get("publicationForbidden") is not True or
            manifest.get("defaultProduct") is not False or manifest.get("obsCommit") != OBS_COMMIT or
            not re.fullmatch(r"\d+\.\d+\.\d+-dev\.[0-9A-Za-z.-]+", manifest.get("version", "")) or
            receipt.get("kind") != "native-product-integration-components" or receipt.get("schema") != 1 or
            receipt.get("publicationForbidden") is not True or receipt.get("obsCommit") != OBS_COMMIT or
            receipt.get("version") != manifest["version"] or receipt.get("fullFeatureMigrationQualified") is not False or
            not re.fullmatch(r"[a-f0-9]{40}", receipt.get("sourceRevision", ""))):
        raise ValueError("internal product build identity mismatch")
    files = receipt.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 16384:
        raise ValueError("invalid product file inventory")
    owned, folded, total = set(), set(), 0
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
            raise ValueError("invalid product file entry")
        relative = entry["path"]
        if (not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative or
                any(ord(character) < 32 or character in '\"$' for character in relative)):
            raise ValueError("unsafe product file path")
        path = PurePosixPath(relative)
        if (path.is_absolute() or any(part in {".", "..", ""} for part in relative.split("/")) or
                path.parts[0].lower() in {"config", "backups", "logs", "recordings"} or
                relative in owned or relative.casefold() in folded or
                relative.casefold() in {"product-components.json", "uninstall.exe"}):
            raise ValueError("unsafe or duplicate product file path")
        target = runtime / relative
        if not target.is_file() or any(parent.is_symlink() or (getattr(parent.lstat(), "st_file_attributes", 0) & 0x400)
                                      for parent in (target, *target.parents)):
            raise ValueError("missing or linked product file")
        if (type(entry["bytes"]) is not int or entry["bytes"] < 0 or
                not isinstance(entry["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]) or
                target.stat().st_size != entry["bytes"] or digest(target) != entry["sha256"]):
            raise ValueError("product payload changed after staging")
        owned.add(relative)
        folded.add(relative.casefold())
        total += entry["bytes"]
    actual = set()
    for path in runtime.rglob("*"):
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("linked product runtime")
        if path.is_file():
            actual.add(path.relative_to(runtime).as_posix())
    allowed = owned | {"product-components.json"} | ({"Uninstall.exe"} if installed else set())
    if (actual != allowed or not REQUIRED <= owned or
            receipt.get("totalBytesBeforeReceipt") != total):
        raise ValueError("unaccounted or incomplete product payload")
    return {"schema": 1, "kind": "internal-native-product-payload", "version": manifest["version"],
            "sourceRevision": receipt["sourceRevision"], "files": sorted(actual),
            "totalBytes": total + (runtime / "product-components.json").stat().st_size +
                ((runtime / "Uninstall.exe").stat().st_size if installed else 0),
            "publicationForbidden": True, "fullFeatureMigrationQualified": False}


def write_removals(payload, destination):
    # Paths have already rejected every NSIS variable/quote/control character.
    lines = ["; Generated only from the verified payload; never enumerate user data."]
    directories = set()
    for relative in payload["files"]:
        path = relative.replace("/", "\\")
        lines.extend([f'  IfFileExists "$INSTDIR\\{path}" 0 +5', '    ClearErrors',
                      f'    Delete "$INSTDIR\\{path}"', '    IfErrors 0 +2',
                      '      Abort "A product file is in use; close WebOBS Wall before uninstalling."'])
        directories.update(parent.as_posix() for parent in PurePosixPath(relative).parents if parent != PurePosixPath("."))
    for directory in sorted(directories, key=lambda item: (-item.count("/"), item)):
        lines.append('  RMDir "$INSTDIR\\' + directory.replace("/", "\\") + '"')
    with Path(destination).open("x", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--removals", type=Path)
    parser.add_argument("--installed", action="store_true")
    arguments = parser.parse_args()
    if arguments.installed and arguments.removals:
        parser.error("installer removal ownership must come from the clean staged payload")
    payload = verify(arguments.runtime, installed=arguments.installed)
    if arguments.removals:
        write_removals(payload, arguments.removals)
    print(json.dumps({key: value for key, value in payload.items() if key != "files"}))
