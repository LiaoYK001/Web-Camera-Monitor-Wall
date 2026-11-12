#!/usr/bin/env python3
"""Stage the product's real control/services beside its single OBS media host."""
from __future__ import annotations

import argparse
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


def prepare_dependencies(repo, build_root, cache, offline):
    lock = json.loads((repo / "desktop/dependencies.lock.json").read_text(encoding="utf-8"))
    if lock["obsCommit"] != OBS_COMMIT:
        raise ValueError("product control and native OBS pins must match")
    selected = {item["id"]: item for item in lock["artifacts"] if item["id"] in {"vcpkg", "python"}}
    if set(selected) != {"vcpkg", "python"}:
        raise ValueError("missing locked product dependencies")
    for item in selected.values():
        obtain(item, cache, offline)
    destination = build_root / "vcpkg-source"
    if destination.exists():
        raise ValueError("product dependency source directory must be new")
    archive_extractor(repo)(cache / "vcpkg.zip", destination)


def stage(repo, runtime, core, vcpkg, cache):
    if not (runtime / "webobs-native-prototype.json").is_file() or (runtime / "config").exists():
        raise ValueError("stage product services only into a clean native media build")
    manifest_path = runtime / "webobs-native-prototype.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("productIntegration") is not True or manifest.get("publicationForbidden") is not True:
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
        "version": manifest["version"], "obsCommit": OBS_COMMIT, "publicationForbidden": True,
        "defaultServices": ["accounts-and-registry", "control", "frontend"],
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
    arguments = parser.parse_args()
    if arguments.action == "prepare":
        prepare_dependencies(arguments.repo.resolve(), arguments.build_root.resolve(), arguments.cache.resolve(), arguments.offline)
    else:
        if arguments.core is None or arguments.vcpkg is None:
            parser.error("stage requires --core and --vcpkg")
        stage(arguments.repo.resolve(), arguments.build_root.resolve() / "runtime",
              arguments.core.resolve(), arguments.vcpkg.resolve(), arguments.cache.resolve())
