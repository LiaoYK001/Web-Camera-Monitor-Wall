#!/usr/bin/env python3
"""Manually attach to an already-running Windows root. Never control the product."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

from common import (SCHEMA, UNMEASURED, digest, metadata, new_private_directory, read_json,
                    summarize_samples, write_json)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class Tree:
    """Retain observed process handles to read final CPU after exit; never follow reused PIDs."""
    def __init__(self, root, factory, enumerate_processes):
        self.root = root; self.factory = factory; self.enumerate = enumerate_processes
        self.owned = {root.identity: root}
        self.current = {root.pid: root}

    def capture(self) -> tuple[list[dict], list[dict]]:
        observations = {key: p.observe() for key, p in self.owned.items()}
        events = []
        rows = self.enumerate()
        attempted = set()
        progress = True
        while progress:
            progress = False
            for row in rows:
                pid = row["pid"]
                if pid in attempted:
                    continue
                old = self.current.get(pid)
                if old is not None and not old.exited:
                    attempted.add(pid); continue
                parent = self.current.get(row["parentPid"])
                if parent is None:
                    continue
                attempted.add(pid)
                if pid == os.getpid():
                    raise ValueError("Collector must be outside the measured product tree")
                try:
                    child = self.factory(pid, row["parentPid"], row["exeName"], parent.identity)
                except OSError as exc:
                    events.append({"kind": "descendantOpenUnavailable", "pid": pid,
                                   "winError": getattr(exc, "winerror", None)})
                    continue
                if child.identity in self.owned:
                    child.close(); continue
                if child.created < parent.created or (parent.exited and (not parent.exit_time or child.created > parent.exit_time)):
                    events.append({"kind": "parentPidReuseOrCreationAmbiguous", "pid": pid})
                    child.close(); continue
                if len(self.owned) >= 4096:
                    child.close()
                    raise ValueError("Process identity safety limit exceeded")
                if old is not None:
                    events.append({"kind": "pidReuseObserved", "pid": pid})
                self.owned[child.identity] = child
                self.current[pid] = child
                observations[child.identity] = child.observe()
                events.append({"kind": "appearance", "identity": child.identity})
                progress = True
        for ident, observation in observations.items():
            for error in observation.get("errors", []):
                events.append({"kind": error, "identity": ident})
        return list(observations.values()), events

    def close(self):
        for process in self.owned.values():
            process.close()


def run(args) -> Path:
    if os.name != "nt":
        raise ValueError("Actual process collection is Windows x64 only")
    import win32
    meta = metadata(read_json(args.metadata))
    if args.pid < 1 or args.pid == os.getpid() or not args.exe.is_absolute() or not args.exe.is_file():
        raise ValueError("Supply an existing absolute root executable and an already-running external root PID")
    if not 0 <= args.warmup <= 86400 or not 0 < args.duration <= 86400 or not .2 <= args.interval <= 60:
        raise ValueError("Invalid timing bounds")
    if args.duration < args.interval:
        raise ValueError("Sample duration must cover at least one complete interval")
    if not args.fixture and (args.warmup < 180 or args.duration < 1200):
        raise ValueError("Short collection requires explicit --fixture; P5 defaults are 180s warm-up / 1200s measurement")
    if args.fixture and meta["workload"] != "fixture":
        raise ValueError("Short fixture mode must use workload=fixture metadata")
    if (args.warmup + args.duration) / args.interval > 36000:
        raise ValueError("Sample count safety limit exceeded")
    root = win32.Process(args.pid, 0, args.exe.name, None)
    tree = Tree(root, win32.Process, win32.snapshot)
    try:
        actual = os.path.normcase(os.path.normpath(root.image()))
        expected = os.path.normcase(os.path.normpath(str(args.exe)))
        if actual != expected:
            raise ValueError("Root PID executable does not exactly match --exe")
        if root.observe()["exited"]:
            raise ValueError("Root process has already exited")
        cpus = win32.logical_processors()
        output = new_private_directory(args.output)
        write_json(output / "metadata.json", meta)
        manifest = {"schemaVersion": SCHEMA, "collector": "windows-readonly-process-tree-v1",
                    "startedUtc": utc(), "endedUtc": None, "sampleStartUtc": None, "sampleEndUtc": None,
                    "status": "collecting", "fixture": args.fixture, "rootIdentity": root.identity,
                    "rootExeSha256": digest(args.exe), "logicalProcessors": cpus,
                    "timing": {"requestedWarmupSeconds": args.warmup, "requestedDurationSeconds": args.duration,
                               "intervalSeconds": args.interval, "actualWarmupSeconds": None},
                    "coverageIncomplete": True, "strictTotal": False, "qualified": False,
                    "samplingMethod": "Read-only Toolhelp parent snapshots; retained process handles / GetProcessTimes / GetProcessMemoryInfo",
                    "unmeasured": UNMEASURED.copy()}
        start = time.perf_counter(); measurements = []; last_exited = set(); root_exit = False
        try:
            with (output / "samples.jsonl").open("x", encoding="utf-8", newline="\n") as raw:
                def capture(phase):
                    nonlocal root_exit
                    before = time.perf_counter()
                    processes, events = tree.capture()
                    for process in processes:
                        if process["exited"] and process["identity"] not in last_exited:
                            last_exited.add(process["identity"])
                            events.append({"kind": "exit", "identity": process["identity"]})
                    root_exit = root.exited
                    record = {"phase": phase, "elapsedSeconds": time.perf_counter() - start,
                              "fileTime": win32.system_file_time(), "utc": utc(),
                              "captureSpanSeconds": time.perf_counter() - before,
                              "processes": processes, "events": events}
                    raw.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"); raw.flush()
                    if phase != "warmup": measurements.append(record)
                deadline = start + args.warmup
                capture("warmup" if args.warmup else "baseline")
                while not root_exit and time.perf_counter() < deadline:
                    time.sleep(max(0, min(args.interval, deadline - time.perf_counter())))
                    if time.perf_counter() < deadline:
                        capture("warmup")
                if root_exit:
                    manifest["status"] = "root-exited-during-warmup"
                else:
                    if args.warmup: capture("baseline")
                    manifest["sampleStartUtc"] = measurements[0]["utc"]
                    manifest["timing"]["actualWarmupSeconds"] = measurements[0]["elapsedSeconds"]
                    baseline = time.perf_counter(); final = baseline + args.duration
                    target = min(final, baseline + args.interval)
                    while not root_exit:
                        time.sleep(max(0, target - time.perf_counter()))
                        capture("measure")
                        if time.perf_counter() >= final: break
                        target = min(final, target + args.interval)
                    manifest["sampleEndUtc"] = measurements[-1]["utc"]
                    manifest["status"] = "root-exited-during-measurement" if root_exit else "complete"
        except (Exception, KeyboardInterrupt) as exc:
            # Keep partial data without paths, OS messages, command lines or user strings in reports.
            manifest["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "collection-error"
            manifest["errorType"] = type(exc).__name__
        manifest["endedUtc"] = utc()
        raw_path = output / "samples.jsonl"
        manifest["samplesSha256"] = digest(raw_path)
        manifest["metadataSha256"] = digest(output / "metadata.json")
        try:
            manifest["summary"] = summarize_samples(measurements, cpus) if len(measurements) >= 2 else None
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            manifest["summary"] = None
            manifest["status"] = "invalid-sample-accounting"
            manifest["errorType"] = type(exc).__name__
        write_json(output / "manifest.json", manifest)
        if manifest["status"] != "complete":
            raise ValueError(f'Private partial receipt retained; status={manifest["status"]}')
        return output
    finally:
        tree.close()


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--pid", type=int, required=True)
    result.add_argument("--exe", type=Path, required=True, help="Exact absolute executable of an already-started root")
    result.add_argument("--metadata", type=Path, required=True, help="Anonymous allowlisted run JSON")
    result.add_argument("--output", type=Path, required=True, help="New absolute private directory OUTSIDE every Git tree")
    result.add_argument("--warmup", type=float, default=180)
    result.add_argument("--duration", type=float, default=1200)
    result.add_argument("--interval", type=float, default=5)
    result.add_argument("--fixture", action="store_true", help="Explicit short algorithm diagnostic, never qualification")
    return result


if __name__ == "__main__":
    try:
        location = run(parser().parse_args())
        print("Private CPU/memory lower-bound receipt complete. No OBS parity or hardware qualification is implied.")
    except (ValueError, OSError) as error:
        print(f"Collection refused or incomplete ({type(error).__name__}); inspect private output if created.", file=sys.stderr)
        sys.exit(1)
