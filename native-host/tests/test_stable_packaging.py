#!/usr/bin/env python3
"""Stable packaging identity: staging, Tag and update metadata stay bound.

A stable runtime or latest.yml must never come from a version number alone.
Both must record or require the actual acceptance receipt, and the release Tag
must come from the shared mapping (installer 5.1.0 -> Tag v5.1).
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "native-host/scripts"
sys.path.insert(0, str(SCRIPTS))
import stage
import update_manifest as manifest_writer
PRODUCT_PATCH = ROOT / "native-host/patches/obs-32.1.2-product-frontend.patch"
RECEIPT = "docs/qualification/windows-v5.1-release-2026-11-18.json"
REPOSITORY = "LiaoYK001/Web-Camera-Monitor-Wall"
REVISION = "3" * 40


def load(name: str, relative: str):
    specification = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def fixture_runtime(root: Path) -> tuple[Path, Path, Path]:
    repo, source, runtime = root / "repo", root / "source", root / "runtime"
    for path in stage.REQUIRED:
        target = runtime / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture - not a real binary")
    (runtime / "bin/64bit/Qt6Network.dll").write_bytes(b"fixture qt network")
    for relative in ("native-host/scripts/launch-native.ps1", "native-host/README.md",
                     "native-host/LICENSE", "desktop/dependencies.lock.json",
                     "native-host/patches/obs-32.1.2-product-frontend.patch"):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(PRODUCT_PATCH.read_bytes() if relative.endswith(".patch") else b"fixture")
    source.mkdir()
    (source / "COPYING").write_text("fixture license")
    (source / ".webobs-product-patch.json").write_text(json.dumps({"schema": 1}))
    return repo, source, runtime


def acceptance_file(directory: Path, version: str, label: str = "accepted", **overrides) -> Path:
    payload = {"schema": 1, "version": version, "repository": REPOSITORY,
               "sourceRevision": REVISION, "productIntegration": True,
               "installationQualified": True, "legacyUpgradeQualified": True,
               "fullFeatureMigrationQualified": True,
               "qualificationReceipt": RECEIPT, "targetMachine": "i9-13900HX / RTX 4090 Laptop"}
    payload.update(overrides)
    directory = directory / f"acceptance-{label}"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "acceptance.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def refuses(call, expectation):
    try:
        call()
    except (ValueError, SystemExit) as error:
        assert expectation in str(error), f"unexpected rejection: {error}"
        return
    raise AssertionError(f"stable packaging accepted: {expectation}")


def exercise():
    with tempfile.TemporaryDirectory(prefix="webobs-stable-") as temporary:
        base = Path(temporary)
        repo, source, runtime = fixture_runtime(base / "stage")
        accepted = acceptance_file(base, "5.1.0")
        manifest = stage.finalize(repo, source, runtime, "5.1.0", product=True, stable=True,
                                  acceptance=accepted, repository=REPOSITORY,
                                  source_revision=REVISION)
        assert manifest["releaseProfile"] == "native-complete-stable"
        assert manifest["releaseTag"] == "v5.1"
        assert manifest["stableUpdaterEnabled"] is True and manifest["candidate"] is False
        assert manifest["publicationForbidden"] is False
        assert manifest["qualificationReceipt"] == RECEIPT
        assert manifest["defaultProduct"] is False
        assert manifest["servicesStarted"] == []
        assert json.loads((runtime / "webobs-native-prototype.json").read_text(encoding="utf-8")) == manifest
        # The portable runtime still disables OBS's own updater; the product
        # updater is a separate user-confirmed tool reading latest.yml.
        assert (runtime / "disable_updater.txt").is_file() and (runtime / "portable_mode.txt").is_file()
        assert not (runtime / "config").exists()

        for label, arguments, expectation in (
                ("no-acceptance", dict(product=True, stable=True),
                 "requires the recorded acceptance file"),
                ("without-product", dict(stable=True, acceptance=accepted),
                 "requires the integrated product profile"),
                ("candidate-version", dict(product=True, stable=True, acceptance=accepted),
                 "cannot stage a candidate version"),
                ("both-profiles", dict(product=True, complete=True, stable=True, acceptance=accepted),
                 "mutually exclusive")):
            staged_repo, staged_source, staged_runtime = fixture_runtime(base / f"reject-{label}")
            version = "5.1.0-rc.26" if label == "candidate-version" else "5.1.0"
            refuses(lambda repo=staged_repo, source=staged_source, runtime=staged_runtime,
                    version=version, arguments=arguments: stage.finalize(
                        repo, source, runtime, version, **arguments), expectation)
        partial = acceptance_file(base, "5.1.0", label="partial", installationQualified=False)
        staged_repo, staged_source, staged_runtime = fixture_runtime(base / "reject-partial")
        refuses(lambda: stage.finalize(staged_repo, staged_source, staged_runtime, "5.1.0",
                                       product=True, stable=True, acceptance=partial,
                                       repository=REPOSITORY, source_revision=REVISION),
                "missing recorded gates")
        # Staging a stable runtime must already bind the reviewed source, not
        # only the later publication step.
        unbound_repo, unbound_source, unbound_runtime = fixture_runtime(base / "reject-unbound-revision")
        refuses(lambda: stage.finalize(unbound_repo, unbound_source, unbound_runtime, "5.1.0",
                                       product=True, stable=True, acceptance=accepted,
                                       repository=REPOSITORY),
                "requires the 40-character reviewed source revision")
        foreign_repo, foreign_source, foreign_runtime = fixture_runtime(base / "reject-foreign-repository")
        refuses(lambda: stage.finalize(foreign_repo, foreign_source, foreign_runtime, "5.1.0",
                                       product=True, stable=True, acceptance=accepted,
                                       repository="someone-else/repository",
                                       source_revision=REVISION),
                "belongs to another repository")
        shifted_repo, shifted_source, shifted_runtime = fixture_runtime(base / "reject-shifted-revision")
        refuses(lambda: stage.finalize(shifted_repo, shifted_source, shifted_runtime, "5.1.0",
                                       product=True, stable=True,
                                       acceptance=acceptance_file(base, "5.1.0", label="other-revision",
                                                                  sourceRevision="2" * 40),
                                       repository=REPOSITORY, source_revision=REVISION),
                "belongs to another source revision")

        payload = b"MZ" + b"stable installer" * 400
        stable_installer = base / "WebOBS-Wall-5.1.0-windows-x64-SETUP.exe"
        stable_installer.write_bytes(payload)
        output = base / "latest.yml"
        refuses(lambda: manifest_writer.main(["--installer", str(stable_installer),
                                             "--version", "5.1.0", "--output", str(output)]),
                "requires --acceptance")
        refuses(lambda: manifest_writer.main(["--installer", str(stable_installer), "--version", "5.1.0",
                                             "--output", str(output), "--acceptance", str(accepted)]),
                "requires --source-revision")
        refuses(lambda: manifest_writer.main(["--installer", str(stable_installer), "--version", "5.1.0",
                                             "--output", str(output), "--acceptance", str(accepted),
                                             "--source-revision", REVISION[:20]]),
                "requires --source-revision")
        refuses(lambda: manifest_writer.main(["--installer", str(stable_installer), "--version", "5.1.0",
                                             "--output", str(output), "--acceptance", str(accepted),
                                             "--source-revision", REVISION]),
                "requires --repository")
        refuses(lambda: manifest_writer.main(["--installer", str(stable_installer), "--version", "5.1.0",
                                             "--output", str(output), "--acceptance", str(partial),
                                             "--source-revision", REVISION, "--repository", REPOSITORY]),
                "missing recorded gates")
        refuses(lambda: manifest_writer.main(["--installer", str(stable_installer), "--version", "5.1.0",
                                             "--output", str(output), "--acceptance", str(accepted),
                                             "--source-revision", "2" * 40, "--repository", REPOSITORY]),
                "belongs to another source revision")
        assert manifest_writer.main(["--installer", str(stable_installer), "--version", "5.1.0",
                                     "--output", str(output), "--acceptance", str(accepted),
                                     "--source-revision", REVISION, "--repository", REPOSITORY]) == 0
        text = output.read_text(encoding="utf-8")
        digest = base64.b64encode(hashlib.sha512(payload).digest()).decode("ascii")
        assert "version: 5.1.0" in text and digest in text and f"size: {len(payload)}" in text
        assert stable_installer.name in text

        candidate = base / "WebOBS-Wall-5.1.0-rc.26-windows-x64-SETUP.exe"
        candidate.write_bytes(payload)
        assert manifest_writer.main(["--installer", str(candidate), "--version", "5.1.0-rc.26",
                                     "--output", str(output)]) == 0
        assert "version: 5.1.0-rc.26" in output.read_text()
        refuses(lambda: manifest_writer.main(["--installer", str(candidate), "--version", "5.2.0-rc.1",
                                             "--output", str(output)]),
                "must be 5.0.0-rc.N or 5.1.0-rc.N")
        refuses(lambda: manifest_writer.main(["--installer", str(candidate), "--version", "5.1.0-dev.2",
                                             "--output", str(output)]),
                "three-part, optionally with a -rc.N suffix")

        publisher = load("stable_publish_chain", "native-host/scripts/publish_candidate.py")
        policy = publisher.load_release_policy()
        assert policy.tag_for_version("5.1.0") == "v5.1"
        assert manifest["releaseTag"] == policy.tag_for_version(manifest["version"])
    print("PASS stable staging, update metadata and publication share one recorded identity")


if __name__ == "__main__":
    exercise()
