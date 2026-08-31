#!/usr/bin/env python3
"""Inject bounded v2-M7 failures and write a revision-bound redacted receipt."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request


HERE = pathlib.Path(__file__).resolve().parent
REPOSITORY = HERE.parents[1]
ROOT = HERE.parent / ".m7-cluster"
COMPOSE = HERE / "compose.yaml"
BASE = os.environ.get("WEBOBS_M7_CONTROL_URL", "http://127.0.0.1:18080")
ORIGIN = "http://127.0.0.1:18080"
RUNTIME = os.environ.get("WEBOBS_CONTAINER_RUNTIME", "docker")
CHECKS = ["archiveDigestVerified", "backupRestoreVerified", "clockSkewRejected",
          "controllerIsolationBounded", "minioOutageRecordingContinues",
          "mqttReconnectBounded", "readOnlyVolumeRejected", "recorderFailureDetected",
          "staleGenerationRejected"]


def compose(*arguments: str, capture: bool = False) -> str:
    result = subprocess.run([RUNTIME, "compose", "-f", str(COMPOSE), *arguments], check=True,
                            capture_output=capture, text=True)
    return result.stdout.strip() if capture else ""


def request(method: str, path: str, value: dict | None = None,
            if_match: int | None = None, expected: int = 200) -> dict:
    auth = "Basic " + base64.b64encode(
        ((ROOT / "secrets/admin-user").read_text() + ":" +
         (ROOT / "secrets/admin-password").read_text()).encode()).decode()
    body = json.dumps(value, separators=(",", ":")).encode() if value is not None else None
    headers = {"Authorization": auth, "Origin": ORIGIN, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if if_match is not None:
        headers["If-Match"] = f'"{if_match}"'
    call = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(call, timeout=10) as response:
            if response.status != expected:
                raise RuntimeError(f"unexpected controller status {response.status}")
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == expected:
            error.read()
            return {}
        raise


def catalog(node: str) -> tuple[int, int, int]:
    database = sqlite3.connect(
        f"file:{(ROOT / 'recordings' / node / 'catalog.sqlite3').as_posix()}?mode=ro",
        uri=True, timeout=5,
    )
    try:
        values = database.execute("""
          SELECT COUNT(*), SUM(CASE WHEN archive_state='uploaded' THEN 1 ELSE 0 END),
            SUM(CASE WHEN integrity IN ('missing','corrupt') THEN 1 ELSE 0 END) FROM segments
        """).fetchone()
        return values[0] or 0, values[1] or 0, values[2] or 0
    finally:
        database.close()


def wait_until(message: str, predicate, timeout: int, interval: float = 2) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (OSError, sqlite3.Error, urllib.error.URLError, KeyError) as error:
            last_error = error
        time.sleep(interval)
    raise RuntimeError(message) from last_error


def node_status(name: str) -> str:
    for node in request("GET", "/api/v2/nodes")["nodes"]:
        if node["name"] == name:
            return node["status"]
    return "missing"


def assignments_empty(node: str) -> bool:
    value = json.loads((ROOT / node / "node" / "assignments.json").read_text(encoding="utf-8"))
    return value.get("controllerOnline") is False and value.get("assignments") == []


def write_receipt(started: float) -> None:
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY, check=True,
                              capture_output=True, text=True).stdout.strip()
    target = REPOSITORY / "build" / "private-gates" / "m7-faults.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    value = {
        "contract": "webobs-m7-gate-receipt-v1", "name": "m7-faults", "kind": "fault",
        "revision": revision,
        "completedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "durationSeconds": int(time.monotonic() - started), "cameraCount": None, "checks": CHECKS,
    }
    temporary.write_text(json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n",
                         encoding="utf-8")
    os.replace(temporary, target)


def main() -> None:
    started = time.monotonic()
    recorder_a = compose("ps", "-q", "recorder-a", capture=True)
    if not recorder_a:
        raise SystemExit("recorder-a fixture container is unavailable")

    # A Recorder must retain its camera-side network during controller loss,
    # continue only through the documented isolation window, then fail closed.
    before = catalog("recorder-a")[0]
    subprocess.run([RUNTIME, "network", "disconnect", "webobs-m7-gate-control", recorder_a], check=True)
    wait_until("recorder did not continue within the isolation window",
               lambda: catalog("recorder-a")[0] > before, 45)
    wait_until("recorder did not stop after the 120-second isolation boundary",
               lambda: assignments_empty("recorder-a"), 145)
    # The currently open crash-safe segment may finalize after the assignment
    # snapshot is cleared. Give it two segment intervals to flush, then require
    # a stable catalog instead of treating the safe finalization as new work.
    time.sleep(20)
    stopped = catalog("recorder-a")[0]
    time.sleep(15)
    if catalog("recorder-a")[0] != stopped:
        raise SystemExit("recorder created a new segment after its isolation assignment was cleared")
    subprocess.run([RUNTIME, "network", "connect", "webobs-m7-gate-control", recorder_a], check=True)
    wait_until("recorder did not rejoin after controller connectivity returned",
               lambda: node_status("recorder-a") == "online", 45)
    wait_until("recorder did not resume after lease reconciliation",
               lambda: catalog("recorder-a")[0] > stopped, 45)

    # A dead recorder is visible after the 20-second health boundary and can
    # rejoin with its existing mTLS identity.
    compose("stop", "recorder-b")
    wait_until("stopped recorder was not marked offline",
               lambda: node_status("recorder-b") == "offline", 40)
    compose("start", "recorder-b")
    wait_until("restarted recorder did not return online",
               lambda: node_status("recorder-b") == "online", 60)

    # S3 is asynchronous: loss of MinIO must not stop local recording, and the
    # backlog must return to digest-verified uploaded state after recovery.
    before_segments, before_uploaded, _ = catalog("recorder-c")
    compose("stop", "minio")
    wait_until("local recording stopped while MinIO was unavailable",
               lambda: catalog("recorder-c")[0] > before_segments, 45)
    compose("start", "minio")
    wait_until("archive backlog did not resume after MinIO recovery",
               lambda: catalog("recorder-c")[1] > before_uploaded, 90)

    # A manually read-only mounted volume remains visible but is not eligible
    # for a new recording assignment.
    volumes = request("GET", "/api/v2/storage-volumes")["volumes"]
    node_c = next(node for node in request("GET", "/api/v2/nodes")["nodes"]
                  if node["name"] == "recorder-c")
    volume = next(item for item in volumes if item["nodeId"] == node_c["id"])
    changed = request("PATCH", f"/api/v2/storage-volumes/{node_c['id']}/{volume['id']}",
                      {"state": "read-only"}, volume["revision"])
    request("POST", "/api/v2/recording-placements", {
        "cameraId": "fixture-read-only", "profileId": "main", "nodeId": node_c["id"],
        "taskType": "record-copy", "costs": {"cpuCores": .01, "memoryBytes": 1048576,
        "decodeSlots": 0, "encodeSlots": 0, "diskBytesPerSecond": 1024},
    }, expected=409)
    request("PATCH", f"/api/v2/storage-volumes/{node_c['id']}/{volume['id']}",
            {"state": "online"}, changed["revision"])

    # Exercise the real TLS broker and the deterministic generation/skew and
    # encrypted-backup suites before issuing the minimal receipt.
    compose("exec", "-T", "controller", "python3", "/fixture/mqtt-integration.py")
    subprocess.run([sys.executable, str(REPOSITORY / "tests/test_cluster_service.py")],
                   cwd=REPOSITORY, check=True)
    compose("exec", "-T", "controller", "env",
            "WEBOBS_TEST_ENCRYPTED_BACKUP=/opt/webobs/bin/webobs-encrypted-backup",
            "python3", "/fixture/test_encrypted_backup.py")
    if any(catalog(node)[2] for node in ("recorder-a", "recorder-b", "recorder-c")):
        raise SystemExit("catalog corruption was observed after fault recovery")
    write_receipt(started)
    print("M7 failure, archive, MQTT and backup gate passed.")


if __name__ == "__main__":
    main()
