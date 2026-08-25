#!/usr/bin/env python3
"""Regression tests for the fail-closed native dependency lock."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "clients" / "dependencies.lock.json"
VERIFIER = ROOT / "clients" / "scripts" / "verify_dependency_lock.py"
SPEC = importlib.util.spec_from_file_location("dependency_lock", VERIFIER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DependencyLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = json.loads(LOCK.read_text(encoding="utf-8"))

    def write_lock(self, document: object) -> Path:
        temporary = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
        with temporary:
            json.dump(document, temporary)
        self.addCleanup(Path(temporary.name).unlink, missing_ok=True)
        return Path(temporary.name)

    def test_release_baseline_is_exact(self) -> None:
        artifacts = MODULE.verify_lock(LOCK)
        self.assertEqual(set(artifacts), set(MODULE.EXPECTED))
        self.assertEqual(artifacts["gstreamer-plugins-rs-source"]["version"], "0.15.3")
        self.assertIn("75e46c3a1b868e9a08fd688d091476b76a498df1",
                      artifacts["gstreamer-plugins-rs-source"]["url"])

    def test_missing_whep_source_is_rejected(self) -> None:
        altered = copy.deepcopy(self.document)
        altered["artifacts"] = [item for item in altered["artifacts"]
                                if item["id"] != "gstreamer-plugins-rs-source"]
        with self.assertRaises(SystemExit):
            MODULE.verify_lock(self.write_lock(altered))

    def test_mutable_or_credentialed_source_url_is_rejected(self) -> None:
        altered = copy.deepcopy(self.document)
        target = next(item for item in altered["artifacts"]
                      if item["id"] == "gstreamer-plugins-rs-source")
        target["url"] = "https://user:password@example.invalid/latest.tar.gz"
        with self.assertRaises(SystemExit):
            MODULE.verify_lock(self.write_lock(altered))

    def test_platform_requirement_fails_when_files_are_omitted(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VERIFIER), "--require-platform", "linux-x86_64"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("artifact set mismatch", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
