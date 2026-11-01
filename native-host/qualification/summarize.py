#!/usr/bin/env python3
"""Offline observed-tree CPU/memory paired report, never an OBS parity verdict."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import sys

from common import (SCHEMA, UNMEASURED, comparable_key, digest, metadata, new_private_directory,
                    read_json, stats, summarize_samples, write_json)


def timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Missing timezone-qualified collection timestamp")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Unqualified timestamp")
    return result


def load_run(directory: Path) -> dict:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Run directory must be an existing private regular directory")
    meta = metadata(read_json(directory / "metadata.json"))
    manifest = read_json(directory / "manifest.json")
    if manifest.get("schemaVersion") != SCHEMA or manifest.get("collector") != "windows-readonly-process-tree-v1":
        raise ValueError("Unknown raw receipt format")
    if manifest.get("qualified") is not False or manifest.get("coverageIncomplete") is not True or manifest.get("strictTotal") is not False:
        raise ValueError("Raw process polling must retain incomplete-coverage boundaries")
    if manifest.get("unmeasured") != UNMEASURED:
        raise ValueError("Do not merge unmeasured or incompatible GPU/picture metrics into process reports")
    if manifest.get("metadataSha256") != digest(directory / "metadata.json"):
        raise ValueError("Metadata receipt digest mismatch")
    raw = directory / "samples.jsonl"
    if raw.is_symlink() or not raw.is_file() or raw.stat().st_size > 512 * 1024 * 1024:
        raise ValueError("Raw receipt missing, unsafe or over 512 MiB")
    if digest(raw) != manifest.get("samplesSha256"):
        raise ValueError("Raw sample receipt digest mismatch")
    records = []; lines = 0
    with raw.open(encoding="utf-8") as stream:
        for line in stream:
            lines += 1
            if lines > 36002 or len(line) > 8 * 1024 * 1024:
                raise ValueError("Raw receipt safety limit exceeded")
            value = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite sample")))
            if value.get("phase") in ("baseline", "measure"):
                records.append(value)
            elif value.get("phase") != "warmup":
                raise ValueError("Unknown raw sample phase")
    root = manifest.get("rootIdentity")
    for sample in records:
        if not any(p["identity"] == root for p in sample["processes"]):
            raise ValueError("Root identity missing from raw sample")
    summary = summarize_samples(records, manifest["logicalProcessors"])
    if summary != manifest.get("summary"):
        raise ValueError("Stored summary differs from raw offline recomputation")
    start = timestamp(manifest["startedUtc"]); end = timestamp(manifest["endedUtc"])
    sample_start = timestamp(manifest["sampleStartUtc"]); sample_end = timestamp(manifest["sampleEndUtc"])
    if not start <= sample_start < sample_end <= end:
        raise ValueError("Collection timestamps inconsistent")
    reasons = []
    timing = manifest["timing"]
    if manifest["status"] != "complete": reasons.append("collectionIncomplete")
    if manifest.get("fixture") or meta["workload"] != "five-real-h265": reasons.append("notRealFiveCameraRun")
    if (timing["requestedWarmupSeconds"] < 180 or timing["actualWarmupSeconds"] < 180
            or timing["requestedDurationSeconds"] < 1200 or summary["durationSeconds"] < 1200):
        reasons.append("belowP5TimingMinimum")
    if not all(meta["declarations"].values()): reasons.append("manualComparabilityDeclarationsMissing")
    if summary["knownCoverageIssues"]: reasons.append("knownObservedCoverageGaps")
    if any(summary[key]["missingSamples"] for key in ("workingSetSumBytes", "privateCommitSumBytes")):
        reasons.append("memorySamplesUnavailable")
    for record in records:
        if (not isinstance(record.get("captureSpanSeconds"), (float, int))
                or record["captureSpanSeconds"] < 0 or not math.isfinite(record["captureSpanSeconds"])):
            raise ValueError("Invalid capture span")
    interval = timing["intervalSeconds"]
    if not isinstance(interval, (float, int)) or not .2 <= interval <= 60:
        raise ValueError("Invalid sampling interval")
    if any(b["elapsedSeconds"] - a["elapsedSeconds"] > interval * 2 for a, b in zip(records, records[1:])):
        reasons.append("sampleTimingGaps")
    if max(r["captureSpanSeconds"] for r in records) > interval * .2:
        reasons.append("captureSkewExceeds20PercentOfInterval")
    return {"metadata": meta, "manifest": manifest, "summary": summary,
            "start": start, "end": end, "sampleStart": sample_start, "sampleEnd": sample_end,
            "diagnosticRestrictions": sorted(set(reasons))}


def ratio(product, obs):
    return product / obs if obs is not None and obs > 0 and product is not None else None


def paired_report(runs: list[dict]) -> dict:
    if len(runs) < 6 or len(runs) % 2:
        raise ValueError("At least three complete paired runs are required")
    if len({r["metadata"]["runId"] for r in runs}) != len(runs):
        raise ValueError("Duplicate run IDs")
    if len({comparable_key(r["metadata"]) for r in runs}) != 1:
        raise ValueError("Campaign, anonymous five inputs and all settings IDs must match across every run")
    if len({r["manifest"]["logicalProcessors"] for r in runs}) != 1:
        raise ValueError("Machine normalization differs across runs")
    for timing_key in ("intervalSeconds", "requestedWarmupSeconds", "requestedDurationSeconds"):
        if len({r["manifest"]["timing"][timing_key] for r in runs}) != 1:
            raise ValueError("Sampling cadence or requested timing differs across runs")
    for side in ("obs", "product"):
        if len({r["manifest"]["rootExeSha256"] for r in runs if r["metadata"]["variant"] == side}) != 1:
            raise ValueError("Executable identity changed within a comparison variant")
    chronological = sorted(runs, key=lambda r: r["start"])
    if any(a["end"] > b["start"] for a, b in zip(chronological, chronological[1:])):
        raise ValueError("Paired collections overlap; run OBS and product alternately, not simultaneously")
    groups = {}
    for run in runs:
        meta = run["metadata"]
        groups.setdefault(meta["pairIndex"], []).append(run)
    if sorted(groups) != list(range(1, len(groups) + 1)) or len(groups) < 3:
        raise ValueError("Need at least three consecutive pairIndex values from 1")
    pairs = []; previous_first = None; expected_chronology = []
    for index, group in sorted(groups.items()):
        if len(group) != 2 or {r["metadata"]["variant"] for r in group} != {"obs", "product"}:
            raise ValueError("Each pair must contain exactly one OBS and one product run")
        if len({r["metadata"]["pairId"] for r in group}) != 1 or {r["metadata"]["position"] for r in group} != {1, 2}:
            raise ValueError("Pair identity or order metadata mismatch")
        ordered = sorted(group, key=lambda r: r["metadata"]["position"])
        expected_chronology.extend(r["metadata"]["runId"] for r in ordered)
        first = ordered[0]["metadata"]["variant"]
        if first == previous_first:
            raise ValueError("Alternate first variant across pairs: OBS/product, product/OBS, OBS/product")
        previous_first = first
        by_side = {r["metadata"]["variant"]: r for r in group}
        product = by_side["product"]["summary"]; obs = by_side["obs"]["summary"]
        cpu_ratios = {name: ratio(product["cpuNormalizedPercent"][name], obs["cpuNormalizedPercent"][name])
                      for name in ("mean", "timeWeightedMean", "median", "p95", "peak")}
        pairs.append({"pairIndex": index, "pairId": ordered[0]["metadata"]["pairId"],
                      "order": [r["metadata"]["variant"] for r in ordered],
                      "cpuObservedLowerBoundProductOverObs": cpu_ratios,
                      "workingSetMeanRatio": ratio(product["workingSetSumBytes"]["mean"], obs["workingSetSumBytes"]["mean"]),
                      "privateCommitMeanRatio": ratio(product["privateCommitSumBytes"]["mean"], obs["privateCommitSumBytes"]["mean"]),
                      "runIds": [r["metadata"]["runId"] for r in ordered]})
    if expected_chronology != [r["metadata"]["runId"] for r in chronological]:
        raise ValueError("Declared alternating sequence differs from actual collection chronology")
    if len({p["pairId"] for p in pairs}) != len(pairs):
        raise ValueError("Pair IDs must be distinct")
    results = []
    for run in chronological:
        results.append({"runId": run["metadata"]["runId"], "variant": run["metadata"]["variant"],
                        "pairIndex": run["metadata"]["pairIndex"], "startedUtc": run["manifest"]["startedUtc"],
                        "endedUtc": run["manifest"]["endedUtc"], "rootExeSha256": run["manifest"]["rootExeSha256"],
                        "rawSamplesSha256": run["manifest"]["samplesSha256"], "summary": run["summary"],
                        "diagnosticRestrictions": run["diagnosticRestrictions"]})
    medians = [p["cpuObservedLowerBoundProductOverObs"]["median"] for p in pairs]
    return {"schemaVersion": SCHEMA, "reportKind": "observed-process-paired-diagnostic", "qualified": False,
            "obsParity": None, "strictTotal": False, "coverageIncomplete": True,
            "pairCount": len(pairs), "anonymousConditions": {k: chronological[0]["metadata"][k]
                                                           for k in ("campaignId", "workload", "identities", "inputs")},
            "runs": results, "pairs": pairs,
            "pairedCpuMedianRatioDistribution": stats([v for v in medians if v is not None]),
            "unmeasured": UNMEASURED.copy(),
            "limitations": ["Polling can miss short-lived processes or ancestry; observed CPU is a lower bound, not all-owned-process strict total.",
                            "Conditions are anonymous operator declarations, not verified stream settings, picture quality, hardware decode or GPU identity.",
                            "Capture reads are sequential; raw capture span and monotonic intervals expose timing skew.",
                            "Working-set sums double-count shared pages; private commit is not resident physical memory.",
                            "Per-run percentiles and paired ratios are not confidence bounds; noisy differences need further runs.",
                            "No GPU/VRAM/power/latency/final pixels/hardware decode/thermal/frequency or external-owned-process measurement; no parity decision."]}


def render_text(report: dict) -> str:
    lines = ["P5 observed-tree CPU/memory diagnostic — NOT performance qualification", "",
             "All CPU percentages use the same machine logical-processor denominator.",
             "Polling coverage is incomplete; never interpret a ratio <= 1 as OBS parity.", ""]
    for run in report["runs"]:
        cpu = run["summary"]["cpuNormalizedPercent"]
        lines.append(f'{run["runId"]} ({run["variant"]}): mean={cpu["mean"]:.3f}% median={cpu["median"]:.3f}% p95={cpu["p95"]:.3f}% peak={cpu["peak"]:.3f}% observedCpuSeconds={cpu["observedCpuSeconds"]:.3f}')
        lines.append("  Restrictions: " + (", ".join(run["diagnosticRestrictions"]) or "none beyond universal polling/unmeasured limits"))
    lines += ["", *report["limitations"], "", "Raw receipt directories remain private; this output is NOT approved for publishing."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", required=True, help="Private collection directory; repeat at least six times")
    parser.add_argument("--output", type=Path, required=True, help="New private absolute directory OUTSIDE Git")
    args = parser.parse_args()
    report = paired_report([load_run(path) for path in args.run])
    output = new_private_directory(args.output)
    write_json(output / "paired-summary.json", report)
    with (output / "summary.txt").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(render_text(report))
    print("Private paired diagnostic saved. qualified=false, coverageIncomplete=true; no OBS parity verdict.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Paired diagnostic refused ({type(error).__name__}); no qualification generated.", file=sys.stderr)
        sys.exit(1)
