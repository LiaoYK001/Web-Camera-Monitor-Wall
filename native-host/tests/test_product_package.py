#!/usr/bin/env python3
"""Payload contamination/tamper checks; fake binaries, no install qualification."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import product_package as package


class ProductPackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="webobs-package-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "runtime"
        self.root.mkdir()
        self.manifest = {"obsCommit": package.OBS_COMMIT, "version": "4.1.0-dev.test",
            "productIntegration": True, "publicationForbidden": True, "defaultProduct": False}
        (self.root / "webobs-native-prototype.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        for name in package.REQUIRED:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"synthetic fixture, not executable")
        files = [{"path": path.relative_to(self.root).as_posix(), "bytes": path.stat().st_size,
                  "sha256": package.digest(path)} for path in self.root.rglob("*") if path.is_file()]
        self.receipt = {"schema": 1, "kind": "native-product-integration-components", "obsCommit": package.OBS_COMMIT,
            "sourceRevision": "a" * 40, "version": self.manifest["version"], "publicationForbidden": True,
            "fullFeatureMigrationQualified": False, "files": files,
            "totalBytesBeforeReceipt": sum(entry["bytes"] for entry in files)}
        self.save_receipt()

    def save_receipt(self):
        (self.root / "product-components.json").write_text(json.dumps(self.receipt), encoding="utf-8")

    def test_all_files_are_verified_and_only_owned_paths_get_removed(self):
        payload = package.verify(self.root)
        self.assertEqual(payload["totalBytes"], sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file()))
        destination = self.root.parent / "owned-files.nsh"
        package.write_removals(payload, destination)
        text = destination.read_text(encoding="utf-8")
        self.assertIn('Delete "$INSTDIR\\bin\\webobs-wall.exe"', text)
        self.assertNotIn("RMDir /r", text)
        self.assertNotIn("LOCALAPPDATA", text)
        self.assertNotIn("*.*", text)

    def test_changed_and_missing_files_fail_before_packaging(self):
        target = self.root / "bin/webobsd.exe"
        target.write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            package.verify(self.root)
        target.unlink()
        with self.assertRaises(ValueError):
            package.verify(self.root)

    def test_installed_verification_counts_the_generated_uninstaller(self):
        (self.root / "Uninstall.exe").write_bytes(b"synthetic generated uninstaller")
        with self.assertRaises(ValueError):
            package.verify(self.root)
        payload = package.verify(self.root, installed=True)
        self.assertIn("Uninstall.exe", payload["files"])

    def test_unaccounted_configuration_or_user_file_is_never_silently_shipped(self):
        for name in ("config/account.json", "extra.txt"):
            target = self.root / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(b"private fixture only")
            with self.assertRaises(ValueError):
                package.verify(self.root)
            target.unlink()

    def test_unsafe_case_aliased_or_duplicate_paths_are_rejected(self):
        original = list(self.receipt["files"])
        for path in ("../outside", "bin/../outside", "bin/x$INSTDIR", 'bin/a"b', "C:/elsewhere",
                     "bin\\outside", "config/private.json", "BIN/WEBOBSD.EXE", "bin/webobsd.exe"):
            self.receipt["files"] = original + [{"path": path, "bytes": 0, "sha256": "a" * 64}]
            self.save_receipt()
            with self.subTest(path=path), self.assertRaises(ValueError):
                package.verify(self.root)

    def test_publication_or_complete_product_claim_is_rejected(self):
        for field, value in (("publicationForbidden", False), ("fullFeatureMigrationQualified", True),
                             ("version", "4.1.0"), ("obsCommit", "0" * 40)):
            old = self.receipt[field]
            self.receipt[field] = value
            self.save_receipt()
            with self.subTest(field=field), self.assertRaises(ValueError):
                package.verify(self.root)
            self.receipt[field] = old


if __name__ == "__main__":
    unittest.main()
