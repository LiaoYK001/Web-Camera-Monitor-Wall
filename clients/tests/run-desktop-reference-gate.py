#!/usr/bin/env python3
"""Run the private 16+1 v2-M2 desktop hardware and zero-server-load gate."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import urllib.request


ALLOWED_ADAPTERS = {"rtsp", "mjpeg", "hls", "whep"}
ALLOWED_CODECS = {"h264", "h265", "mjpeg"}
MEDIA_PROCESSES = {"mediamtx", "ffmpeg", "obs-browser"}


def unique_json(path: Path) -> object:
    def unique(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"duplicate field {key!r}")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ValueError(f"non-finite value {value}")))


def validate_manifest(value: object) -> dict:
    root_fields = {"schemaVersion", "durationSeconds", "maxDroppedPercent", "requireHardware",
                   "streams"}
    stream_fields = {"name", "role", "adapter", "endpoint", "codec", "expectedFps",
                     "usernameEnv", "passwordEnv"}
    if not isinstance(value, dict) or set(value) != root_fields or value["schemaVersion"] != 1:
        raise ValueError("reference manifest fields are invalid")
    duration = value["durationSeconds"]
    if not isinstance(duration, int) or isinstance(duration, bool) or not 1800 <= duration <= 7200:
        raise ValueError("reference duration must be 1800-7200 seconds")
    maximum = value["maxDroppedPercent"]
    if not isinstance(maximum, (int, float)) or isinstance(maximum, bool) or not 0 <= maximum < 1:
        raise ValueError("maximum dropped percentage must be below one")
    if value["requireHardware"] is not True:
        raise ValueError("the M2 reference gate must require hardware decode")
    streams = value["streams"]
    if not isinstance(streams, list) or len(streams) != 17 or \
            sum(isinstance(item, dict) and item.get("role") == "sub" for item in streams) != 16 or \
            sum(isinstance(item, dict) and item.get("role") == "main" for item in streams) != 1:
        raise ValueError("reference gate requires exactly sixteen substreams and one main stream")
    names = set()
    for stream in streams:
        if not isinstance(stream, dict) or set(stream) != stream_fields:
            raise ValueError("stream fields are invalid")
        if not isinstance(stream["name"], str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", stream["name"]) or \
                stream["name"] in names:
            raise ValueError("stream name is invalid or duplicated")
        names.add(stream["name"])
        if stream["adapter"] not in ALLOWED_ADAPTERS or stream["codec"] not in ALLOWED_CODECS or \
                not isinstance(stream["endpoint"], str) or len(stream["endpoint"]) > 2048 or \
                "@" in stream["endpoint"] or not isinstance(stream["expectedFps"], (int, float)) or \
                not 1 <= stream["expectedFps"] <= 120:
            raise ValueError("stream protocol, endpoint, codec, or FPS is invalid")
        for field in ("usernameEnv", "passwordEnv"):
            if not isinstance(stream[field], str) or (stream[field] and not re.fullmatch(
                    r"WEBOBS_PRIVATE_[A-Z0-9_]{1,80}", stream[field])):
                raise ValueError("credential references must use private environment variable names")
    return value


def server_processes(url: str) -> dict | None:
    if not url:
        return None
    request = urllib.request.Request(url.rstrip("/") + "/api/v1/system/processes",
                                     headers={"Accept": "application/json"})
    username = os.environ.get("WEBOBS_REFERENCE_CONTROL_USERNAME", "")
    password = os.environ.get("WEBOBS_REFERENCE_CONTROL_PASSWORD", "")
    if username or password:
        request.add_header("Authorization", "Basic " + base64.b64encode(
            f"{username}:{password}".encode()).decode())
    with urllib.request.urlopen(request, timeout=10) as response:
        value = json.load(response)
    if not isinstance(value, dict) or not isinstance(value.get("processes"), list) or \
            not isinstance(value.get("rtspSessions"), int):
        raise RuntimeError("server process response is invalid")
    return value


def media_counts(snapshot: dict) -> dict[str, int]:
    return {item["name"]: int(item["instances"]) for item in snapshot["processes"]
            if isinstance(item, dict) and item.get("name") in MEDIA_PROCESSES}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--control-url", default=os.environ.get("WEBOBS_REFERENCE_CONTROL_URL", ""))
    arguments = parser.parse_args()
    if not arguments.client.is_file() or not arguments.evidence.is_absolute():
        raise SystemExit("client must exist and evidence path must be absolute")
    manifest = validate_manifest(unique_json(arguments.manifest))
    baseline = server_processes(arguments.control_url)
    processes: list[tuple[dict, subprocess.Popen[str]]] = []
    try:
        for stream in manifest["streams"]:
            environment = os.environ.copy()
            environment["WEBOBS_PROBE_USERNAME"] = environment.get(stream["usernameEnv"], "")
            environment["WEBOBS_PROBE_PASSWORD"] = environment.get(stream["passwordEnv"], "")
            command = [str(arguments.client), "--probe-endpoint", stream["endpoint"],
                       "--probe-adapter", stream["adapter"], "--probe-codec", stream["codec"],
                       "--probe-seconds", str(manifest["durationSeconds"])]
            processes.append((stream, subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", env=environment)))
        time.sleep(20)
        during = server_processes(arguments.control_url)
        if baseline is not None and during is not None and (
                during["rtspSessions"] != baseline["rtspSessions"] or
                media_counts(during) != media_counts(baseline)):
            raise RuntimeError("opening True Direct clients changed server media sessions")
        evidence_streams = []
        timeout = manifest["durationSeconds"] + 30
        for stream, process in processes:
            stdout, stderr = process.communicate(timeout=timeout)
            if process.returncode != 0:
                raise RuntimeError(f"stream {stream['name']} failed: {stderr[-512:]}")
            lines = [line for line in stdout.splitlines() if line.startswith("{")]
            if len(lines) != 1:
                raise RuntimeError(f"stream {stream['name']} returned invalid bounded evidence")
            result = json.loads(lines[0])
            decoded = int(result.get("framesDecoded", 0))
            dropped = int(result.get("framesDropped", 0))
            dropped_percent = 100.0 * dropped / max(1, decoded + dropped)
            minimum_frames = manifest["durationSeconds"] * float(stream["expectedFps"]) * 0.95
            if result.get("hardwareDecode") is not True or decoded < minimum_frames or \
                    dropped_percent >= manifest["maxDroppedPercent"]:
                raise RuntimeError(f"stream {stream['name']} missed its hardware/frame/drop gate")
            evidence_streams.append({"name": stream["name"], "role": stream["role"],
                "decoder": str(result.get("decoder", ""))[:128], "framesDecoded": decoded,
                "framesDropped": dropped, "droppedPercent": round(dropped_percent, 5)})
        final_server = server_processes(arguments.control_url)
        document = {"schemaVersion": 1, "result": "passed", "platform": platform.platform(),
            "python": platform.python_version(), "durationSeconds": manifest["durationSeconds"],
            "streamCount": len(evidence_streams), "streams": evidence_streams,
            "serverRtspSessionsBefore": baseline["rtspSessions"] if baseline else None,
            "serverRtspSessionsDuring": during["rtspSessions"] if during else None,
            "serverRtspSessionsAfter": final_server["rtspSessions"] if final_server else None}
        arguments.evidence.parent.mkdir(parents=True, exist_ok=True)
        temporary = arguments.evidence.with_suffix(arguments.evidence.suffix + ".tmp")
        temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(arguments.evidence)
        print("v2-M2 desktop reference gate passed: 16 substreams + 1 main, hardware decode, "
              "drop threshold, 30-minute duration, and zero incremental server media load.")
        return 0
    finally:
        for _, process in processes:
            if process.poll() is None:
                process.terminate()
        for _, process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    sys.exit(main())
