"""Linux-offline tiny fixtures; not installer or GitHub-origin qualification."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare-dev-prerelease.py"
spec = importlib.util.spec_from_file_location("prepare_dev_prerelease", SCRIPT)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
VERSION = "4.1.0-dev.18"
REVISION = "24e8eb371582c646c5e4c7059e070d37b4fdfcaa"


class DevPrereleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / "download"
        self.base = self.input / VERSION
        self.base.mkdir(parents=True)
        self.output = self.root / "prepared"
        self.names = validator.asset_names(VERSION)
        self.prefix = f"webobs-windows-{VERSION}"
        for name in self.names[:-1]:
            (self.base / name).write_bytes(b"tiny fixture\x00\xff\r\n")
        self.write_json("runtime-manifest.json", {
            "schema": 1, "platform": "windows-x64", "version": VERSION,
            "revision": REVISION, "milestone": "v4-M2-dev", "files": []})
        self.write_json("sbom.cdx.json", {
            "bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
            "metadata": {"component": {"type": "application", "name": "WebOBS", "version": VERSION},
                "properties": [{"name": "webobs:revision", "value": REVISION}]}, "components": []})
        self.write_json("dependencies.lock.json", {"schema": 1, "artifacts": []})
        self.write_json("footprint.json", {"version": VERSION, "files": 1})
        self.rechecksum()

    def path(self, suffix):
        return self.base / f"{self.prefix}-{suffix}"

    def write_json(self, suffix, value):
        self.path(suffix).write_text(json.dumps(value), encoding="utf-8")

    def change_json(self, suffix, update):
        value = json.loads(self.path(suffix).read_text())
        update(value)
        self.write_json(suffix, value)
        self.rechecksum()

    def rechecksum(self):
        self.lines = [f"{hashlib.sha256((self.base / name).read_bytes()).hexdigest()}  {name}"
            for name in self.names[:-1]]
        self.write_lines(self.lines)

    def write_lines(self, lines):
        self.path("SHA256SUMS.txt").write_bytes(("\n".join(lines) + "\n").encode("ascii"))

    def prepare(self, **changes):
        args = dict(version=VERSION, revision=REVISION, input_directory=self.input, output_directory=self.output)
        args.update(changes)
        return validator.prepare_dev_prerelease(**args)

    def rejects(self, **changes):
        with self.assertRaises(validator.VerificationError):
            self.prepare(**changes)
        self.assertFalse(self.output.exists())

    def test_success_copies_only_exact_eight_originals_and_bounded_private_receipt(self):
        (self.base / "windows-build-evidence.json").write_text('{"private":"not copied"}')
        (self.base / "unrelated-build.log").write_text("not copied")
        receipt = self.prepare()
        self.assertEqual({p.name for p in self.output.iterdir()}, set(self.names) | {validator.RECEIPT_NAME})
        for name in self.names:
            self.assertEqual((self.output / name).read_bytes(), (self.base / name).read_bytes())
        receipt_file = self.output / validator.RECEIPT_NAME
        self.assertLessEqual(receipt_file.stat().st_size, validator.MAX_RECEIPT_BYTES)
        self.assertEqual(json.loads(receipt_file.read_text()), receipt)
        self.assertEqual(len(receipt["assets"]), 8)
        self.assertFalse(receipt["github_source_verified"])
        self.assertFalse(receipt["publication_performed"])
        self.assertFalse(receipt["receipt_is_public_release_asset"])
        self.assertNotIn(str(self.root), receipt_file.read_text())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(receipt_file.stat().st_mode), 0o600)

    def test_windows_crlf_checksums_copied_unchanged(self):
        original = ("\r\n".join(self.lines) + "\r\n").encode("ascii")
        self.path("SHA256SUMS.txt").write_bytes(original)
        self.prepare()
        self.assertEqual((self.output / self.names[-1]).read_bytes(), original)

    def test_rejects_stable_latest_and_noncanonical_versions(self):
        for version in ("4.1.0", "latest", "Latest", "v4.1.0-dev.18", "4.1.0-dev.18-x", "4.1.0-dev.018", "04.1.0-dev.18", "4.1.0-dev.18\n"):
            with self.subTest(version=version):
                self.rejects(version=version)

    def test_rejects_short_invalid_revision(self):
        for revision in ("24e8eb3", "x" * 40, REVISION + "\n"):
            with self.subTest(revision=revision):
                self.rejects(revision=revision)

    def test_requested_version_and_source_mismatch(self):
        self.rejects(version="4.1.0-dev.19")
        self.rejects(revision="a" * 40)

    def test_runtime_identity_mismatches(self):
        original = json.loads(self.path("runtime-manifest.json").read_text())
        for key, value in (("version", "4.1.0"), ("revision", "f" * 40), ("platform", "linux-x64")):
            with self.subTest(key=key):
                self.write_json("runtime-manifest.json", {**original, key: value})
                self.rechecksum()
                self.rejects()

    def test_sbom_component_version_mismatch(self):
        self.change_json("sbom.cdx.json", lambda v: v["metadata"]["component"].update(version="4.1.0"))
        self.rejects()

    def test_sbom_revision_missing_wrong_or_duplicate(self):
        for properties in ([], [{"name": "webobs:revision", "value": "a" * 40}],
            [{"name": "webobs:revision", "value": REVISION}] * 2):
            with self.subTest(properties=properties):
                self.change_json("sbom.cdx.json", lambda v: v["metadata"].update(properties=properties))
                self.rejects()

    def test_sbom_missing_or_invalid_schema(self):
        for sbom in ({}, {"bomFormat": "other", "metadata": {}}, {"bomFormat": "CycloneDX", "metadata": []}):
            self.write_json("sbom.cdx.json", sbom)
            self.rechecksum()
            self.rejects()

    def test_forbids_pixeltest_metadata_in_all_json_assets(self):
        for suffix in ("runtime-manifest.json", "sbom.cdx.json", "dependencies.lock.json", "footprint.json"):
            for marker in ("PixelTest", "PIXEL_test", "pixel-test"):
                with self.subTest(suffix=suffix, marker=marker):
                    original = self.path(suffix).read_bytes()
                    self.change_json(suffix, lambda v: v.update(buildMarker=marker))
                    self.rejects()
                    self.path(suffix).write_bytes(original)
                    self.rechecksum()

    def test_rejects_traversal_slashes_backslash_and_latest_entries(self):
        for name in ("../payload.exe", "sub/payload.exe", "sub\\payload.exe", "/payload.exe", "C:payload.exe", "latest.yml", "Latest.yml"):
            with self.subTest(name=name):
                self.write_lines([self.lines[0].split("  ")[0] + "  " + name] + self.lines[1:])
                self.rejects()

    def test_extra_missing_duplicate_and_self_checksums(self):
        for lines in (self.lines + ["0" * 64 + "  extra.exe"], self.lines[:-1],
            self.lines + [self.lines[0]], self.lines + ["0" * 64 + "  " + self.names[-1]]):
            with self.subTest(lines=len(lines)):
                self.write_lines(lines)
                self.rejects()

    def test_rejects_noncanonical_checksum_records(self):
        for first in (self.lines[0].replace("  ", " *", 1), self.lines[0].replace("  ", " ", 1),
            self.lines[0].upper(), "", "# comment", "0" * 63 + "  " + self.names[0]):
            with self.subTest(first=first):
                self.write_lines([first] + self.lines[1:])
                self.rejects()

    def test_nonascii_and_oversize_checksums(self):
        for data in (b"\xff", b"x" * (validator.MAX_CHECKSUM_BYTES + 1)):
            self.path("SHA256SUMS.txt").write_bytes(data)
            self.rejects()

    def test_hash_corruption(self):
        (self.base / self.names[0]).write_bytes(b"corruption")
        self.rejects()

    def test_missing_asset(self):
        (self.base / self.names[0]).unlink()
        self.rejects()

    def test_duplicate_checksum_locations(self):
        other = self.input / "duplicate"
        other.mkdir()
        (other / self.names[-1]).write_bytes(self.path("SHA256SUMS.txt").read_bytes())
        self.rejects()

    def test_missing_checksum(self):
        self.path("SHA256SUMS.txt").unlink()
        self.rejects()

    def test_latest_in_selected_directory_not_even_if_unlisted(self):
        (self.base / "latest.yml").write_bytes(b"stable feed")
        self.rejects()

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symlinks")
    def test_asset_and_checksum_symlinks(self):
        for name in (self.names[0], self.names[-1]):
            with self.subTest(name=name):
                file = self.base / name
                original = file.read_bytes()
                outside = self.root / "target"
                outside.write_bytes(original)
                file.unlink()
                file.symlink_to(outside)
                self.rejects()
                file.unlink()
                file.write_bytes(original)

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symlinks")
    def test_search_directory_and_input_ancestor_symlinks(self):
        link = self.input / "linked"
        link.symlink_to(self.root, target_is_directory=True)
        self.rejects()
        link.unlink()
        link = self.root / "linked-input"
        link.symlink_to(self.input, target_is_directory=True)
        self.rejects(input_directory=link / VERSION)

    def test_reparse_attribute_detection_without_windows(self):
        self.assertTrue(validator._is_link_or_reparse(SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)))
        self.assertTrue(validator._is_link_or_reparse(SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFO")
    def test_nonregular_fifo_rejected_without_blocking(self):
        file = self.base / self.names[0]
        file.unlink()
        os.mkfifo(file)
        self.rejects()

    def test_existing_output_untouched(self):
        self.output.mkdir()
        sentinel = self.output / "sentinel"
        sentinel.write_bytes(b"keep")
        with self.assertRaises(validator.VerificationError):
            self.prepare()
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symlinks")
    def test_output_dangling_symlink_and_linked_parent_rejected(self):
        self.output.symlink_to(self.root / "missing")
        self.rejects()
        self.assertTrue(self.output.is_symlink())
        self.output.unlink()
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(self.root, target_is_directory=True)
        self.rejects(output_directory=linked_parent / "prepared")

    def test_overlapping_input_output_rejected(self):
        for output in (self.input, self.input / "nested", self.base / "new", self.root):
            with self.subTest(output=output):
                with self.assertRaises(validator.VerificationError):
                    self.prepare(output_directory=output)
        self.assertFalse((self.input / "nested").exists())

    def test_prunes_win_unpacked_tree_but_not_asset_wrappers(self):
        unpacked = self.base / "win-unpacked"
        unpacked.mkdir()
        # Not an asset root: neither this duplicate nor its untrusted children
        # are visited. The exact selected eight remain under self.base.
        (unpacked / self.names[-1]).write_bytes(b"not a candidate")
        if hasattr(os, "symlink"):
            (unpacked / "ignored-link").symlink_to(self.root)
        self.prepare()

    def test_search_entry_and_depth_limits_fail_closed(self):
        with patch.object(validator, "MAX_SCAN_ENTRIES", 1):
            self.rejects()
        with patch.object(validator, "MAX_SCAN_DEPTH", 0):
            self.rejects()

    def test_metadata_size_invalid_json_and_duplicate_keys(self):
        original = self.path("dependencies.lock.json").read_bytes()
        for data in (b"{", b"[]", b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff"):
            with self.subTest(data=data):
                self.path("dependencies.lock.json").write_bytes(data)
                self.rechecksum()
                self.rejects()
        self.path("dependencies.lock.json").write_bytes(original)
        self.rechecksum()
        with patch.object(validator, "MAX_JSON_BYTES", 10):
            self.rejects()

    def test_copy_corruption_is_detected_by_postcopy_verification(self):
        real_copy = validator._copy_asset
        def corrupt(source, target, expected):
            real_copy(source, target, expected)
            if target.name == self.names[0]:
                target.write_bytes(b"corrupt after copy")
        with patch.object(validator, "_copy_asset", side_effect=corrupt):
            with self.assertRaises(validator.VerificationError):
                self.prepare()
        self.assertFalse((self.output / validator.RECEIPT_NAME).exists())

    def test_mutation_after_input_verification_fails_copy_comparison(self):
        real_copy = validator._copy_asset
        def mutate(source, target, expected):
            if source.name == self.names[0]:
                source.write_bytes(b"changed before copy")
            real_copy(source, target, expected)
        with patch.object(validator, "_copy_asset", side_effect=mutate):
            with self.assertRaises(validator.VerificationError):
                self.prepare()
        self.assertFalse((self.output / validator.RECEIPT_NAME).exists())

    def test_cli_explicit_arguments_success_and_private_path_free_errors(self):
        command = [sys.executable, "-B", str(SCRIPT), "--version", VERSION, "--revision", REVISION,
            "--input", str(self.input), "--output", str(self.output)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(len(json.loads(result.stdout)["assets"]), 8)
        self.assertEqual(result.stderr, "")
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertNotIn(str(self.root), result.stderr)
        result = subprocess.run([sys.executable, "-B", str(SCRIPT)], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
