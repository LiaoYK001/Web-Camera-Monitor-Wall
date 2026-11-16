#!/usr/bin/env python3
"""Stage the product's real control/services beside its single OBS media host."""
from __future__ import annotations

import argparse
from release_policy import delivery, copy_delivery
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

from prepare import OBS_COMMIT, digest, obtain


def archive_extractor(repo):
    specification = importlib.util.spec_from_file_location("product_archive_staging",
        repo / "desktop/scripts/stage-runtime.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module.extract


COMPLETE_ARTIFACTS = {"vcpkg", "python", "go2rtc", "mediamtx", "caddy", "ffmpeg",
                      "numpy", "onnxruntime", "flatbuffers", "packaging", "protobuf"}


def prepare_dependencies(repo, build_root, cache, offline, complete=False):
    lock = json.loads((repo / "desktop/dependencies.lock.json").read_text(encoding="utf-8"))
    if lock["obsCommit"] != OBS_COMMIT:
        raise ValueError("product control and native OBS pins must match")
    required = {"vcpkg", "python"} | (COMPLETE_ARTIFACTS if complete else set())
    selected = {item["id"]: item for item in lock["artifacts"] if item["id"] in required}
    if set(selected) != required:
        raise ValueError("missing locked product dependencies")
    for item in selected.values():
        obtain(item, cache, offline)
    destination = build_root / "vcpkg-source"
    if destination.exists():
        raise ValueError("product dependency source directory must be new")
    archive_extractor(repo)(cache / "vcpkg.zip", destination)


def stage_complete(repo, runtime, cache, build_root):
    """Stage the existing business services and their shipped dependencies."""
    lock = json.loads((repo / "desktop/dependencies.lock.json").read_text(encoding="utf-8"))
    artifacts = {item["id"]: item for item in lock["artifacts"]}
    missing = COMPLETE_ARTIFACTS - set(artifacts)
    if missing:
        raise ValueError("complete product lock is missing artifacts: " + ", ".join(sorted(missing)))
    extract = archive_extractor(repo)
    unpack = build_root / "complete-unpacked"
    unpack.mkdir(exist_ok=True)
    for artifact_id in COMPLETE_ARTIFACTS:
        item = artifacts[artifact_id]
        archive = cache / (artifact_id + ".zip")
        if digest(archive) != item["sha256"]:
            raise ValueError("complete product dependency digest mismatch: " + artifact_id)
        destination = unpack / artifact_id
        if not destination.exists():
            destination.mkdir()
            extract(archive, destination)
    site = runtime / "python/Lib/site-packages"
    site.mkdir(parents=True, exist_ok=True)
    (runtime / "python/python312._pth").write_text(
        "python312.zip\n.\nLib/site-packages\n../services\nimport site\n", encoding="ascii")
    for package in ("numpy", "onnxruntime", "flatbuffers", "packaging", "protobuf"):
        for source in (unpack / package).iterdir():
            if source.name.startswith("."):
                continue
            destination = site / source.name
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                shutil.copy2(source, destination)
    binaries = runtime / "bin"
    online_installer = importlib.util.spec_from_file_location(
        "product_online_source_installer", repo / "scripts/install-online-source-runtime.py")
    online_module = importlib.util.module_from_spec(online_installer)
    online_installer.loader.exec_module(online_module)
    online_module.install(repo / "go2rtc/online-source-dependencies.lock.json", "windows-x64",
                          cache / "online-source", site, binaries, runtime / "licenses/online-source")
    for name in ("go2rtc", "mediamtx", "caddy"):
        found = list((unpack / name).rglob(name + ".exe"))
        if len(found) != 1:
            raise ValueError("complete product binary is missing or ambiguous: " + name)
        shutil.copy2(found[0], binaries / found[0].name)
    ffmpeg = list((unpack / "ffmpeg").rglob("ffmpeg.exe"))
    if len(ffmpeg) != 1:
        raise ValueError("complete product FFmpeg is missing or ambiguous")
    for source in ffmpeg[0].parent.iterdir():
        if source.is_file() and (source.name.lower() in {"ffmpeg.exe", "ffprobe.exe"} or
                                 source.suffix.lower() == ".dll"):
            shutil.copy2(source, binaries / source.name)
    services = runtime / "services"
    for name in ("camera", "events", "nvr", "cluster", "v2", "analytics", "archive", "backup"):
        target = services / name
        target.mkdir(parents=True, exist_ok=True)
        for source in (repo / name).glob("*.py"):
            shutil.copy2(source, target / source.name)
    for source in (repo / "desktop/python").glob("*.py"):
        shutil.copy2(source, services / "desktop-tools" / source.name)
    tools = services / "go2rtc"
    tools.mkdir(parents=True, exist_ok=True)
    for source in (repo / "go2rtc").glob("*.py"):
        shutil.copy2(source, tools / source.name)
    shutil.copy2(repo / "native-host/scripts/migrate-legacy.cmd", runtime / "MIGRATE-LEGACY.cmd")
    shutil.copy2(repo / "native-host/scripts/check-updates.cmd", runtime / "CHECK-UPDATES.cmd")
    shutil.copy2(repo / "native-host/scripts/restore-backup.cmd", runtime / "RESTORE-BACKUP.cmd")
    feed = repo / "native-host/update-feed.url"
    if feed.is_file():
        shutil.copy2(feed, runtime / "update-feed.url")
    etc = runtime / "etc"
    etc.mkdir(exist_ok=True)
    shutil.copy2(repo / "gateway/mediamtx.yml", etc / "mediamtx.yml")
    shutil.copy2(repo / "go2rtc/go2rtc.yaml", etc / "go2rtc.yaml")
    if (repo / "web/go2rtc-dist/index.html").is_file():
        shutil.copytree(repo / "web/go2rtc-dist", runtime / "go2rtc-www", dirs_exist_ok=True)
    licenses = runtime / "licenses/complete"
    for artifact_id in COMPLETE_ARTIFACTS - {"vcpkg"}:
        destination = licenses / artifact_id
        for source in (unpack / artifact_id).rglob("*"):
            if source.is_file() and any(word in source.name.lower() for word in
                                        ("license", "copying", "notice", "copyright")):
                relative = source.relative_to(unpack / artifact_id)
                (destination / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination / relative)
    shutil.copy2(repo / "desktop/dependencies.lock.json", licenses / "dependencies.lock.json")
    return sorted(COMPLETE_ARTIFACTS)


def stage(repo, runtime, core, vcpkg, cache, complete=False):
    if not (runtime / "webobs-native-prototype.json").is_file() or (runtime / "config").exists():
        raise ValueError("stage product services only into a clean native media build")
    manifest_path = runtime / "webobs-native-prototype.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    delivery(manifest)
    if manifest.get("productIntegration") is not True:
        raise ValueError("expected an internal product integration build")
    for path in (runtime / "python", runtime / "services", runtime / "product-components.json"):
        if path.exists() or path.is_symlink():
            raise ValueError("product component destination is already configured")
    lock = json.loads((repo / "desktop/dependencies.lock.json").read_text(encoding="utf-8"))
    python = next(item for item in lock["artifacts"] if item["id"] == "python")
    if digest(cache / "python.zip") != python["sha256"]:
        raise ValueError("embedded Python archive digest mismatch")
    archive_extractor(repo)(cache / "python.zip", runtime / "python")
    (runtime / "python/python312._pth").write_text("python312.zip\n.\n../services\nimport site\n", encoding="ascii")
    binaries = runtime / "bin"
    for directory in (core / "bin", vcpkg / "bin"):
        for source in directory.iterdir():
            if source.is_file() and source.suffix.lower() in {".exe", ".dll"}:
                if source.is_symlink():
                    raise ValueError("product binaries must not be links")
                shutil.copy2(source, binaries / source.name)
    for required in ("webobs-wall.exe", "webobsd.exe", "libsodium.dll"):
        if not (binaries / required).is_file():
            raise ValueError("missing product control binary")
    for source in binaries.glob("*.dll"):
        if source.name.lower().startswith(("msvcp", "vcruntime", "concrt")):
            shutil.copy2(source, runtime / "python" / source.name)
    services = runtime / "services"
    for name in ("camera", "cluster"):
        target = services / name
        target.mkdir(parents=True)
        for source in (repo / name).glob("*.py"):
            shutil.copy2(source, target / source.name)
    shutil.copy2(repo / "runtime_support.py", services / "runtime_support.py")
    (services / "desktop-tools").mkdir()
    shutil.copy2(repo / "desktop/python/private_directory.py", services / "desktop-tools/private_directory.py")
    (services / "product").mkdir()
    shutil.copy2(repo / "native-host/scripts/product_supervisor.py", services / "product/supervisor.py")
    shutil.copy2(repo / "native-host/scripts/release_policy.py", services / "product/release_policy.py")
    shutil.copy2(repo / "native-host/scripts/migrate_legacy.py", services / "product/migrate_legacy.py")
    shutil.copy2(repo / "native-host/scripts/native_updater.py", services / "product/native_updater.py")
    if not (repo / "web/dist/index.html").is_file():
        raise ValueError("product management UI must be built before staging")
    shutil.copytree(repo / "web/dist", runtime / "web")
    for source in (vcpkg / "share").rglob("*"):
        if source.is_file() and any(word in source.name.lower() for word in ("license", "copyright", "notice", "copying", "spdx")):
            destination = runtime / "licenses/product-control/vcpkg" / source.relative_to(vcpkg / "share")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    (runtime / "licenses/product-control").mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo / "desktop/dependencies.lock.json", runtime / "licenses/product-control/dependencies.lock.json")
    complete_artifacts = stage_complete(repo, runtime, cache, runtime.parent) if complete else []
    # This count includes the staged control/service/UI payload. The earlier
    # 100 MiB media-only receipt is preserved under its separate filename.
    files = []
    for path in sorted(runtime.rglob("*")):
        if path.is_symlink():
            raise ValueError("product runtime must not contain links")
        if path.is_file():
            files.append({"path": path.relative_to(runtime).as_posix(), "bytes": path.stat().st_size,
                          "sha256": digest(path)})
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    receipt = {"schema": 1, "kind": "native-product-integration-components", "sourceRevision": revision,
        "version": manifest["version"], "obsCommit": OBS_COMMIT, **copy_delivery(manifest),
        "defaultServices": (["accounts-and-registry", "control", "frontend", "events", "nvr",
                              "clients", "go2rtc", "backup"] if complete else
                             ["accounts-and-registry", "control", "frontend"]),
        "completeStaging": bool(complete), "completeArtifacts": complete_artifacts,
        "controlMode": "direct-only", "files": files, "totalBytesBeforeReceipt": sum(item["bytes"] for item in files),
        "fullFeatureMigrationQualified": False}
    (runtime / "product-components.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"kind": receipt["kind"], "files": len(files),
        "totalBytesBeforeReceipt": receipt["totalBytesBeforeReceipt"], "fullFeatureMigrationQualified": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "stage"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--core", type=Path)
    parser.add_argument("--vcpkg", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--complete", action="store_true", help="stage all existing business services and shipped dependencies")
    arguments = parser.parse_args()
    if arguments.action == "prepare":
        prepare_dependencies(arguments.repo.resolve(), arguments.build_root.resolve(), arguments.cache.resolve(),
                             arguments.offline, arguments.complete)
    else:
        if arguments.core is None or arguments.vcpkg is None:
            parser.error("stage requires --core and --vcpkg")
        stage(arguments.repo.resolve(), arguments.build_root.resolve() / "runtime",
              arguments.core.resolve(), arguments.vcpkg.resolve(), arguments.cache.resolve(),
              arguments.complete)
