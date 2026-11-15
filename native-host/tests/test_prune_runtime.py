"""Contract tests for native-host/scripts/prune_runtime.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import prune_runtime  # noqa: E402


class PruneRuntimeTests(unittest.TestCase):
    def test_removes_only_pdb_and_reports_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "bin/64bit").mkdir(parents=True)
            (runtime / "obs-plugins/64bit").mkdir(parents=True)
            (runtime / "bin/64bit/obs64.exe").write_bytes(b"exe")
            (runtime / "bin/64bit/obs64.pdb").write_bytes(b"p" * 10)
            (runtime / "obs-plugins/64bit/plugin.PDB").write_bytes(b"q" * 5)
            (runtime / "readme.txt").write_text("keep")
            receipt = prune_runtime.prune(runtime)
            self.assertEqual(receipt["schema"], 1)
            self.assertEqual(receipt["kind"], "native-runtime-prune")
            self.assertEqual(receipt["removedFiles"], 2)
            self.assertEqual(receipt["removedBytes"], 15)
            self.assertEqual(receipt["remainingPdbFiles"], 0)
            self.assertTrue((runtime / "bin/64bit/obs64.exe").exists())
            self.assertTrue((runtime / "readme.txt").exists())
            self.assertFalse((runtime / "bin/64bit/obs64.pdb").exists())
            self.assertFalse((runtime / "obs-plugins/64bit/plugin.PDB").exists())
            self.assertEqual(
                [item["path"] for item in receipt["removed"]],
                ["bin/64bit/obs64.pdb", "obs-plugins/64bit/plugin.PDB"],
            )

    def test_missing_runtime_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                prune_runtime.prune(Path(tmp) / "missing")

    def test_main_writes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            (runtime / "a.pdb").write_bytes(b"x")
            report = Path(tmp) / "out/prune.json"
            self.assertEqual(
                prune_runtime.main(["--runtime", str(runtime), "--report", str(report)]),
                0,
            )
            receipt = json.loads(report.read_text())
            self.assertEqual(receipt["removedFiles"], 1)
            self.assertEqual(receipt["removedBytes"], 1)


if __name__ == "__main__":
    unittest.main()
