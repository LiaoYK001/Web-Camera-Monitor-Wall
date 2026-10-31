"""Contract tests for native-host/scripts/compare_runtime_sizes.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import compare_runtime_sizes  # noqa: E402


def write(root: Path, relative: str, payload: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


class CompareRuntimeSizesTests(unittest.TestCase):
    def test_classifies_and_groups_the_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prototype = Path(tmp) / "prototype"
            obs = Path(tmp) / "obs"
            write(prototype, "bin/64bit/obs64.exe", b"e" * 10)
            write(obs, "bin/64bit/obs64.exe", b"e" * 10)
            write(prototype, "obs-plugins/64bit/webobs-native-host.dll", b"w" * 3)
            write(obs, "bin/64bit/cef/cef.dll", b"c" * 100)
            write(obs, "data/obs-plugins/obs-browser/locale/en-US.ini", b"l" * 5)
            write(obs, "data/libobs/obs-browser/cef.pak", b"p" * 40)
            receipt = compare_runtime_sizes.compare(prototype, obs)
            self.assertEqual(receipt["kind"], "native-size-compare")
            self.assertEqual(receipt["prototype"], {"files": 2, "bytes": 13})
            self.assertEqual(receipt["obs"], {"files": 4, "bytes": 155})
            self.assertEqual(receipt["shared"], {"files": 1, "bytes": 10})
            self.assertEqual(receipt["prototypeOnly"], {"files": 1, "bytes": 3})
            self.assertEqual(receipt["obsOnly"], {"files": 3, "bytes": 145})
            groups = {entry["group"]: entry["bytes"] for entry in receipt["obsOnlyGroups"]}
            self.assertEqual(groups["bin/64bit"], 100)
            self.assertEqual(groups["data/obs-plugins"], 5)
            self.assertEqual(groups["data/libobs"], 40)
            self.assertEqual(receipt["largestObsOnly"][0]["path"], "bin/64bit/cef/cef.dll")
            self.assertGreater(receipt["sharedPercentOfObsBytes"], 0)

    def test_missing_tree_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                compare_runtime_sizes.compare(Path(tmp) / "missing", Path(tmp))

    def test_main_writes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prototype = Path(tmp) / "prototype"
            obs = Path(tmp) / "obs"
            write(prototype, "a.dll", b"a")
            write(obs, "a.dll", b"a")
            write(obs, "b.dll", b"bb")
            report = Path(tmp) / "out/compare.json"
            self.assertEqual(
                compare_runtime_sizes.main(
                    ["--prototype", str(prototype), "--obs", str(obs), "--report", str(report)]
                ),
                0,
            )
            receipt = json.loads(report.read_text())
            self.assertEqual(receipt["obsOnly"]["files"], 1)
            self.assertEqual(receipt["obsOnly"]["bytes"], 2)


if __name__ == "__main__":
    unittest.main()
