#!/usr/bin/env python3
"""Candidate and stable publication identity, without touching GitHub.

The publisher must take every Tag from the shared release policy, keep
candidates outside the stable feed, and refuse a stable release whose
acceptance was never recorded or whose commit is not reachable from `main`.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVISION = "1" * 40


MODULE = None


def load():
    """Load once so the raised PublishError class stays the same object."""
    global MODULE
    if MODULE is None:
        specification = importlib.util.spec_from_file_location(
            "candidate_publish", ROOT / "native-host/scripts/publish_candidate.py")
        MODULE = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = MODULE
        specification.loader.exec_module(MODULE)
    return MODULE


class Runner:
    """Stand in for `gh`; the publisher must never reach the network here."""

    def __init__(self, *, compare="ahead", existing_release=False, existing_tag=False):
        self.compare = compare
        self.existing_release = existing_release
        self.existing_tag = existing_tag
        self.calls = []
        self.created = None

    def __call__(self, *arguments, capture=False, check=True):
        self.calls.append(list(arguments))
        if arguments[0] == "release" and arguments[1] == "view":
            code = 0 if self.existing_release else 1
            return subprocess.CompletedProcess(arguments, code, stdout="", stderr="")
        if arguments[0] == "api" and "git/ref/tags/" in arguments[1]:
            code = 0 if self.existing_tag else 1
            return subprocess.CompletedProcess(arguments, code, stdout="", stderr="")
        if arguments[0] == "api" and "compare/" in arguments[1]:
            assert f"{REVISION}...main" in arguments[1], arguments[1]
            payload = {"status": self.compare, "ahead_by": 0 if self.compare == "identical" else 3,
                       "merge_base_commit": {"sha": REVISION}}
            return subprocess.CompletedProcess(arguments, 0, stdout=json.dumps(payload), stderr="")
        if arguments[0] == "release" and arguments[1] == "create":
            self.created = list(arguments)
            return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected gh call: {arguments}")


def build(directory: Path, version: str, *, tampered=False, label="") -> tuple[Path, Path]:
    """Build one synthetic frozen package in its own directory.

    Every package keeps its own latest.yml so a later fixture cannot silently
    replace the update metadata that a publication was already verified against.
    """
    module = load()
    directory = directory / (label or version)
    directory.mkdir(parents=True, exist_ok=True)
    installer = directory / f"WebOBS-Wall-{version}-windows-x64-SETUP.exe"
    installer.write_bytes(b"synthetic installer payload" * 4)
    manifest = directory / "latest.yml"
    manifest.write_text(
        f"version: {version}\nfiles:\n  path: {installer.name}\n  sha512: {module.sha512_base64(installer)}\n"
        f"  size: {installer.stat().st_size}\n", encoding="utf-8")
    if tampered:
        installer.write_bytes(b"synthetic installer payload" * 5)
    return installer, manifest


def acceptance_file(directory: Path, version: str, label: str = "accepted", **overrides) -> Path:
    payload = {"schema": 1, "version": version,
               "repository": "LiaoYK001/Web-Camera-Monitor-Wall",
               "sourceRevision": REVISION, "productIntegration": True,
               "installationQualified": True, "legacyUpgradeQualified": True,
               "fullFeatureMigrationQualified": True,
               "qualificationReceipt": "docs/qualification/windows-v5.1-release-2026-11-18.json"}
    payload.update(overrides)
    directory = directory / f"acceptance-{label}"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "acceptance.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def refuses(call, expectation):
    module = load()
    try:
        call()
    except module.PublishError as error:
        assert expectation in str(error), f"unexpected rejection: {error}"
        return
    raise AssertionError(f"publication accepted: {expectation}")


def exercise():
    module = load()
    policy_module = module.load_release_policy()
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        notes = directory / "notes.md"
        notes.write_text("synthetic release notes\n", encoding="utf-8")

        candidate_version = "5.1.0-rc.26"
        installer, manifest = build(directory, candidate_version)
        runner = Runner()
        result = module.publish(installer, manifest, candidate_version,
                                "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                confirm=True, final=False, runner=runner)
        assert result["tag"] == "v5.1.0-rc.26", result["tag"]
        assert result["prerelease"] is True and result["sha256"] == module.sha256(installer)
        assert "--prerelease" in runner.created and "--latest" not in runner.created
        assert runner.created[1] == "create" and runner.created[2] == "v5.1.0-rc.26"
        assert "完整候选" in " ".join(runner.created)
        assert (installer.parent / "SHA256SUMS.txt").read_text(encoding="ascii").startswith(
            result["sha256"])
        assert not any("compare/" in " ".join(call) for call in runner.calls), \
            "a development candidate must not be required to come from main"

        stable_version = "5.1.0"
        stable_installer, stable_manifest = build(directory, stable_version)
        receipt = acceptance_file(directory, stable_version)
        runner = Runner(compare="ahead")
        result = module.publish(stable_installer, stable_manifest, stable_version,
                                "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                confirm=True, final=True, acceptance=receipt, runner=runner)
        assert result["tag"] == "v5.1", f"feature release must publish the two-part Tag: {result['tag']}"
        assert result["prerelease"] is False
        assert result["qualificationReceipt"] == \
            "docs/qualification/windows-v5.1-release-2026-11-18.json"
        assert "--latest" in runner.created and "--prerelease" not in runner.created
        assert "正式发布" in " ".join(runner.created)

        runner = Runner(compare="diverged")
        refuses(lambda: module.publish(stable_installer, stable_manifest, stable_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=True, final=True, acceptance=receipt, runner=runner),
                "reachable from reviewed main")
        assert runner.created is None, "a diverged stable build must not be uploaded"

        runner = Runner(compare="identical")
        assert module.publish(stable_installer, stable_manifest, stable_version,
                              "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                              confirm=True, final=True, acceptance=receipt,
                              runner=runner)["tag"] == "v5.1"

        refuses(lambda: module.publish(stable_installer, stable_manifest, stable_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=True, final=True, runner=Runner()),
                "--acceptance")
        partial = acceptance_file(directory, stable_version, label="partial",
                           legacyUpgradeQualified=False)
        refuses(lambda: module.publish(stable_installer, stable_manifest, stable_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=True, final=True, acceptance=partial,
                                       runner=Runner()), "missing recorded gates")
        other_version = acceptance_file(directory, "5.2.0", label="other-version")
        refuses(lambda: module.publish(stable_installer, stable_manifest, stable_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=True, final=True, acceptance=other_version,
                                       runner=Runner()), "another version")
        other_revision = acceptance_file(directory, stable_version, label="other-revision",
                                   sourceRevision="2" * 40)
        refuses(lambda: module.publish(stable_installer, stable_manifest, stable_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=True, final=True, acceptance=other_revision,
                                       runner=Runner()), "another source revision")
        thin_receipt = acceptance_file(directory, stable_version, label="thin-receipt",
                                   qualificationReceipt="short")
        refuses(lambda: module.publish(stable_installer, stable_manifest, stable_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=True, final=True, acceptance=thin_receipt,
                                       runner=Runner()), "bounded qualificationReceipt")

        refuses(lambda: module.publish(installer, manifest, "5.1.0-dev.3",
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=True, final=False, runner=Runner()),
                "three-part")
        refuses(lambda: module.release_tag(policy_module, "5.1.0-dev.3", final=False,
                                           acceptance=None,
                                           repository="LiaoYK001/Web-Camera-Monitor-Wall",
                                           source_revision=REVISION), "no publishable Tag")
        refuses(lambda: module.publish(stable_installer, stable_manifest, stable_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=True, final=False, runner=Runner()),
                "-rc.N candidate version")
        refuses(lambda: module.publish(installer, manifest, candidate_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=False, final=False, runner=Runner()),
                "explicit confirmation")
        tampered_installer, tampered_manifest = build(directory, candidate_version,
                                                      tampered=True, label="tampered")
        refuses(lambda: module.publish(tampered_installer, tampered_manifest, candidate_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=True, final=False, runner=Runner()),
                "does not match the frozen installer bytes")
        wrong_name = tampered_installer.parent / "renamed-setup.exe"
        wrong_name.write_bytes(tampered_installer.read_bytes())
        refuses(lambda: module.publish(wrong_name, manifest, candidate_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=True, final=False, runner=Runner()),
                "unexpected complete installer name")
        refuses(lambda: module.publish(installer, manifest, candidate_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=True, final=False,
                                       runner=Runner(existing_release=True)),
                "release already exists")
        refuses(lambda: module.publish(installer, manifest, candidate_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=True, final=False,
                                       runner=Runner(existing_tag=True)),
                "tag already exists")

        # Update metadata is verified against the frozen bytes field by field, so a
        # truncated package, a substituted package and a mismatched version all fail.
        def metadata_variant(label: str, *, version=None, size=None, sha512=None,
                             omit_size=False) -> tuple[Path, Path]:
            variant = directory / f"metadata-{label}"
            variant.mkdir(parents=True, exist_ok=True)
            copy = variant / installer.name
            copy.write_bytes(installer.read_bytes())
            digest = sha512 if sha512 is not None else module.sha512_base64(copy)
            written = size if size is not None else copy.stat().st_size
            manifest_path = variant / "latest.yml"
            manifest_path.write_text(
                f"version: {version or candidate_version}\nfiles:\n  path: {copy.name}\n"
                f"  sha512: {digest}\n", encoding="utf-8")
            if not omit_size:
                manifest_path.write_text(manifest_path.read_text(encoding="utf-8") +
                                         f"  size: {written}\n", encoding="utf-8")
            return copy, manifest_path

        publish_candidate = lambda inst, meta, version, **extra: module.publish(  # noqa: E731
            inst, meta, version, "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
            confirm=True, final=False, runner=Runner(), **extra)
        refuses(lambda: publish_candidate(*(metadata_variant("size",
                                        size=installer.stat().st_size + 1)), candidate_version),
                "does not match the frozen installer bytes")
        refuses(lambda: publish_candidate(*(metadata_variant("sha512",
                                        sha512=base64.b64encode(hashlib.sha512(b"substituted package").digest()).decode("ascii"))),
                                        candidate_version),
                "does not match the frozen installer bytes")
        refuses(lambda: publish_candidate(*(metadata_variant("version",
                                        version="5.1.0-rc.99")), candidate_version),
                "does not match the frozen installer bytes")
        refuses(lambda: publish_candidate(*(metadata_variant("no-size", omit_size=True)),
                                        candidate_version),
                "missing version, size or sha512")
        renamed_metadata = installer.parent / "latest.yaml"
        renamed_metadata.write_text(manifest.read_text(encoding="utf-8"), encoding="utf-8")
        refuses(lambda: publish_candidate(installer, renamed_metadata, candidate_version),
                "update metadata must be latest.yml")

        # A stable release only accepts a readable acceptance receipt that names
        # this version, repository and source revision with every gate recorded.
        stable_publish = lambda receipt: module.publish(  # noqa: E731
            stable_installer, stable_manifest, stable_version,
            "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes, confirm=True, final=True,
            acceptance=receipt, runner=Runner(compare="ahead"))
        refuses(lambda: stable_publish(directory / "acceptance-absent" / "acceptance.json"),
                "acceptance receipt is unreadable")
        unreadable = directory / "acceptance-unreadable"
        unreadable.mkdir(parents=True, exist_ok=True)
        (unreadable / "acceptance.json").write_text("{ not json", encoding="utf-8")
        refuses(lambda: stable_publish(unreadable / "acceptance.json"),
                "acceptance receipt is unreadable")
        not_object = directory / "acceptance-array"
        not_object.mkdir(parents=True, exist_ok=True)
        (not_object / "acceptance.json").write_text(json.dumps([True]), encoding="utf-8")
        refuses(lambda: stable_publish(not_object / "acceptance.json"),
                "acceptance receipt must be a JSON object")
        other_repository = acceptance_file(directory, stable_version, label="other-repository",
                                           repository="someone-else/repository")
        refuses(lambda: stable_publish(other_repository), "acceptance receipt belongs to "
                "another repository")
        empty_revision = acceptance_file(directory, stable_version, label="revision-unrecorded",
                                         sourceRevision=None)
        refuses(lambda: stable_publish(empty_revision),
                "does not record its source revision")

        # The chain must be provable up to a pending release: every gate runs, nothing is
        # written to disk and no upload call happens. That is how a candidate is verified
        # before the user's centralized acceptance exists, without publishing anything.
        pending_runner = Runner()
        pending_installer, pending_manifest = build(directory, candidate_version, label="pending")
        pending = module.publish(pending_installer, pending_manifest, candidate_version,
                                 "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                 confirm=False, final=False, runner=pending_runner,
                                 verify_only=True)
        assert pending["planned"] is True and pending["tag"] == "v5.1.0-rc.26", pending
        assert pending["prerelease"] is True and pending["confirmationRequired"] is True
        assert pending["sha256"] == module.sha256(pending_installer) \
            and pending["bytes"] == pending_installer.stat().st_size
        assert not any(call[:2] == ["release", "create"] for call in pending_runner.calls), \
            "verify-only must not upload"
        assert not (pending_installer.parent / "SHA256SUMS.txt").exists(), \
            "verify-only wrote a checksum file instead of staying pending"

        pending_stable = module.publish(stable_installer, stable_manifest, stable_version,
                                        "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                        confirm=False, final=True, acceptance=receipt,
                                        runner=Runner(compare="ahead"), verify_only=True)
        assert pending_stable["planned"] is True and pending_stable["tag"] == "v5.1"
        assert pending_stable["prerelease"] is False
        assert pending_stable["qualificationReceipt"].startswith("docs/qualification/")

        # Pending verification still refuses the same defects as a real publication.
        refuses(lambda: module.publish(tampered_installer, tampered_manifest, candidate_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=False, final=False, runner=Runner(),
                                       verify_only=True), "does not match the frozen installer bytes")
        refuses(lambda: module.publish(installer, manifest, candidate_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=False, final=False, runner=Runner(existing_tag=True),
                                       verify_only=True), "tag already exists")
        refuses(lambda: module.publish(installer, manifest, candidate_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=False, final=False, runner=Runner(existing_release=True),
                                       verify_only=True), "release already exists")
        refuses(lambda: module.publish(stable_installer, stable_manifest, stable_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=False, final=True, runner=Runner(compare="ahead"),
                                       verify_only=True), "--acceptance")
        refuses(lambda: module.publish(stable_installer, stable_manifest, stable_version,
                                       "LiaoYK001/Web-Camera-Monitor-Wall", REVISION, notes,
                                       confirm=False, final=True, acceptance=receipt,
                                       runner=Runner(compare="diverged"), verify_only=True),
                "reachable from reviewed main")

        policy = policy_module
        assert policy.tag_for_version(stable_version) == "v5.1"
        assert policy.tag_for_version("5.1.2") == "v5.1.2"
        assert policy.tag_for_version(candidate_version) == "v5.1.0-rc.26"
        accepted = module.read_acceptance(policy_module, receipt, stable_version,
                                          "LiaoYK001/Web-Camera-Monitor-Wall", REVISION)
        assert accepted["qualificationReceipt"].startswith("docs/qualification/")
        assert accepted["legacyUpgradeQualified"] is True
    print("PASS candidate Tags come from the shared policy; stable publication requires "
          "recorded acceptance and a reviewed main revision; pending verification runs every gate")


if __name__ == "__main__":
    exercise()
