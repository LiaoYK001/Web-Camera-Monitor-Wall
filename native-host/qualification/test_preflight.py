#!/usr/bin/env python3
"""Contract tests for the target-machine P5 preflight (never a performance verdict)."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preflight  # noqa: E402

EXAMPLE = Path(__file__).resolve().parent / "metadata.example.json"
SYSTEM = {"os": "Windows 11", "osRelease": "11", "osBuild": "26100", "machine": "AMD64",
          "cpu": "Intel Core i9-13900HX", "logicalProcessors": 32, "memoryBytes": 32 * 1024 ** 3,
          "adapters": [{"name": "NVIDIA GeForce RTX 4090 Laptop GPU", "driverVersion": "1.2.3"}],
          "monitors": 1, "primaryWidth": 2560, "primaryHeight": 1600, "python": "3.12.0"}


class PreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.native = self.root / "native" / "obs64.exe"
        self.obs = self.root / "obs" / "obs64.exe"
        for path, payload in ((self.native, b"nat"), (self.obs, b"ref")):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        self.metadata = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        for key in self.metadata["declarations"]:
            self.metadata["declarations"][key] = True

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_metadata(self, value: dict) -> Path:
        path = self.root / "metadata.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_passes_contract_and_never_qualifies(self) -> None:
        output = self.root / "receipt"
        receipt = preflight.run(self.native, self.obs, self.write_metadata(self.metadata), output, 16, 1, False, SYSTEM)
        self.assertEqual("pass", receipt["status"])
        self.assertFalse(receipt["qualified"])
        self.assertTrue(receipt["coverageIncomplete"])
        self.assertFalse((output / "README.txt").exists())
        native = receipt["executables"]["native"]
        self.assertEqual(3, native["bytes"])
        self.assertNotEqual(native["sha256"], receipt["executables"]["obs"]["sha256"])

    def test_fails_when_hardware_expectations_are_not_met(self) -> None:
        system = dict(SYSTEM, monitors=0, memoryBytes=8 * 1024 ** 3)
        receipt = preflight.run(self.native, self.obs, self.write_metadata(self.metadata),
                                self.root / "receipt", 16, 2, False, system)
        self.assertEqual("fail", receipt["status"])
        self.assertEqual(["memory", "monitors"], [c["id"] for c in receipt["checks"] if not c["passed"]])

    def test_real_preflight_rejects_unconfirmed_declarations(self) -> None:
        path = Path(__file__).resolve().parent / "metadata.example.json"
        with self.assertRaises(ValueError):
            preflight.run(self.native, self.obs, path, self.root / "receipt", 16, 1, False, SYSTEM)

    def test_diagnostic_allows_placeholder_metadata(self) -> None:
        path = Path(__file__).resolve().parent / "metadata.example.json"
        receipt = preflight.run(self.native, self.obs, path, self.root / "receipt", 16, 1, True, SYSTEM)
        self.assertTrue(receipt["diagnostic"])
        self.assertFalse(receipt["qualified"])
        self.assertTrue((self.root / "receipt" / "README.txt").is_file())

    def test_rejects_identical_builds(self) -> None:
        receipt = preflight.run(self.native, self.native, self.write_metadata(self.metadata),
                                self.root / "receipt", 16, 1, False, SYSTEM)
        self.assertEqual("fail", receipt["status"])
        self.assertIn("distinct-builds", [c["id"] for c in receipt["checks"] if not c["passed"]])

    def test_rejects_existing_output_directory(self) -> None:
        output = self.root / "receipt"
        output.mkdir()
        with self.assertRaises(ValueError):
            preflight.run(self.native, self.obs, self.write_metadata(self.metadata), output, 16, 1, False, SYSTEM)

    def test_rejects_metadata_without_declarations(self) -> None:
        broken = json.loads(json.dumps(self.metadata))
        del broken["declarations"]["recordingOff"]
        with self.assertRaises(ValueError):
            preflight.run(self.native, self.obs, self.write_metadata(broken), self.root / "receipt", 16, 1, True, SYSTEM)


if __name__ == "__main__":
    unittest.main()
