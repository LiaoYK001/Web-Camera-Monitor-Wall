#!/usr/bin/env python3
"""Tests for the fail-closed local release receipt verifier."""

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify-local-gate-receipts.py"
SPEC = importlib.util.spec_from_file_location("gate_receipts", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class LocalGateReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    def write_receipts(self, directory: Path, *, revision: str | None = None,
                       completed_at: datetime | None = None) -> None:
        timestamp = (completed_at or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
        for platform in MODULE.PLATFORMS:
            (directory / f"{platform}.json").write_text(json.dumps({
                "contract": MODULE.CONTRACT,
                "platform": platform,
                "revision": revision or self.revision,
                "completedAt": timestamp,
                "checks": sorted(MODULE.EXPECTED_CHECKS[platform]),
            }), encoding="utf-8")

    def run_verifier(self, directory: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--evidence-dir", str(directory)],
            cwd=ROOT, capture_output=True, text=True,
        )

    def test_accepts_two_current_exact_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.write_receipts(directory)
            self.assertEqual(self.run_verifier(directory).returncode, 0)

    def test_rejects_different_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.write_receipts(directory, revision="0" * 40)
            self.assertNotEqual(self.run_verifier(directory).returncode, 0)

    def test_rejects_stale_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.write_receipts(directory, completed_at=datetime.now(timezone.utc) - timedelta(hours=49))
            self.assertNotEqual(self.run_verifier(directory).returncode, 0)

    def test_rejects_missing_required_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.write_receipts(directory)
            path = directory / "windows.json"
            receipt = json.loads(path.read_text(encoding="utf-8"))
            receipt["checks"].pop()
            path.write_text(json.dumps(receipt), encoding="utf-8")
            self.assertNotEqual(self.run_verifier(directory).returncode, 0)


if __name__ == "__main__":
    unittest.main()
