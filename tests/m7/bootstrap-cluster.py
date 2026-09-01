#!/usr/bin/env python3
"""Enroll three synthetic recorder nodes through the public controller API."""

from __future__ import annotations

import base64
import json
import os
import pathlib
import ssl
import time
import urllib.error
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[1] / ".m7-cluster"
AUTH = "Basic " + base64.b64encode(
    ((ROOT / "secrets/admin-user").read_text() + ":" +
     (ROOT / "secrets/admin-password").read_text()).encode()).decode()
BASE = os.environ.get("WEBOBS_M7_CONTROL_URL", "https://127.0.0.1:18443")
ORIGIN = BASE.rstrip("/")
TLS_CONTEXT = ssl.create_default_context(cafile=str(ROOT / "secrets/cluster-ca.crt"))


def request(method: str, path: str, value: dict | None = None) -> dict:
    body = json.dumps(value, separators=(",", ":")).encode() if value is not None else None
    headers = {"Authorization": AUTH, "Origin": ORIGIN, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    call = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(call, timeout=10, context=TLS_CONTEXT) as response:
        return json.load(response)


def wait_for_controller() -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(BASE + "/api/v1/health", timeout=2,
                                        context=TLS_CONTEXT) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise SystemExit("controller did not become reachable before the bounded deadline")


def main() -> None:
    wait_for_controller()
    enrollments = {}
    for node in ("recorder-a", "recorder-b", "recorder-c"):
        created = request("POST", "/api/v2/node-enrollments", {"name": node, "role": "recorder"})
        enrollments[node] = created
        (ROOT / f"{node}.env").write_text(
            f"WEBOBS_NODE_ENROLLMENT_ID={created['id']}\n"
            f"WEBOBS_NODE_ENROLLMENT_TOKEN={created['token']}\n", encoding="ascii")
    compose = pathlib.Path(__file__).with_name("compose.yaml")
    runtime = os.environ.get("WEBOBS_CONTAINER_RUNTIME", "docker")
    import subprocess
    subprocess.run([runtime, "compose", "-f", str(compose), "up", "-d",
                    "recorder-a", "recorder-b", "recorder-c"], check=True)
    node_ids = {}
    for node, created in enrollments.items():
        deadline = time.monotonic() + 60
        while True:
            try:
                approved = request("POST", f"/api/v2/node-enrollments/{created['id']}/approve", {})
                node_ids[node] = approved["nodeId"]
                break
            except urllib.error.HTTPError as error:
                if error.code != 409 or time.monotonic() >= deadline:
                    raise
                time.sleep(1)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        nodes = request("GET", "/api/v2/nodes")["nodes"]
        capacity = request("GET", "/api/v2/resource-capacity")["nodes"]
        volumes = request("GET", "/api/v2/storage-volumes")["volumes"]
        if len(nodes) == 3 and all(node["status"] == "online" for node in nodes) and \
                len(capacity) == 3 and len(volumes) >= 3:
            break
        time.sleep(2)
    else:
        raise SystemExit("recorders did not publish capacity and volumes before the bounded deadline")
    request("POST", "/api/v2/archive-targets", {
        "name": "M7 MinIO fixture", "endpoint": os.environ.get(
            "WEBOBS_M7_ARCHIVE_PUBLIC_ENDPOINT", "https://127.0.0.1:19000"),
        "bucket": "webobs-archive", "region": "us-east-1",
        "credentialsRef": "minio-s3.json", "enabled": True,
    })
    count = int(os.environ.get("WEBOBS_M7_CAMERA_COUNT", "8"))
    for camera in range(1, count + 1):
        camera_id = f"fixture-{camera:02d}"
        request("POST", "/api/v1/cameras", {
            "id": camera_id, "name": f"Synthetic {camera:02d}", "adapter": "rtsp",
            "address": "rtsp://mediamtx:8554/synth", "credentialsRef": "",
            "groupId": "fixture-zone-a" if camera <= (count + 1) // 2 else "fixture-zone-b",
            "tags": ["synthetic", "m7-gate"],
            "profiles": [{
                "id": "main", "name": "Main", "role": "main",
                "endpoint": "rtsp://mediamtx:8554/synth", "videoCodec": "h264",
                "audioCodec": "aac", "width": 640, "height": 360, "fps": 15,
                "transportMode": "rtsp-tcp", "audioExpectation": "auto",
            }],
        })
        node = ("recorder-a", "recorder-b", "recorder-c")[(camera - 1) % 3]
        request("POST", "/api/v2/recording-placements", {
            "cameraId": camera_id, "profileId": "main",
            "nodeId": node_ids[node], "taskType": "record-copy",
            "costs": {"cpuCores": 0.05, "memoryBytes": 16777216,
                      "decodeSlots": 0, "encodeSlots": 0, "diskBytesPerSecond": 262144},
        })
    result = {"schemaVersion": 1, "cameraCount": count,
              "nodes": sorted({node["name"]: node["id"] for node in nodes}.items())}
    (ROOT / "bootstrap-result.json").write_text(
        json.dumps(result, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    print(f"M7 cluster bootstrap passed: 3 recorders, {count} assignments.")


if __name__ == "__main__":
    main()
