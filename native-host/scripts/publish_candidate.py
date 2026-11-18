#!/usr/bin/env python3
"""Publish one frozen complete Windows candidate or stable release.

This is the portable counterpart of desktop/scripts/publish-native-candidate.ps1:
it verifies the exact installer bytes against latest.yml, writes a checksum
file, and creates an immutable GitHub release. Candidate identities stay
prereleases pinned to their own ``-rc.N`` Tag and never advertise the stable
updater feed. A stable release is allowed only with a recorded acceptance
receipt and a source revision reachable from the reviewed ``main`` branch; its
Tag comes from the single ``release_policy.tag_for_version`` mapping so a
feature release publishes ``v5.1`` while the installer keeps ``5.1.0``.
Nothing here overwrites an existing tag or asset.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path


class PublishError(RuntimeError):
    pass


def load_release_policy():
    """Load the single native release policy next to this script.

    Tag mapping and stable identity must not be reimplemented here.
    """
    path = Path(__file__).resolve().with_name("release_policy.py")
    specification = importlib.util.spec_from_file_location("webobs_native_release_policy", path)
    if specification is None or specification.loader is None:
        raise PublishError("cannot load the native release policy")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def read_acceptance(policy, path: Path, version: str, repository: str, source_revision: str) -> dict:
    """Delegate to the shared policy so one acceptance contract gates every tool."""
    try:
        return policy.read_acceptance(path, version=version, repository=repository,
                                      source_revision=source_revision)
    except ValueError as error:
        raise PublishError(str(error)) from error


def require_main_ancestry(runner, repository: str, source_revision: str) -> str:
    """Reject a stable build that is not reachable from the reviewed ``main``."""
    result = runner("api", f"repos/{repository}/compare/{source_revision}...main",
                    capture=True, check=False)
    if result.returncode != 0:
        raise PublishError("cannot compare the source revision with reviewed main")
    try:
        payload = json.loads(result.stdout)
    except ValueError as error:
        raise PublishError("main comparison returned unreadable JSON") from error
    status = payload.get("status")
    if status not in ("ahead", "identical"):
        raise PublishError(
            f"stable publication requires a source revision reachable from reviewed main "
            f"(compare status={status})")
    return status


def release_tag(policy, version: str, *, final: bool, acceptance: Path | None,
                repository: str, source_revision: str) -> tuple[str, str | None]:
    """Resolve the immutable Tag through the shared release policy."""
    if final:
        if acceptance is None:
            raise PublishError(
                "stable publication requires --acceptance with recorded Windows acceptance")
        identity = {"version": version}
        try:
            applied = policy.apply_acceptance(identity, acceptance.resolve(strict=True),
                                             repository=repository, source_revision=source_revision)
            return applied["releaseTag"], applied["qualificationReceipt"]
        except ValueError as error:
            raise PublishError(f"stable identity rejected: {error}") from error
    try:
        tag = policy.tag_for_version(version)
    except ValueError as error:
        raise PublishError(f"version has no publishable Tag: {error}") from error
    if "-rc." not in tag:
        raise PublishError("candidate publication requires a -rc.N candidate version")
    candidate = {"version": version, "productIntegration": True}
    try:
        policy.configure_complete(candidate)
    except ValueError as error:
        raise PublishError(f"candidate identity rejected: {error}") from error
    if candidate["stableUpdaterEnabled"] is not False or candidate["candidate"] is not True:
        raise PublishError("candidate identity must stay outside the stable updater feed")
    return tag, None


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
            source_revision: str, notes: Path, *, confirm: bool, final: bool,
            acceptance: Path | None = None, runner=gh) -> dict:
    if not confirm:
        raise PublishError("explicit confirmation is required")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-rc\.[0-9]+)?", version):
        raise PublishError("version must be three-part, optionally with a -rc.N suffix")
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
    policy = load_release_policy()
    tag, receipt = release_tag(policy, version, final=final, acceptance=acceptance,
                               repository=repository, source_revision=source_revision)
    if runner("release", "view", tag, "--repo", repository, capture=True, check=False).returncode == 0:
        raise PublishError("release already exists; never overwrite it")
    if runner("api", f"repos/{repository}/git/ref/tags/{tag}", capture=True,
              check=False).returncode == 0:
        raise PublishError("tag already exists; never overwrite it")
    if final:
        require_main_ancestry(runner, repository, source_revision)
    checksum = installer.parent / "SHA256SUMS.txt"
    checksum.write_text(f"{sha256(installer)}  {installer.name}\n", encoding="ascii")
    label = "正式发布 / stable release" if final else "完整候选 / complete candidate"
    arguments = ["release", "create", tag, str(installer), str(manifest), str(checksum),
                 "--repo", repository, "--title", f"WebOBS Wall {version} {label}",
                 "--notes-file", str(notes), "--target", source_revision]
    arguments.append("--prerelease" if not final else "--latest")
    runner(*arguments)
    result = {"schema": 1, "tag": tag, "prerelease": not final, "version": version,
              "installer": installer.name, "bytes": installer.stat().st_size,
              "sha256": sha256(installer), "sha512": metadata["sha512"],
              "sourceRevision": source_revision}
    if receipt:
        result["qualificationReceipt"] = receipt
    return result


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
    parser.add_argument("--acceptance", type=Path,
                        help="JSON acceptance receipt required for --final")
    arguments = parser.parse_args()
    try:
        result = publish(arguments.installer, arguments.manifest, arguments.version,
                         arguments.repository, arguments.source_revision, arguments.notes,
                         confirm=arguments.confirm, final=arguments.final,
                         acceptance=arguments.acceptance)
    except (PublishError, OSError) as error:
        print(f"candidate publication failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
