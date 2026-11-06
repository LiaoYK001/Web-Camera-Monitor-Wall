#!/usr/bin/env python3
"""Contract tests for staging frozen native dev assets; never touches Windows."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "verify_native_dev_assets", ROOT / "native-host/scripts/verify_native_dev_assets.py")
assert SPEC and SPEC.loader
verify_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_module)

VERSION = "4.1.0-dev.40"
REVISION = "3c916db" + "0" * 33


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class DevAssetTests(unittest.TestCase):
    def make_artifact(self, *, config_entry: bool = False, bad_sidecar: bool = False) -> tuple[tempfile.TemporaryDirectory, Path]:
        holding = tempfile.TemporaryDirectory()
        root = Path(holding.name) / "artifact"
        root.mkdir()
        setup = root / f"WebOBS-OBS-native-{VERSION}-windows-x64-SETUP.exe"
        setup.write_bytes(b"setup-bytes")
        manifest = {
            "schema": 1,
            "version": VERSION,
            "obsVersion": "32.1.2",
            "obsCommit": "fb4d98bf88fae5fc85cb11fc57f7c5e309282194",
            "defaultProduct": False,
            "servicesStarted": [],
        }
        prototype = root / f"WebOBS-OBS-native-{VERSION}-windows-x64-PROTOTYPE.zip"
        with zipfile.ZipFile(prototype, "w") as archive:
            archive.writestr("webobs-native-prototype.json", json.dumps(manifest))
            archive.writestr("bin/64bit/obs64.exe", b"binary")
            if config_entry:
                archive.writestr("config/obs-studio/global.ini", "secret")
        digest = sha256(prototype.read_bytes())
        Path(str(prototype) + ".sha256").write_text(
            f"{'0' * 64 if bad_sidecar else digest}  {prototype.name}\n", encoding="utf-8")
        receipt = {
            "schema": 1,
            "kind": "per-user-nsis-installer",
            "version": VERSION,
            "installerBytes": len(b"setup-bytes"),
            "installerSha256": sha256(b"setup-bytes"),
            "installedFileCount": 1_579,
            "configPreservedAcrossReinstall": True,
            "configPreservedAcrossUninstall": True,
            "registryCleanedOnUninstall": True,
            "signed": False,
        }
        (root / "native-nsis-installer.json").write_text(json.dumps(receipt), encoding="utf-8")
        return holding, root

    def test_verified_assets_are_staged_with_checksums(self):
        holding, root = self.make_artifact()
        with holding:
            output = root.parent / "output"
            summary = verify_module.verify(root, VERSION, REVISION, output)
            self.assertEqual(3, len(summary["assets"]))
            self.assertTrue((output / f"WebOBS-OBS-native-{VERSION}-windows-x64-SETUP.exe").is_file())
            lines = (output / "SHA256SUMS.txt").read_text().splitlines()
            self.assertEqual(2, len(lines))
            self.assertTrue(lines[0].endswith("windows-x64-SETUP.exe"))
            self.assertEqual(sha256(b"setup-bytes"), lines[0].split()[0])

    def test_private_config_entry_is_rejected(self):
        holding, root = self.make_artifact(config_entry=True)
        with holding, self.assertRaises(ValueError):
            verify_module.verify(root, VERSION, REVISION, root.parent / "output")

    def test_sidecar_mismatch_is_rejected(self):
        holding, root = self.make_artifact(bad_sidecar=True)
        with holding, self.assertRaises(ValueError):
            verify_module.verify(root, VERSION, REVISION, root.parent / "output")

    def test_signed_installer_receipt_is_rejected(self):
        holding, root = self.make_artifact()
        with holding:
            receipt_path = root / "native-nsis-installer.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["signed"] = True
            receipt_path.write_text(json.dumps(receipt))
            with self.assertRaises(ValueError):
                verify_module.verify(root, VERSION, REVISION, root.parent / "output")


if __name__ == "__main__":
    unittest.main(verbosity=2)
