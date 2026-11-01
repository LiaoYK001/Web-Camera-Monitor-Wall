"""Contract tests for native-host/scripts/runtime_inventory.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import runtime_inventory  # noqa: E402


def make_runtime(root: Path) -> Path:
    files = {
        "bin/64bit/obs64.exe": b"e" * 10,
        "bin/64bit/Qt6Core.dll": b"q" * 20,
        "bin/64bit/avcodec-61.dll": b"a" * 30,
        "bin/64bit/avdevice-61.dll": b"d" * 4,
        "bin/64bit/obs-ffmpeg-mux.exe": b"m" * 3,
        "bin/64bit/libx264-164.dll": b"x" * 5,
        "obs-plugins/64bit/obs-ffmpeg.dll": b"f" * 7,
        "data/obs-plugins/obs-filters/locale/en-US.ini": b"hello",
        "data/obs-plugins/obs-filters/locale/zh-CN.ini": b"nihao",
        "data/obs-studio/locale/de-DE.ini": b"hallo!",
        "licenses/OBS-COPYING.txt": b"gpl",
        "readme.md": b"docs",
    }
    for relative, payload in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    (root / "webobs-native-prototype.json").write_text(json.dumps({"version": "4.1.0-dev.99"}))
    return root


class RuntimeInventoryTests(unittest.TestCase):
    def test_groups_vendors_and_locales(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = make_runtime(Path(tmp))
            receipt = runtime_inventory.inventory(runtime)
            self.assertEqual(receipt["kind"], "native-runtime-inventory")
            self.assertEqual(receipt["version"], "4.1.0-dev.99")
            self.assertEqual(receipt["groups"]["qt"], 20)
            self.assertEqual(receipt["groups"]["plugins"], 7)
            self.assertEqual(receipt["groups"]["licenses"], 3)
            self.assertEqual(receipt["locales"]["files"], 3)
            self.assertEqual(receipt["locales"]["bytes"], 5 + 5 + 6)
            self.assertEqual(receipt["locales"]["languages"], ["de-DE.ini", "en-US.ini", "zh-CN.ini"])
            vendors = {c["path"]: c["vendor"] for c in receipt["components"]}
            self.assertEqual(vendors["bin/64bit/Qt6Core.dll"], "Qt")
            self.assertEqual(vendors["bin/64bit/avcodec-61.dll"], "FFmpeg")
            self.assertEqual(vendors["bin/64bit/libx264-164.dll"], "x264")
            self.assertEqual(vendors["bin/64bit/avdevice-61.dll"], "FFmpeg")
            self.assertEqual(vendors["bin/64bit/obs-ffmpeg-mux.exe"], "OBS Studio")
            self.assertEqual(vendors["obs-plugins/64bit/obs-ffmpeg.dll"], "OBS Studio")
            self.assertEqual(vendors["bin/64bit/obs64.exe"], "OBS Studio")
            hashes = {c["path"]: c["sha256"] for c in receipt["components"]}
            self.assertEqual(len(hashes["bin/64bit/obs64.exe"]), 64)

    def test_forbidden_build_product_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = make_runtime(Path(tmp))
            (runtime / "bin/64bit/obs64.pdb").write_bytes(b"pdb")
            with self.assertRaises(SystemExit):
                runtime_inventory.inventory(runtime)

    def test_budget_overflow_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = make_runtime(Path(tmp))
            with self.assertRaises(SystemExit):
                runtime_inventory.inventory(runtime, max_runtime_bytes=10)

    def test_main_writes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = make_runtime(Path(tmp) / "runtime")
            report = Path(tmp) / "out/inventory.json"
            self.assertEqual(
                runtime_inventory.main(["--runtime", str(runtime), "--report", str(report)]),
                0,
            )
            receipt = json.loads(report.read_text())
            self.assertTrue(receipt["withinBudget"])
            self.assertGreater(receipt["files"], 0)


if __name__ == "__main__":
    unittest.main()
