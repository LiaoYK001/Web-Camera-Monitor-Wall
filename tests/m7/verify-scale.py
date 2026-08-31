#!/usr/bin/env python3
"""Measure the bounded three-recorder scale fixture and emit only a redacted receipt."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import os
import pathlib
import sqlite3
import subprocess
import time
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[1] / ".m7-cluster"
REPOSITORY = pathlib.Path(__file__).resolve().parents[2]
BASE = os.environ.get("WEBOBS_M7_CONTROL_URL", "http://127.0.0.1:18080")
ORIGIN = "http://127.0.0.1:18080"
CHECKS = ["assignmentsAccepted", "catalogIntegrity", "controllerThreeRecorders",
          "recordingAllNodes", "resourceCapacityReported", "threeStorageVolumes"]


def request(path: str) -> dict:
    auth = "Basic " + base64.b64encode(
        ((ROOT / "secrets/admin-user").read_text() + ":" +
         (ROOT / "secrets/admin-password").read_text()).encode()).decode()
    call = urllib.request.Request(BASE + path, headers={
        "Authorization": auth, "Origin": ORIGIN, "Accept": "application/json",
    })
    with urllib.request.urlopen(call, timeout=10) as response:
        return json.load(response)


def catalog_measurements() -> list[dict[str, int]]:
    measurements = []
    for node in ("recorder-a", "recorder-b", "recorder-c"):
        path = ROOT / "recordings" / node / "catalog.sqlite3"
        deadline = time.monotonic() + 40
        while True:
            try:
                database = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
                segments, corrupt, uploaded = database.execute("""
                  SELECT COUNT(*),
                    SUM(CASE WHEN integrity IN ('deleted','missing','corrupt') THEN 1 ELSE 0 END),
                    SUM(CASE WHEN archive_state='uploaded' THEN 1 ELSE 0 END)
                  FROM segments
                """).fetchone()
                database.close()
                if segments and uploaded:
                    measurements.append({"segments": segments, "corrupt": corrupt or 0,
                                         "uploaded": uploaded})
                    break
            except sqlite3.Error:
                pass
            if time.monotonic() >= deadline:
                raise SystemExit(f"{node} did not produce an uploaded, verifiable segment")
            time.sleep(2)
    return measurements


def atomic_receipt(camera_count: int, duration: int) -> pathlib.Path:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    evidence = REPOSITORY / "build" / "private-gates"
    evidence.mkdir(parents=True, exist_ok=True)
    target = evidence / f"m7-scale-{camera_count}.json"
    temporary = target.with_suffix(".tmp")
    value = {
        "contract": "webobs-m7-gate-receipt-v1", "name": f"m7-scale-{camera_count}",
        "kind": "scale", "revision": revision,
        "completedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "durationSeconds": duration, "cameraCount": camera_count, "checks": CHECKS,
    }
    temporary.write_text(json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n",
                         encoding="utf-8")
    os.replace(temporary, target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera-count", type=int, choices=(8, 16, 32), required=True)
    parser.add_argument("--duration-seconds", type=int, required=True)
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args()
    nodes = request("/api/v2/nodes")["nodes"]
    volumes = request("/api/v2/storage-volumes")["volumes"]
    capacity = request("/api/v2/resource-capacity")["nodes"]
    placements = request("/api/v2/recording-placements")["placements"]
    if len(nodes) != 3 or any(node["status"] != "online" for node in nodes):
        raise SystemExit("three online recorders were not observed")
    if len({(item["nodeId"], item["id"]) for item in volumes}) < 3:
        raise SystemExit("three recorder volumes were not observed")
    if len(capacity) != 3 or any(not item["rated"] for item in capacity):
        raise SystemExit("rated capacity was not reported by all recorders")
    if len(placements) != args.camera_count or any(item["state"] != "active" for item in placements):
        raise SystemExit("the exact active assignment set was not observed")
    measurements = catalog_measurements()
    if any(item["corrupt"] != 0 or item["uploaded"] <= 0 for item in measurements):
        raise SystemExit("catalog integrity or verified S3 archive state failed")
    if args.write_receipt:
        if args.duration_seconds < 900:
            raise SystemExit("scale receipts require a measured duration of at least 900 seconds")
        path = atomic_receipt(args.camera_count, args.duration_seconds)
        print(f"Redacted v2-M7 scale receipt written to {path.relative_to(REPOSITORY)}")
    print(f"M7 scale verification passed for {args.camera_count} cameras on three recorders.")


if __name__ == "__main__":
    main()
