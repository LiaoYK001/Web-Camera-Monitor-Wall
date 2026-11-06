#!/usr/bin/env python3
"""Verified, product-owned OBS source/dependency staging; never patches upstream."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import urllib.parse
import urllib.request

OBS_COMMIT = "fb4d98bf88fae5fc85cb11fc57f7c5e309282194"
OBS_VERSION = "32.1.2"
ARTIFACTS = {"obs-deps": "prebuilt", "obs-qt": "qt6"}


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def git(source: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(source), *args], text=True)


def locked_artifacts(lock: dict, presets: dict) -> list[dict]:
    if lock.get("obsCommit") != OBS_COMMIT:
        raise ValueError("OBS dependency lock is not the qualified 32.1.2 commit")
    dependencies = next(p for p in presets["configurePresets"] if p["name"] == "dependencies")["vendor"]["obsproject.com/obs-studio"]["dependencies"]
    selected = []
    for artifact_id, upstream_key in ARTIFACTS.items():
        matches = [a for a in lock["artifacts"] if a["id"] == artifact_id]
        if len(matches) != 1:
            raise ValueError(f"Expected one locked artifact: {artifact_id}")
        artifact = matches[0]
        upstream = dependencies[upstream_key]
        filename = ("windows-deps-qt6-" if upstream_key == "qt6" else "windows-deps-") + upstream["version"] + "-x64.zip"
        expected_url = upstream["baseUrl"] + "/" + upstream["version"] + "/" + filename
        if artifact["version"] != upstream["version"] or artifact["sha256"] != upstream["hashes"]["windows-x64"] or artifact["url"] != expected_url:
            raise ValueError(f"Desktop/upstream dependency lock mismatch: {artifact_id}")
        if not expected_url.startswith("https://github.com/obsproject/obs-deps/releases/download/"):
            raise ValueError("Unapproved OBS dependency origin")
        selected.append(dict(artifact, filename=filename))
    return selected


def obtain(artifact: dict, cache: Path, offline: bool) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (artifact["id"] + ".zip")
    if target.exists():
        if digest(target) != artifact["sha256"]:
            # Do not silently replace a corrupt/shared cache artifact.
            raise ValueError(f"Cached dependency SHA-256 mismatch: {artifact['id']}")
        return target
    if offline:
        raise ValueError(f"Offline cache missing: {artifact['id']}")
    partial = target.with_suffix(".zip.partial")
    if partial.exists():
        raise ValueError(f"Incomplete dependency download exists: {artifact['id']}; inspect it before retrying")
    with urllib.request.urlopen(artifact["url"], timeout=60) as response, partial.open("xb") as output:
        if urllib.parse.urlparse(response.url).scheme != "https":
            raise ValueError("Dependency redirected away from HTTPS")
        shutil.copyfileobj(response, output)
    if digest(partial) != artifact["sha256"]:
        raise ValueError(f"Downloaded dependency SHA-256 mismatch: {artifact['id']}")
    # Source/target are explicit siblings in the caller's build cache; no deletion.
    partial.rename(target)
    return target


def snapshot(source: Path, destination: Path) -> None:
    source, destination = source.resolve(), destination.resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Source snapshot must be outside the upstream checkout")
    if git(source, "rev-parse", "HEAD").strip() != OBS_COMMIT:
        raise ValueError("OBS checkout commit mismatch")
    if git(source, "status", "--porcelain", "--untracked-files=no").strip():
        raise ValueError("OBS checkout has tracked modifications")
    submodules = git(source, "submodule", "status", "--recursive").splitlines()
    if any(not line.startswith(" ") for line in submodules):
        raise ValueError("OBS nested submodules are missing or at different commits")
    git(source, "submodule", "foreach", "--quiet", "--recursive", "git diff --quiet && git diff --cached --quiet")
    paths = git(source, "ls-files", "--recurse-submodules", "-z").split("\0")
    files = {}
    for relative in filter(None, paths):
        pure = PurePosixPath(relative)
        item = source / relative
        if pure.is_absolute() or ".." in pure.parts or (not item.is_symlink() and not item.is_file()):
            raise ValueError("Unsafe or missing tracked OBS source entry")
        # Pinned OBS has tooling-only symlinks. Materialize their link text, as
        # Git core.symlinks=false does on Windows; never follow an external path
        # or require Windows symlink privileges. No compiled source is patched.
        if item.is_symlink():
            files[relative] = hashlib.sha256(item.readlink().as_posix().encode("utf-8")).hexdigest()
        else:
            files[relative] = digest(item)
    receipt = {"obsCommit": OBS_COMMIT, "nestedSubmodules": submodules, "files": files}
    marker = destination / ".webobs-source.json"
    if destination.exists():
        if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")) != receipt:
            raise ValueError("Existing source snapshot does not match the fixed source; use a new build directory")
        for relative, expected in files.items():
            if not (destination / relative).is_file() or digest(destination / relative) != expected:
                raise ValueError(f"Source snapshot was modified: {relative}")
        return
    destination.mkdir(parents=True)
    for relative in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        original = source / relative
        if original.is_symlink():
            target.write_bytes(original.readlink().as_posix().encode("utf-8"))
        else:
            shutil.copy2(original, target)
    marker.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def prepare(repo: Path, output: Path, cache: Path, offline: bool) -> None:
    source = repo / "obs/obs-studio"
    lock = json.loads((repo / "desktop/dependencies.lock.json").read_text(encoding="utf-8"))
    presets = json.loads((source / "CMakePresets.json").read_text(encoding="utf-8"))
    artifacts = locked_artifacts(lock, presets)
    # Verify upstream before downloading/copying, and reject existing patched snapshots.
    snapshot(source, output)
    deps = output / ".deps"
    deps.mkdir(exist_ok=True)
    for artifact in artifacts:
        archive = obtain(artifact, cache, offline)
        target = deps / artifact["filename"]
        if target.exists():
            if digest(target) != artifact["sha256"]:
                raise ValueError("Staged dependency SHA-256 mismatch")
        else:
            shutil.copy2(archive, target)
        if digest(target) != artifact["sha256"]:
            raise ValueError("Dependency changed while staging")
    print("Verified OBS 32.1.2 snapshot and locked obs-deps/Qt inputs; no upstream patches")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    prepare(args.repo.resolve(), args.output.resolve(), args.cache.resolve(), args.offline)
