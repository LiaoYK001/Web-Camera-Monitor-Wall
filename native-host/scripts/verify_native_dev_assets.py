#!/usr/bin/env python3
"""Verify the exact frozen assets of one native Windows dev build before publication.

Never rebuilds anything: it reads the downloaded Actions artifact, checks the installer
receipt, the prototype ZIP manifest and the sidecar digests, rejects private
configuration or traversal entries, then stages only the reviewed assets plus a
SHA256SUMS file. It makes no network request and prints no camera URLs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile


OBS_VERSION = "32.1.2"
OBS_COMMIT = "fb4d98bf88fae5fc85cb11fc57f7c5e309282194"
RECEIPT_NAME = "native-nsis-installer.json"
PINS = ("version", "obsVersion", "obsCommit", "defaultProduct", "servicesStarted")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject(message: str) -> None:
    raise ValueError(message)


def verify(artifact_dir: Path, version: str, revision: str, output: Path) -> dict:
    root = artifact_dir.resolve()
    if not root.is_dir():
        _reject("artifact directory is missing")
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision.lower()):
        _reject("revision must be a full 40-hex commit")
    receipt = json.loads((root / RECEIPT_NAME).read_text(encoding="utf-8"))
    if receipt.get("schema") != 1 or receipt.get("kind") != "per-user-nsis-installer":
        _reject("installer receipt has an unexpected schema")
    if receipt.get("version") != version:
        _reject("installer receipt version does not match the frozen version")
    if receipt.get("signed") is not False:
        _reject("a signed installer must never be published by this development path")
    for flag in ("configPreservedAcrossReinstall", "configPreservedAcrossUninstall", "registryCleanedOnUninstall"):
        if receipt.get(flag) is not True:
            _reject(f"installer receipt lacks {flag}")
    setups = sorted(root.glob(f"WebOBS-OBS-native-{version}-windows-x64-SETUP.exe"))
    prototypes = sorted(root.glob(f"WebOBS-OBS-native-{version}-windows-x64-PROTOTYPE.zip"))
    if len(setups) != 1 or len(prototypes) != 1:
        _reject("expected exactly one installer and one prototype ZIP")
    setup, prototype = setups[0], prototypes[0]
    if setup.stat().st_size != receipt.get("installerBytes"):
        _reject("installer bytes disagree with the receipt")
    setup_digest = sha256(setup)
    if setup_digest != str(receipt.get("installerSha256", "")).lower():
        _reject("installer digest disagrees with the receipt")
    sidecar = Path(str(prototype) + ".sha256")
    fields = sidecar.read_text(encoding="utf-8").split()
    prototype_digest = sha256(prototype)
    if len(fields) < 1 or fields[0].lower() != prototype_digest:
        _reject("prototype sidecar digest mismatch")
    if len(fields) > 1 and fields[-1] != prototype.name:
        _reject("prototype sidecar names another file")
    with zipfile.ZipFile(prototype) as archive:
        names = archive.namelist()
        for name in names:
            parts = Path(name).parts
            if name.startswith("/") or "\\" in name or ".." in parts or name == "config" or name.startswith("config/"):
                _reject("prototype ZIP contains an absolute, traversal or private-config entry")
        manifest = json.loads(archive.read("webobs-native-prototype.json").decode("utf-8"))
    if set(PINS) - set(manifest):
        _reject("prototype manifest is missing pinned fields")
    if manifest.get("version") != version or manifest.get("obsVersion") != OBS_VERSION or manifest.get("obsCommit") != OBS_COMMIT:
        _reject("prototype manifest identity does not match the frozen pin")
    if manifest.get("defaultProduct") is not False or manifest.get("servicesStarted") != []:
        _reject("prototype must not be the default product or start services")
    if output.exists() and any(output.iterdir()):
        _reject("output directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    staged = []
    for source in (setup, prototype):
        target = output / source.name
        shutil.copyfile(source, target)
        staged.append(target)
    checksums = output / "SHA256SUMS.txt"
    checksums.write_text("".join(f"{sha256(item)}  {item.name}\n" for item in staged), encoding="utf-8")
    return {
        "schema": 1,
        "kind": "native-dev-prerelease-assets",
        "version": version,
        "revision": revision,
        "installerBytes": setup.stat().st_size,
        "installerSha256": setup_digest,
        "prototypeBytes": prototype.stat().st_size,
        "prototypeSha256": prototype_digest,
        "prototypeFileCount": len(names),
        "privateConfigExcluded": True,
        "assets": [item.name for item in staged] + [checksums.name],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = verify(args.artifact_dir, args.version, args.revision, args.output)
    except ValueError as error:
        print(f"native dev asset verification failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
