"""Synthetic export-policy fixtures, not Windows/media qualification."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "native-host/scripts"))
import product_package
import preview_assets
import release_policy


class PreviewReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.build = Path(temporary.name)
        self.runtime = self.build / "runtime"
        self.runtime.mkdir()
        self.manifest = {"version": "4.5.0", "productIntegration": True, "defaultProduct": False,
                         "obsCommit": product_package.OBS_COMMIT}
        release_policy.configure_preview(self.manifest)
        (self.runtime / "webobs-native-prototype.json").write_text(json.dumps(self.manifest))
        for name in product_package.REQUIRED | product_package.PREVIEW_REQUIRED:
            path = self.runtime / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic nonexecutable fixture")
        self.revision = "a" * 40
        self.receipt = {"schema": 1, "kind": "native-product-integration-components", "sourceRevision": self.revision,
                        "version": "4.5.0", "obsCommit": product_package.OBS_COMMIT,
                        **release_policy.copy_delivery(self.manifest)}
        files = [{"path": p.relative_to(self.runtime).as_posix(), "bytes": p.stat().st_size,
                  "sha256": product_package.digest(p)} for p in self.runtime.rglob("*") if p.is_file()]
        self.receipt.update(files=files, totalBytesBeforeReceipt=sum(p["bytes"] for p in files))
        (self.runtime / "product-components.json").write_text(json.dumps(self.receipt))

    def test_preview_identity_is_scoped_and_keeps_complete_product_gates_false(self):
        result = product_package.verify(self.runtime)
        self.assertEqual(result["version"], "4.5.0")
        self.assertFalse(result["publicationForbidden"])
        self.assertFalse(result["fullFeatureMigrationQualified"])
        self.assertFalse(result["stableUpdaterEnabled"])
        self.assertEqual(result["dataProfile"], "NativePreview")

    def test_unmarked_stable_or_relaxed_internal_build_cannot_publish(self):
        for identity in ({"version": "4.5.0", "publicationForbidden": True},
                         {"version": "4.5.0-dev.1", "publicationForbidden": False}):
            with self.assertRaises(ValueError):
                release_policy.delivery(identity)

    def test_preview_cannot_claim_migration_updates_other_versions_or_internal_data(self):
        for key, value in (("stableUpdaterEnabled", True), ("fullFeatureMigrationQualified", True),
                           ("legacyUpgradeQualified", True), ("version", "4.6.0"),
                           ("dataProfile", "NativeIntegration"), ("publicationForbidden", 0)):
            with self.assertRaises(ValueError):
                release_policy.delivery({**self.manifest, key: value})

    def test_export_requires_all_matching_gates_and_the_tested_installer_hash(self):
        installer = self.build / "internal-installer/WebOBS-Wall-4.5.0-windows-x64-PREVIEW-UNSIGNED.exe"
        installer.parent.mkdir()
        installer.write_bytes(b"synthetic nonexecutable installer fixture")
        for name in ("entry-ui", "restore", "installed-ui", "nsis"):
            value = {"passed": True, "version": "4.5.0", "sourceRevision": self.revision,
                     "fullFeatureMigrationQualified": False}
            if name == "nsis":
                value.update(freshInstalledEntryQualified=True, publicationForbidden=False,
                             legacyUpgradeQualified=False, setupBytes=installer.stat().st_size,
                             setupSha256=product_package.digest(installer))
            (self.build / f"native-product-{name}.json").write_text(json.dumps(value))
        bad = self.build / "native-product-installed-ui.json"
        saved = bad.read_bytes()
        bad.write_text(json.dumps({"passed": False}))
        with self.assertRaises(ValueError):
            preview_assets.export(self.build, self.build / "refused", self.revision)
        self.assertFalse((self.build / "refused").exists())
        bad.write_bytes(saved)
        with self.assertRaises(ValueError):
            preview_assets.export(self.build, self.build / "wrong-source", "b" * 40)
        preview_assets.export(self.build, self.build / "accepted", self.revision)
        installer.write_bytes(b"tampered after qualification")
        with self.assertRaises(ValueError):
            preview_assets.export(self.build, self.build / "tampered", self.revision)


if __name__ == "__main__":
    unittest.main()
