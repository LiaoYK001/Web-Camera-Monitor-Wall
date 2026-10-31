#!/usr/bin/env python3
"""Local contracts for the private prototype installer; no Windows required."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import install_native  # noqa: E402


def bundle(path: Path, version: str = "4.1.0-dev.1", *, extra: dict[str, bytes] | None = None,
           manifest: dict | None = None) -> Path:
    payload = {"schema": 1, "version": version, "defaultProduct": False, "servicesStarted": []}
    payload.update(manifest or {})
    entries = {
        "webobs-native-prototype.json": json.dumps(payload).encode(),
        "launch-native.ps1": b"# launcher\n",
        "bin/64bit/obs64.exe": b"MZ",
        "README.md": b"readme\n",
    }
    entries.update(extra or {})
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def install(self, package: Path, name: str = "runtime", receipt: str | None = "receipt.json") -> dict:
        target = self.root / name
        return install_native.install(package, target, self.root / receipt if receipt else None)

    def test_fresh_install_writes_bounded_receipt(self) -> None:
        package = bundle(self.root / "bundle.zip")
        payload = self.install(package)
        runtime = self.root / "runtime"
        self.assertEqual(payload["version"], "4.1.0-dev.1")
        self.assertFalse(payload["configPreserved"])
        self.assertIsNone(payload["previousVersion"])
        self.assertEqual(payload["packageSha256"], hashlib.sha256(package.read_bytes()).hexdigest())
        self.assertTrue((runtime / "launch-native.ps1").is_file())
        self.assertTrue((runtime / "bin/64bit/obs64.exe").is_file())
        receipt = json.loads((self.root / "receipt.json").read_text())
        self.assertEqual(receipt, payload)

    def test_reinstall_preserves_portable_profile(self) -> None:
        package = bundle(self.root / "one.zip", "4.1.0-dev.1")
        self.install(package)
        profile = self.root / "runtime/config/obs-studio/basic"
        profile.mkdir(parents=True)
        (profile / "scenes.json").write_text('{"saved":true}')
        shutil.copyfile(self.root / "one.zip", self.root / "two.zip")
        payload = self.install(bundle(self.root / "two.zip", "4.1.0-dev.2"), receipt="second.json")
        self.assertTrue(payload["configPreserved"])
        self.assertEqual(payload["previousVersion"], "4.1.0-dev.1")
        self.assertEqual(payload["version"], "4.1.0-dev.2")
        self.assertEqual((self.root / "runtime/config/obs-studio/basic/scenes.json").read_text(), '{"saved":true}')

    def test_archive_may_not_ship_a_configured_profile(self) -> None:
        package = bundle(self.root / "bad.zip", extra={"config/obs-studio/global.ini": b"[x]"})
        with self.assertRaises(install_native.InstallError) as caught:
            self.install(package)
        self.assertEqual(str(caught.exception), "bundle-contains-config")
        self.assertFalse((self.root / "runtime").exists())

    def test_unsafe_entries_are_rejected(self) -> None:
        for name in ("../evil.txt", "/absolute.txt", "bin/../../evil.txt"):
            package = bundle(self.root / "bad.zip", extra={name: b"x"})
            with self.assertRaises(install_native.InstallError) as caught:
                self.install(package)
            self.assertEqual(str(caught.exception), "bundle-path-unsafe", name)

    def test_incomplete_archive_is_rejected(self) -> None:
        package = self.root / "bad.zip"
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("webobs-native-prototype.json", json.dumps(
                {"version": "4.1.0-dev.1", "defaultProduct": False, "servicesStarted": []}).encode())
        with self.assertRaises(install_native.InstallError) as caught:
            self.install(package)
        self.assertEqual(str(caught.exception), "bundle-incomplete")

    def test_manifest_must_be_development_only(self) -> None:
        for manifest, code in (({"version": "4.1.0"}, "bundle-manifest-invalid"),
                               ({"defaultProduct": True}, "bundle-manifest-invalid"),
                               ({"servicesStarted": ["caddy"]}, "bundle-manifest-invalid")):
            package = bundle(self.root / "bad.zip", manifest=manifest)
            with self.assertRaises(install_native.InstallError) as caught:
                self.install(package)
            self.assertEqual(str(caught.exception), code)

    def test_refuses_to_replace_an_unrelated_directory(self) -> None:
        target = self.root / "runtime"
        target.mkdir()
        marker = target / "keep.txt"
        marker.write_text("do not delete")
        with self.assertRaises(install_native.InstallError) as caught:
            self.install(bundle(self.root / "bundle.zip"))
        self.assertEqual(str(caught.exception), "install-root-not-bundle")
        self.assertEqual(marker.read_text(), "do not delete")

    def test_failed_swap_restores_the_previous_install(self) -> None:
        self.install(bundle(self.root / "one.zip", "4.1.0-dev.1"))
        original = install_native.shutil.move
        calls = {"count": 0}

        def flaky(source, destination):
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("simulated swap failure")
            return original(source, destination)

        install_native.shutil.move = flaky
        try:
            with self.assertRaises(OSError):
                self.install(bundle(self.root / "two.zip", "4.1.0-dev.2"))
        finally:
            install_native.shutil.move = original
        manifest = json.loads((self.root / "runtime/webobs-native-prototype.json").read_text())
        self.assertEqual(manifest["version"], "4.1.0-dev.1")
        leftovers = [path.name for path in self.root.iterdir() if ".staging-" in path.name or ".backup-" in path.name]
        self.assertEqual(leftovers, [])

    def test_uninstall_requires_a_bundle_and_removes_it(self) -> None:
        with self.assertRaises(install_native.InstallError):
            install_native.uninstall(self.root / "missing", None)
        self.install(bundle(self.root / "bundle.zip"))
        payload = install_native.uninstall(self.root / "runtime", self.root / "removed.json")
        self.assertEqual(payload["action"], "uninstall")
        self.assertFalse((self.root / "runtime").exists())
        self.assertTrue((self.root / "removed.json").is_file())

    def test_cli_reports_fixed_failure_code(self) -> None:
        self.assertEqual(install_native.main(["--install-root", str(self.root / "runtime")]), 2)


if __name__ == "__main__":
    unittest.main()
