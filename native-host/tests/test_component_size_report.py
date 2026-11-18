#!/usr/bin/env python3
"""Offline contract for the candidate size split: grouping, bounds and rejection."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "native-host/scripts/component_size_report.py"
specification = importlib.util.spec_from_file_location("component_size_report", MODULE)
module = importlib.util.module_from_spec(specification)
sys.modules["component_size_report"] = module
specification.loader.exec_module(module)


def staged(files, **overrides):
    value = {"schema": 1, "version": "5.1.0-rc.16", "sourceRevision": "a" * 40,
             "candidate": True, "completeStaging": True,
             "files": [{"path": path, "bytes": size} for path, size in files]}
    value.update(overrides)
    return value


class GroupingTests(unittest.TestCase):
    def test_every_named_component_is_separate(self):
        paths = {
            module.component_for("bin/64bit/obs64.exe"): "OBS frontend and product plugin",
            module.component_for("bin/64bit/plugins/obs-ffmpeg.dll"): "OBS plugins shipped by the build",
            module.component_for("obs-plugins/64bit/webobs-native-host.dll"): "OBS plugin binaries",
            module.component_for("data/obs-studio/locale/en-US.ini"): "OBS data and assets",
            module.component_for("bin/64bit/Qt6Core.dll"): "Qt 6 runtime",
            module.component_for("bin/64bit/imageformats/qjpeg.dll"): "Qt plugins",
            module.component_for("bin/avcodec-62.dll"): "FFmpeg (libav* / sw*)",
            module.component_for("bin/64bit/avcodec-61.dll"): "FFmpeg (libav* / sw*)",
            module.component_for("bin/go2rtc.exe"): "go2rtc (binary + bundled UI)",
            module.component_for("go2rtc-www/index.html"): "go2rtc (binary + bundled UI)",
            module.component_for("bin/mediamtx.exe"): "MediaMTX gateway",
            module.component_for("bin/caddy.exe"): "Caddy LAN HTTPS proxy",
            module.component_for("bin/node.exe"): "Node runtime for services",
            module.component_for("python/Lib/site-packages/numpy/core.py"): "Embedded Python runtime",
            module.component_for("bin/webobsd.exe"): "Product control server and online source",
            module.component_for("bin/webobs-online-source.exe"): "Product control server and online source",
            module.component_for("services/nvr/nvr_service.py"): "Python product services",
            module.component_for("web/assets/index-abc.js"): "Web UI bundle (PWA)",
            module.component_for("bin/libcrypto-3-x64.dll"): "Support DLLs (OpenSSL, curl, sqlite, VC++)",
            module.component_for("licenses/go2rtc/LICENSE"): "Licenses and notices",
            module.component_for("run/whatever.txt"): "Other staged files",
        }
        for actual, expected in paths.items():
            self.assertEqual(actual, expected, actual)

    def test_totals_are_conserved_and_shares_sum(self):
        value = module.components(staged([("bin/64bit/obs64.exe", 10),
            ("bin/avcodec-62.dll", 20), ("bin/avformat-62.dll", 30),
            ("web/assets/x.js", 40)])["files"])
        self.assertEqual(sum(group["bytes"] for group in value), 100)
        self.assertEqual(sum(group["files"] for group in value), 4)
        self.assertAlmostEqual(sum(group["sharePercent"] for group in value), 100.0, places=1)
        self.assertEqual(value[0]["name"], "FFmpeg (libav* / sw*)")
        self.assertEqual(value[0]["bytes"], 50)

    def test_unbounded_or_missing_entries_are_refused(self):
        for files in ([{"path": "web/x.js"}], [{"bytes": 1}], [{"path": 1, "bytes": 2}],
                      [{"path": "web/x.js", "bytes": -1}]):
            with self.assertRaises(ValueError):
                module.components(files)


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, name, payload):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_report_requires_a_component_receipt_with_files(self):
        missing = self.root / "runtime/product-components.json"
        self.assertEqual(module.main(["--components", str(missing)]), 1)
        empty = self.write("runtime/product-components.json", staged([]))
        self.assertEqual(module.main(["--components", str(empty)]), 1)

    def test_installer_and_installed_tree_are_reported(self):
        components = self.write("runtime/product-components.json",
            staged([("bin/64bit/obs64.exe", 10), ("python/Lib/x.py", 20)]))
        nsis = self.write("native-product-nsis.json", {"setupBytes": 4096,
            "setupSha256": "b" * 64, "version": "5.1.0-rc.16", "sourceRevision": "a" * 40,
            "footprint": {"logicalBytes": 1000, "mainStreamAllocationBytes": 1024,
                          "fileCount": 3, "directoryCountIncludingRoot": 2,
                          "allocationUnitBytes": 4096}})
        self.assertEqual(module.main(["--components", str(components), "--nsis", str(nsis)]), 0)
        value = module.report(components, nsis)
        self.assertEqual(value["installer"]["bytes"], 4096)
        self.assertEqual(value["installedTree"]["logicalBytes"], 1000)
        self.assertEqual(value["stagedBytes"], 30)
        self.assertIs(value["candidate"], True)

    def test_nsis_receipt_without_footprint_is_refused(self):
        components = self.write("runtime/product-components.json", staged([("web/x.js", 1)]))
        nsis = self.write("native-nsis-no-footprint.json", {"setupBytes": 1})
        self.assertEqual(module.main(["--components", str(components), "--nsis", str(nsis)]), 1)

    def test_stock_obs_reference_compares_same_measurement_tool(self):
        components = self.write("runtime/product-components.json", staged([("bin/caddy.exe", 10)]))
        nsis = self.write("native-product-nsis.json", {"setupBytes": 4096, "setupSha256": "c" * 64,
            "footprint": {"logicalBytes": 958743324, "mainStreamAllocationBytes": 960000000,
                          "fileCount": 7000, "directoryCountIncludingRoot": 900,
                          "allocationUnitBytes": 4096}})
        reference = self.write("obs-reference.json", {"obsVersion": "32.1.2",
            "installerBytes": 157809480, "logicalBytes": 479371662})
        value = module.report(components, nsis, reference)
        self.assertEqual(value["stockObsReference"]["obsVersion"], "32.1.2")
        self.assertAlmostEqual(value["installedTree"]["versusStockObsPercent"], 200.0, places=1)

    def test_output_file_is_bounded_json(self):
        components = self.write("runtime/product-components.json", staged([("bin/caddy.exe", 10)]))
        out = self.root / "out/native-product-size-split.json"
        self.assertEqual(module.main(["--components", str(components), "--output", str(out)]), 0)
        value = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(value["components"][0]["name"], "Caddy LAN HTTPS proxy")
        self.assertEqual(value["stagedBytes"], 10)
        refuses_link = self.root / "out-link.json"
        refuses_link.symlink_to(out)
        self.assertEqual(module.main(["--components", str(components), "--output", str(refuses_link)]), 1)

    def test_symlink_receipt_is_refused(self):
        real = self.write("real.json", staged([("web/x.js", 1)]))
        link = self.root / "link.json"
        link.symlink_to(real)
        with self.assertRaises(ValueError):
            module.read_receipt(link)


if __name__ == "__main__":
    unittest.main()
