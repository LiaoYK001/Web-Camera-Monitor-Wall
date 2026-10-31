"""Private, dependency-free P5 receipt contracts; no performance qualification."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any

SCHEMA = 1
SLUG = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}\Z")
IDENTITIES = ("machine", "os", "driver", "power", "thermal", "display", "adapter",
              "canvas", "view", "decode", "audio", "extras", "fixturePlacement")
DECLARATIONS = ("fiveSourcesVisible", "sameQuality", "recordingOff", "streamingOff",
                "detectionOff", "otherVariantStopped", "ownedScopeReviewed")
UNMEASURED = dict.fromkeys(("gpuByAdapterEngine", "vram", "power", "latency", "picture",
                            "hardwareDecode", "temperature", "frequency", "ownedExternalProcesses"))


def exact_keys(obj: Any, keys: set[str], context: str) -> None:
    if not isinstance(obj, dict) or set(obj) != keys:
        raise ValueError(f"Invalid {context} fields")


def slug(value: Any) -> bool:
    return isinstance(value, str) and SLUG.fullmatch(value) is not None


def metadata(value: Any) -> dict:
    exact_keys(value, {"schemaVersion", "campaignId", "runId", "pairId", "pairIndex",
                       "position", "variant", "workload", "identities", "inputs", "declarations"}, "metadata")
    if value["schemaVersion"] != SCHEMA or any(not slug(value[k]) for k in ("campaignId", "runId", "pairId")):
        raise ValueError("Invalid metadata identity")
    if (type(value["pairIndex"]) is not int or value["pairIndex"] < 1
            or type(value["position"]) is not int or value["position"] not in (1, 2)):
        raise ValueError("Invalid pair position")
    if value["variant"] not in ("obs", "product") or value["workload"] not in ("five-real-h265", "fixture", "other"):
        raise ValueError("Invalid workload or variant")
    exact_keys(value["identities"], set(IDENTITIES), "settings identities")
    if not all(slug(v) for v in value["identities"].values()):
        raise ValueError("Use opaque settings IDs, not paths, URLs or free text")
    inputs = value["inputs"]
    if not isinstance(inputs, list) or len(inputs) != 5:
        raise ValueError("Exactly five anonymous input identities required")
    for item in inputs:
        exact_keys(item, {"sourceId", "settingsId", "codec"}, "input")
        if not slug(item["sourceId"]) or not slug(item["settingsId"]) or item["codec"] not in ("h265", "h264", "other"):
            raise ValueError("Invalid anonymous input identity")
    if len({i["sourceId"] for i in inputs}) != 5:
        raise ValueError("Input identities must be distinct")
    if value["workload"] == "five-real-h265" and any(i["codec"] != "h265" for i in inputs):
        raise ValueError("Real H.265 workload requires five H.265 declarations")
    exact_keys(value["declarations"], set(DECLARATIONS), "manual declarations")
    if any(type(v) is not bool for v in value["declarations"].values()):
        raise ValueError("Declarations must be explicit booleans")
    return value


def read_json(path: Path, maximum: int = 1024 * 1024) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("Unsafe or oversized JSON receipt")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON value")))


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def new_private_directory(path: Path) -> Path:
    """Require a new absolute path with existing nonsymlink parent, outside every Git tree."""
    if not path.is_absolute() or path.exists() or path.is_symlink() or not path.parent.is_dir():
        raise ValueError("Output must be a new absolute directory under an existing private parent")
    for ancestor in (path.parent, *path.parent.parents):
        info = ancestor.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Output ancestors must not be links or reparse points")
        if (ancestor / ".git").exists():
            raise ValueError("Private output must be outside Git repositories, including ignored build directories")
    if os.name == "nt":
        from win32 import create_private_directory
        create_private_directory(path)
    else:
        path.mkdir(mode=0o700)
    return path


def stats(values: list[float]) -> dict:
    if not values:
        return dict.fromkeys(("mean", "median", "p95", "peak"))
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("Invalid metric values")
    ordered = sorted(values)
    n = len(values)
    mid = n // 2
    return {"mean": sum(values) / n,
            "median": ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2,
            "p95": ordered[math.ceil(.95 * n) - 1], "peak": ordered[-1]}


def comparable_key(meta: dict) -> str:
    return json.dumps({k: meta[k] for k in ("campaignId", "workload", "identities", "inputs")}, sort_keys=True)


def summarize_samples(samples: list[dict], logical_processors: int) -> dict:
    """Observed-tree lower-bound deltas, never sum independent process percentiles."""
    if type(logical_processors) is not int or logical_processors < 1:
        raise ValueError("Invalid logical processor count")
    if len(samples) < 2 or samples[0]["phase"] != "baseline":
        raise ValueError("Missing measurement baseline")
    prior = samples[0]
    previous = {}
    process_ids = set()
    issues = set()
    appearances = exits = 0
    cpu = []; working = []; private = []
    cpu_seconds = elapsed_total = 0.0
    for index, sample in enumerate(samples):
        if sample["phase"] not in (("baseline",) if index == 0 else ("measure",)):
            raise ValueError("Invalid sample phase")
        now = sample["elapsedSeconds"]
        if not isinstance(now, (int, float)) or not math.isfinite(now) or now < 0:
            raise ValueError("Invalid monotonic sample time")
        if index and now <= prior["elapsedSeconds"]:
            raise ValueError("Nonincreasing sample timestamps")
        if type(sample["fileTime"]) is not int or sample["fileTime"] < 1:
            raise ValueError("Invalid sample wall clock")
        seen = set(); current = {}; delta = 0
        ws = pb = 0; ws_missing = pb_missing = False
        for process in sample["processes"]:
            ident = process["identity"]
            if ident in seen or not re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", ident):
                raise ValueError("Duplicate or invalid PID/creation identity")
            seen.add(ident); process_ids.add(ident)
            if ident != f'{process["pid"]}:{process["createdFileTime"]}':
                raise ValueError("PID reuse guard mismatch")
            counter = process["cpuTime100ns"]
            if counter is not None and (type(counter) is not int or counter < 0):
                raise ValueError("Invalid cumulative CPU counter")
            if not process["exited"]:
                for field in ("workingSetBytes", "privateBytes"):
                    number = process[field]
                    if number is not None and (type(number) is not int or number < 0):
                        raise ValueError("Invalid memory counter")
                if process["workingSetBytes"] is None: ws_missing = True
                else: ws += process["workingSetBytes"]
                if process["privateBytes"] is None: pb_missing = True
                else: pb += process["privateBytes"]
            old = previous.get(ident)
            if index:
                if old is None:
                    appearances += 1
                if counter is None or (old is not None and old["cpuTime100ns"] is None):
                    issues.add("cpuCounterUnavailable")
                elif old is None:
                    # A newly observed process born after the previous boundary contributes its lifetime CPU.
                    if prior["fileTime"] <= process["createdFileTime"] <= sample["fileTime"]:
                        delta += counter
                    else:
                        issues.add("lateDiscoveryOrWallClockAmbiguity")
                elif counter < old["cpuTime100ns"]:
                    raise ValueError("CPU counter regressed for an unchanged PID/creation identity")
                else:
                    delta += counter - old["cpuTime100ns"]
                if process["exited"] and (old is None or not old["exited"]):
                    exits += 1
                    if counter is None:
                        issues.add("exitedProcessFinalCpuUnavailable")
            current[ident] = process
        if index:
            if set(previous) - seen:
                issues.add("trackedProcessDisappearedWithoutFinalCounter")
            duration = now - prior["elapsedSeconds"]
            used = delta / 10_000_000
            percent = used / duration / logical_processors * 100
            if percent > 100.1:
                issues.add("cpuExceedsMachineCapacity")
            cpu.append(percent)
            cpu_seconds += used; elapsed_total += duration
            working.append(None if ws_missing else ws)
            private.append(None if pb_missing else pb)
            for event in sample.get("events", []):
                if event["kind"] not in ("appearance", "exit"):
                    issues.add(event["kind"])
        previous = current; prior = sample
    cpu_stats = stats(cpu)
    cpu_stats["timeWeightedMean"] = cpu_seconds / elapsed_total / logical_processors * 100
    cpu_stats["observedCpuSeconds"] = cpu_seconds
    def memory(values):
        numbers = [v for v in values if v is not None]
        result = stats(numbers)
        result.update({"validSamples": len(numbers), "missingSamples": len(values) - len(numbers),
                       "endMinusStartBytes": values[-1] - values[0] if values[0] is not None and values[-1] is not None else None})
        return result
    return {"durationSeconds": elapsed_total, "intervals": len(cpu), "logicalProcessors": logical_processors,
            "cpuNormalizedPercent": cpu_stats, "workingSetSumBytes": memory(working), "privateCommitSumBytes": memory(private),
            "observedProcessCount": len(process_ids), "measurementAppearances": appearances, "measurementExits": exits,
            "coverageIncomplete": True, "strictTotal": False, "knownCoverageIssues": sorted(issues),
            "pollingGapRisk": "Processes born and exited between snapshots, and unseen intermediate parents, are not observable.",
            "memoryMethod": "Working sets sum shared pages repeatedly; private bytes are private committed memory, not private resident bytes.",
            "unmeasured": UNMEASURED.copy(), "qualified": False}
