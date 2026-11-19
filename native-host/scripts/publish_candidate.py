#!/usr/bin/env python3
"""Publish one frozen complete Windows candidate from a maintainer host.

This is the portable counterpart of desktop/scripts/publish-native-candidate.ps1:
it verifies the exact installer bytes against latest.yml, writes a checksum
file, and creates an immutable prerelease. It never opens the stable feed,
never marks Latest, and never overwrites an existing tag or asset.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


class PublishError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha512_base64(path: Path) -> str:
    digest = hashlib.sha512()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return base64.b64encode(digest.digest()).decode("ascii")


def read_manifest(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    version = re.search(r"(?m)^version:\s*(\S+)\s*$", text)
    size = re.search(r"(?m)^\s+size:\s*(\d+)\s*$", text)
    sha512 = re.search(r"(?m)^\s+sha512:\s*(\S+)\s*$", text)
    if not version or not size or not sha512:
        raise PublishError("latest.yml is missing version, size or sha512")
    return {"version": version.group(1), "size": int(size.group(1)),
            "sha512": sha512.group(1)}


def gh(*arguments: str, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["gh", *arguments], text=True, capture_output=capture)
    if check and result.returncode != 0:
        raise PublishError(
            "gh " + " ".join(arguments) + " failed" +
            ("" if not capture else ": " + (result.stderr or "").strip()[:200]))
    return result


def publish(installer: Path, manifest: Path, version: str, repository: str,
            source_revision: str, notes: Path, *, confirm: bool,
            final: bool) -> dict:
    if not confirm:
        raise PublishError("explicit confirmation is required")
    if not re.fullmatch(r"5\.1\.0(?:-rc\.[0-9]+)?", version):
        raise PublishError("version must be 5.1.0 or a 5.1.0-rc.N candidate")
    if final and version != "5.1.0":
        raise PublishError("final publication requires version 5.1.0")
    if not re.fullmatch(r"[a-f0-9]{40}", source_revision):
        raise PublishError("source revision must be a full lowercase commit id")
    installer = installer.resolve(strict=True)
    manifest = manifest.resolve(strict=True)
    notes = notes.resolve(strict=True)
    expected_name = f"WebOBS-Wall-{version}-windows-x64-SETUP.exe"
    if installer.name != expected_name:
        raise PublishError("unexpected complete installer name")
    if manifest.name != "latest.yml":
        raise PublishError("update metadata must be latest.yml")
    metadata = read_manifest(manifest)
    if (metadata["version"] != version or metadata["size"] != installer.stat().st_size or
            metadata["sha512"] != sha512_base64(installer)):
        raise PublishError("latest.yml does not match the frozen installer bytes")
    tag = "v" + version
    if gh("release", "view", tag, "--repo", repository, capture=True, check=False).returncode == 0:
        raise PublishError("release already exists; never overwrite it")
    if gh("api", f"repos/{repository}/git/ref/tags/{tag}", capture=True, check=False).returncode == 0:
        raise PublishError("tag already exists; never overwrite it")
    checksum = installer.parent / "SHA256SUMS.txt"
    checksum.write_text(f"{sha256(installer)}  {installer.name}\n", encoding="ascii")
    arguments = ["release", "create", tag, str(installer), str(manifest), str(checksum),
                 "--repo", repository, "--title", f"WebOBS Wall {version} 完整候选 / complete candidate",
                 "--notes-file", str(notes), "--target", source_revision]
    arguments.append("--prerelease" if not final else "--latest")
    gh(*arguments)
    return {"schema": 1, "tag": tag, "prerelease": not final,
            "installer": installer.name, "bytes": installer.stat().st_size,
            "sha256": sha256(installer), "sha512": metadata["sha512"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--final", action="store_true")
    arguments = parser.parse_args()
    try:
        result = publish(arguments.installer, arguments.manifest, arguments.version,
                         arguments.repository, arguments.source_revision, arguments.notes,
                         confirm=arguments.confirm, final=arguments.final)
    except (PublishError, OSError) as error:
        print(f"candidate publication failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
