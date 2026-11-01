#!/usr/bin/env python3
"""Contract tests for the P5 campaign plan generator (never a performance verdict)."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import plan  # noqa: E402
import preflight  # noqa: E402

EXAMPLE = Path(__file__).resolve().parent / "metadata.example.json"
SYSTEM = {"os": "Windows 11", "cpu": "Intel Core i9-13900HX", "memoryBytes": 32 * 1024 ** 3,
          "adapters": [{"name": "NVIDIA GeForce RTX 4090 Laptop GPU", "driverVersion": "1.2.3"}],
          "monitors": 1, "primaryWidth": 2560, "primaryHeight": 1600}


class PlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.template = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.template.update({"runId": "runpair01product", "pairId": "pair01", "pairIndex": 1,
                              "position": 1, "variant": "product"})
        for key in self.template["declarations"]:
            self.template["declarations"][key] = True
        self.template_path = self.root / "template.json"
        self.template_path.write_text(json.dumps(self.template), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_expands_three_alternating_pairs(self) -> None:
        output = self.root / "plan"
        value = plan.build(self.template_path, output)
        self.assertEqual(6, len(value["runs"]))
        self.assertEqual(["product", "obs"] * 3, [run["variant"] for run in value["runs"]])
        self.assertEqual([1, 1, 2, 2, 3, 3], [run["pairIndex"] for run in value["runs"]])
        names = {run["metadataFile"] for run in value["runs"]}
        self.assertEqual(6, len(names))
        for run in value["runs"]:
            generated = json.loads((output / run["metadataFile"]).read_text(encoding="utf-8"))
            self.assertEqual(run["runId"], common.metadata(generated)["runId"])
        self.assertFalse(value["qualified"])
        self.assertTrue((output / "README.txt").is_file())

    def test_rejects_anon_template_that_is_not_pair_one_product(self) -> None:
        template = dict(self.template, variant="obs", position=2)
        self.template_path.write_text(json.dumps(template), encoding="utf-8")
        with self.assertRaises(ValueError):
            plan.build(self.template_path, self.root / "plan")

    def test_rejects_template_with_unconfirmed_declarations(self) -> None:
        template = json.loads(json.dumps(self.template))
        template["declarations"]["recordingOff"] = False
        self.template_path.write_text(json.dumps(template), encoding="utf-8")
        with self.assertRaises(ValueError):
            plan.build(self.template_path, self.root / "plan")

    def test_binds_only_a_passing_non_diagnostic_preflight(self) -> None:
        native = self.root / "native" / "obs64.exe"
        obs = self.root / "obs" / "obs64.exe"
        for path, payload in ((native, b"n"), (obs, b"o")):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        receipt = preflight.run(native, obs, self.template_path, self.root / "preflight", 16, 1, False, SYSTEM)
        self.assertFalse(receipt["qualified"])
        value = plan.build(self.template_path, self.root / "plan", self.root / "preflight" / "preflight.json")
        self.assertIsNotNone(value["preflight"])
        diagnostic = preflight.run(native, obs, self.template_path, self.root / "preflight-diag", 16, 1, True, SYSTEM)
        self.assertFalse(diagnostic["qualified"])
        with self.assertRaises(ValueError):
            plan.build(self.template_path, self.root / "plan2", self.root / "preflight-diag" / "preflight.json")

    def test_rejects_existing_output_directory(self) -> None:
        output = self.root / "plan"
        output.mkdir()
        with self.assertRaises(ValueError):
            plan.build(self.template_path, output)

    def test_rejects_too_long_campaign_id(self) -> None:
        self.template["campaignId"] = "c" * 60
        self.template_path.write_text(json.dumps(self.template), encoding="utf-8")
        with self.assertRaises(ValueError):
            plan.build(self.template_path, self.root / "plan")


if __name__ == "__main__":
    unittest.main()
