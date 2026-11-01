#!/usr/bin/env python3
"""Synthetic contract tests; no Windows hardware or five-camera performance claims."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from collect import Tree, parser
from common import (UNMEASURED, digest, metadata, new_private_directory, read_json,
                    stats, summarize_samples, write_json)
from summarize import load_run, paired_report

HERE = Path(__file__).resolve().parent
FILETIME = 100_000_000_000


def meta(index=1, position=1, variant="obs"):
    value = json.loads((HERE / "metadata.example.json").read_text())
    value.update({"runId": f"pair{index:02d}-{variant}", "pairId": f"pair{index:02d}",
                  "pairIndex": index, "position": position, "variant": variant})
    value["declarations"] = {k: True for k in value["declarations"]}
    return value


def process(pid=1, created=FILETIME-1, cpu=0, exited=False, parent=None):
    return {"identity": f"{pid}:{created}", "pid": pid, "createdFileTime": created,
            "cpuTime100ns": cpu, "exited": exited, "parentIdentity": parent,
            "workingSetBytes": None if exited else 100,
            "privateBytes": None if exited else 50, "exeName": "fixture.exe", "errors": []}


def sample(second, processes, phase="measure", events=None):
    return {"phase": phase, "elapsedSeconds": second,
            "fileTime": FILETIME + int(second * 10_000_000), "captureSpanSeconds": .001,
            "processes": processes, "events": events or []}


def raw_run(directory, index, position, variant, start):
    directory.mkdir()
    value = meta(index, position, variant)
    write_json(directory / "metadata.json", value)
    baseline = sample(180, [process(cpu=50_000_000)], "baseline")
    baseline["utc"] = (start + timedelta(seconds=180)).isoformat()
    measurements = [baseline]
    increment = 10_000_000 if variant == "obs" else 12_000_000
    for i in range(1, 241):
        row = sample(180 + i*5, [process(cpu=50_000_000 + i*increment)])
        row["utc"] = (start + timedelta(seconds=180+i*5)).isoformat()
        measurements.append(row)
    with (directory / "samples.jsonl").open("x") as stream:
        for row in measurements:
            stream.write(json.dumps(row) + "\n")
    summary = summarize_samples(measurements, 8)
    manifest = {"schemaVersion": 1, "collector": "windows-readonly-process-tree-v1", "qualified": False,
                "coverageIncomplete": True, "strictTotal": False, "unmeasured": UNMEASURED.copy(),
                "metadataSha256": digest(directory / "metadata.json"),
                "samplesSha256": digest(directory / "samples.jsonl"), "rootIdentity": process()["identity"],
                "rootExeSha256": ("a" if variant == "obs" else "b") * 64,
                "logicalProcessors": 8, "summary": summary, "status": "complete", "fixture": False,
                "startedUtc": start.isoformat(), "endedUtc": (start + timedelta(seconds=1381)).isoformat(),
                "sampleStartUtc": baseline["utc"], "sampleEndUtc": measurements[-1]["utc"],
                "timing": {"requestedWarmupSeconds": 180, "actualWarmupSeconds": 180,
                           "requestedDurationSeconds": 1200, "intervalSeconds": 5}}
    write_json(directory / "manifest.json", manifest)
    return load_run(directory)


class FakeProcess:
    def __init__(self, pid, parent_pid, name, parent_identity, created, cpu=0):
        self.pid = pid; self.parent_pid = parent_pid; self.name = name
        self.parent_identity = parent_identity; self.created = created
        self.cpu = cpu; self.exited = False; self.exit_time = 0; self.closed = False
        self.identity = f"{pid}:{created}"
    def observe(self):
        return process(self.pid, self.created, self.cpu, self.exited, self.parent_identity)
    def close(self):
        self.closed = True


class QualificationTests(unittest.TestCase):
    def test_metadata_rejects_secrets_and_requires_explicit_contract(self):
        self.assertEqual(metadata(meta())["variant"], "obs")
        for mutate in (lambda m: m.update({"url": "rtsp://private"}),
                       lambda m: m["identities"].update({"canvas": "rtsp://private"}),
                       lambda m: m["inputs"][0].update({"settingsId": "C:\\private"}),
                       lambda m: m["inputs"][1].update({"sourceId": "camera-01"}),
                       lambda m: m["declarations"].update({"sameQuality": "true"})):
            value = meta(); mutate(value)
            with self.assertRaises(ValueError): metadata(value)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicates.json"
            path.write_text('{"a":1,"a":2}')
            with self.assertRaises(ValueError): read_json(path)
        defaults = parser().parse_args(["--pid", "1", "--exe", "C:/fixture.exe", "--metadata", "m.json", "--output", "o"])
        self.assertEqual((defaults.warmup, defaults.duration, defaults.interval, defaults.fixture), (180,1200,5,False))

    def test_private_output_refuses_repository_existing_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private = new_private_directory(root / "private")
            self.assertTrue(private.is_dir())
            with self.assertRaises(ValueError): new_private_directory(private)
            repo = root / "repo"; repo.mkdir(); (repo / ".git").mkdir()
            with self.assertRaises(ValueError): new_private_directory(repo / "ignored-build")
            link = root / "alias"
            try: link.symlink_to(private, target_is_directory=True)
            except OSError: pass
            else:
                with self.assertRaises(ValueError): new_private_directory(link / "new")

    def test_cpu_normalization_exit_tail_and_new_child_lifetime(self):
        parent = process(cpu=100_000_000)
        child_start = FILETIME + 10_000_000
        first = sample(0, [parent], "baseline")
        second = sample(5, [process(cpu=120_000_000), process(2, child_start, 5_000_000)])
        final = sample(10, [process(cpu=130_000_000), process(2, child_start, 10_000_000, exited=True)])
        result = summarize_samples([first, second, final], 2)
        # 2.5 / (5*2) = 25%, then 1.5 / (5*2) = 15%; no lifetime double-count.
        self.assertEqual(result["cpuNormalizedPercent"]["mean"], 20)
        self.assertEqual(result["cpuNormalizedPercent"]["median"], 20)
        self.assertEqual(result["cpuNormalizedPercent"]["p95"], 25)
        self.assertEqual(result["cpuNormalizedPercent"]["observedCpuSeconds"], 4)
        self.assertEqual(result["measurementAppearances"], 1)
        self.assertEqual(result["measurementExits"], 1)
        self.assertTrue(result["coverageIncomplete"])
        self.assertFalse(result["strictTotal"])
        self.assertEqual(result["unmeasured"]["gpuByAdapterEngine"], None)
        self.assertEqual(result["workingSetSumBytes"]["endMinusStartBytes"], -100)

    def test_cpu_missing_tail_and_pid_reuse_are_not_zero_or_same_process(self):
        first = sample(0, [process(1, FILETIME-1, 5_000_000)], "baseline")
        second = sample(5, [process(1, FILETIME-1, None, True), process(1, FILETIME+1, 2_000_000)])
        result = summarize_samples([first, second], 2)
        self.assertIn("exitedProcessFinalCpuUnavailable", result["knownCoverageIssues"])
        self.assertEqual(result["observedProcessCount"], 2)
        self.assertAlmostEqual(result["cpuNormalizedPercent"]["mean"], 2)
        with self.assertRaises(ValueError):
            summarize_samples([first, sample(5, [process(1, FILETIME-1, 1)])], 2)
        with self.assertRaises(ValueError):
            summarize_samples([first, sample(5, [process(), process()])], 2)

    def test_tree_retains_exit_handles_and_rejects_reused_parent_pid(self):
        root = FakeProcess(1, 0, "root.exe", None, FILETIME)
        rows = [{"pid": 2, "parentPid": 1, "exeName": "child.exe"},
                {"pid": 3, "parentPid": 2, "exeName": "grandchild.exe"}]
        created = {2: FILETIME+1, 3: FILETIME+2, 4: FILETIME-1}
        factories = []
        def factory(pid, parent, name, ident):
            value = FakeProcess(pid, parent, name, ident, created[pid]); factories.append(value); return value
        tree = Tree(root, factory, lambda: rows)
        raw, events = tree.capture()
        self.assertEqual(len(raw), 3)
        child = tree.current[2]; child.exited = True; child.exit_time = FILETIME+10; child.cpu = 90
        created[2] = FILETIME+20
        rows.append({"pid": 4, "parentPid": 2, "exeName": "unrelated.exe"})
        raw, events = tree.capture()
        self.assertEqual(len(tree.owned), 4)  # original child remains alongside reused PID identity
        self.assertTrue(any(p["exited"] and p["cpuTime100ns"] == 90 for p in raw))
        self.assertIn("pidReuseObserved", [e["kind"] for e in events])
        self.assertIn("parentPidReuseOrCreationAmbiguous", [e["kind"] for e in events])
        tree.close()
        self.assertTrue(all(p.closed for p in [root, *factories]))

    def six_runs(self, root):
        start = datetime(2026,1,1,tzinfo=timezone.utc)
        runs = []
        for index in range(1,4):
            variants = ("obs", "product") if index % 2 else ("product", "obs")
            for position, variant in enumerate(variants,1):
                runs.append(raw_run(root / f"run{len(runs)}", index, position, variant,
                                    start + timedelta(seconds=1500*len(runs))))
        return runs

    def test_offline_recomputes_raw_and_pairs_alternating_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); runs = self.six_runs(root)
            report = paired_report(list(reversed(runs)))
            self.assertEqual(report["pairCount"], 3)
            self.assertFalse(report["qualified"])
            self.assertIsNone(report["obsParity"])
            self.assertEqual(report["pairs"][0]["cpuObservedLowerBoundProductOverObs"]["median"], 1.2)
            self.assertEqual(report["runs"][0]["diagnosticRestrictions"], [])
            self.assertEqual(set(report["unmeasured"].values()), {None})
            with (root / "run0" / "samples.jsonl").open("a") as stream: stream.write("{}\n")
            with self.assertRaises(ValueError): load_run(root / "run0")

    def test_pairs_reject_mismatch_bad_order_overlap_or_insufficient_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = self.six_runs(Path(tmp))
            mutations = [lambda r: r.pop(),
                         lambda r: r[0]["metadata"]["identities"].update({"decode": "other"}),
                         lambda r: r[2]["metadata"].update({"position": 2}),
                         lambda r: r[3].update({"start": r[2]["start"]}),
                         lambda r: r[2]["manifest"].update({"logicalProcessors": 16}),
                         lambda r: r[0]["manifest"].update({"rootExeSha256": "c"*64}),
                         lambda r: r[0]["metadata"].update({"runId": r[1]["metadata"]["runId"]})]
            for mutate in mutations:
                changed = deepcopy(runs); mutate(changed)
                with self.assertRaises(ValueError): paired_report(changed)

    def test_fixture_never_qualified_and_stored_summary_cannot_override_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.six_runs(root)
            path = root / "run0" / "manifest.json"; value = read_json(path)
            value["fixture"] = True
            value["timing"]["requestedDurationSeconds"] = 10
            path.write_text(json.dumps(value))
            run = load_run(root / "run0")
            self.assertIn("notRealFiveCameraRun", run["diagnosticRestrictions"])
            self.assertIn("belowP5TimingMinimum", run["diagnosticRestrictions"])
            value["summary"]["cpuNormalizedPercent"]["mean"] = 0
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError): load_run(root / "run0")

    def test_stats_nearest_rank_and_not_sum_of_role_percentiles(self):
        self.assertEqual(stats([0,1,2,3])["median"], 1.5)
        self.assertEqual(stats(list(range(100)))["p95"], 94)
        self.assertIsNone(stats([])["mean"])
        with self.assertRaises(ValueError): stats([float("nan")])


if __name__ == "__main__":
    unittest.main()
