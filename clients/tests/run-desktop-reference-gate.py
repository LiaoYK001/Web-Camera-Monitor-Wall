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
MEDIA_STATE_FIELDS = {"engineActive", "compositePublisherActive"}
MONITOR_INTERVAL_SECONDS = 10.0


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
    root_fields = {"schemaVersion", "durationSeconds", "maxDroppedPercent", "maxRssGrowthMiB",
                   "requireHardware", "streams"}
    stream_fields = {"name", "role", "adapter", "endpoint", "codec", "expectedWidth",
                     "expectedHeight", "expectedFps",
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
    rss_limit = value["maxRssGrowthMiB"]
    if not isinstance(rss_limit, int) or isinstance(rss_limit, bool) or not 32 <= rss_limit <= 2048:
        raise ValueError("RSS growth limit must be 32-2048 MiB")
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
        expected_shape = (stream["expectedWidth"], stream["expectedHeight"], stream["expectedFps"])
        allowed_shapes = {(640, 360, 15)} if stream["role"] == "sub" else {
            (1920, 1080, 25), (1920, 1080, 30)}
        if expected_shape not in allowed_shapes:
            raise ValueError("substreams must be 640x360@15 and main must be 1080p@25/30")
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
            not isinstance(value.get("rtspSessions"), int) or any(
                not isinstance(value.get(field), bool) for field in MEDIA_STATE_FIELDS):
        raise RuntimeError("server process response is invalid")
    return value


def media_counts(snapshot: dict) -> dict[str, int]:
    return {item["name"]: int(item["instances"]) for item in snapshot["processes"]
            if isinstance(item, dict) and item.get("name") in MEDIA_PROCESSES}


def same_server_media(baseline: dict | None, current: dict | None) -> bool:
    if baseline is None or current is None:
        return baseline is current
    return current["rtspSessions"] == baseline["rtspSessions"] and \
        media_counts(current) == media_counts(baseline) and all(
            current[field] == baseline[field] for field in MEDIA_STATE_FIELDS)


def assert_private_value_not_logged(output: str, stream: dict, environment: dict[str, str]) -> None:
    sensitive = [stream["endpoint"]]
    sensitive.extend(environment.get(stream[field], "") for field in ("usernameEnv", "passwordEnv"))
    if any(value and value in output for value in sensitive):
        raise RuntimeError(f"stream {stream['name']} emitted a private endpoint or credential")


def process_rss_bytes(process_id: int) -> int | None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        query_information, virtual_memory_read = 0x0400, 0x0010
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                               ctypes.POINTER(ProcessMemoryCounters),
                                               wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(
            query_information | virtual_memory_read, False, process_id)
        if not handle:
            return None
        try:
            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return None
            return int(counters.WorkingSetSize)
        finally:
            kernel32.CloseHandle(handle)
    status = Path(f"/proc/{process_id}/status")
    if status.is_file():
        match = re.search(r"^VmRSS:\s+(\d+)\s+kB$", status.read_text(
            encoding="utf-8", errors="replace"), re.MULTILINE)
        return int(match.group(1)) * 1024 if match else None
    try:
        value = subprocess.check_output(
            ["ps", "-o", "rss=", "-p", str(process_id)], text=True, timeout=3).strip()
        return int(value) * 1024 if value else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


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
    process: subprocess.Popen[str] | None = None
    try:
        environment = os.environ.copy()
        private_names = {stream[field] for stream in manifest["streams"]
                         for field in ("usernameEnv", "passwordEnv") if stream[field]}
        private_values = {name: os.environ.get(name, "") for name in private_names}
        for name in tuple(environment):
            if name.startswith("WEBOBS_PRIVATE_") or name in {
                    "WEBOBS_REFERENCE_CONTROL_USERNAME", "WEBOBS_REFERENCE_CONTROL_PASSWORD"}:
                environment.pop(name, None)
        environment.update(private_values)
        environment["GST_DEBUG"] = "0"
        process = subprocess.Popen(
            [str(arguments.client), "--probe-manifest", str(arguments.manifest.resolve())],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", env=environment)
        deadline = time.monotonic() + manifest["durationSeconds"] + 30
        during = None
        samples = 0
        rss_samples: list[int] = []
        started = time.monotonic()
        while process.poll() is None:
            if time.monotonic() >= deadline:
                raise RuntimeError("desktop reference client exceeded its bounded deadline")
            current = server_processes(arguments.control_url)
            if not same_server_media(baseline, current):
                raise RuntimeError("opening the True Direct client changed server media sessions")
            during = current
            samples += 1
            if time.monotonic() - started >= 60:
                rss = process_rss_bytes(process.pid)
                if rss is not None:
                    rss_samples.append(rss)
            time.sleep(MONITOR_INTERVAL_SECONDS)
        stdout, stderr = process.communicate(timeout=5)
        for stream in manifest["streams"]:
            assert_private_value_not_logged(stdout + stderr, stream, os.environ)
        if process.returncode != 0:
            raise RuntimeError("desktop reference client failed without publishing private logs")
        lines = [line for line in stdout.splitlines() if line.startswith("{")]
        if len(lines) != 1:
            raise RuntimeError("desktop reference client returned invalid bounded evidence")
        batch_result = json.loads(lines[0])
        if batch_result.get("result") != "passed" or batch_result.get("processCount") != 1:
            raise RuntimeError("desktop reference evidence did not come from one client process")
        results = batch_result.get("streams", [])
        if not isinstance(results, list) or len(results) != len(manifest["streams"]):
            raise RuntimeError("desktop reference client returned an invalid stream set")
        results_by_name = {result.get("name"): result for result in results
                           if isinstance(result, dict)}
        if len(results_by_name) != len(results):
            raise RuntimeError("desktop reference client returned duplicate stream evidence")
        evidence_streams = []
        for stream in manifest["streams"]:
            result = results_by_name.get(stream["name"], {})
            decoded = int(result.get("framesDecoded", 0))
            dropped = int(result.get("framesDropped", 0))
            dropped_percent = 100.0 * dropped / max(1, decoded + dropped)
            width = int(result.get("width", 0))
            height = int(result.get("height", 0))
            minimum_frames = manifest["durationSeconds"] * float(stream["expectedFps"]) * 0.95
            minimum_visual_samples = minimum_frames / 60
            if result.get("hardwareDecode") is not True or decoded < minimum_frames or \
                    width != stream["expectedWidth"] or height != stream["expectedHeight"] or \
                    dropped_percent >= manifest["maxDroppedPercent"] or \
                    int(result.get("visualSamples", 0)) < minimum_visual_samples or \
                    int(result.get("blackSamples", -1)) != 0 or \
                    int(result.get("pipelineRestarts", -1)) != 0:
                raise RuntimeError(f"stream {stream['name']} missed its hardware/frame/drop gate")
            evidence_streams.append({"name": stream["name"], "role": stream["role"],
                "decoder": str(result.get("decoder", ""))[:128], "framesDecoded": decoded,
                "framesDropped": dropped, "droppedPercent": round(dropped_percent, 5),
                "width": width, "height": height,
                "visualSamples": int(result.get("visualSamples", 0)),
                "blackSamples": int(result.get("blackSamples", -1)),
                "pipelineRestarts": int(result.get("pipelineRestarts", -1))})
        if len(rss_samples) < 3:
            raise RuntimeError("desktop reference client produced insufficient RSS samples")
        rss_growth = max(0, rss_samples[-1] - rss_samples[0])
        rss_limit = manifest["maxRssGrowthMiB"] * 1024 * 1024
        if rss_growth > rss_limit:
            raise RuntimeError("desktop reference client exceeded its bounded RSS growth gate")
        final_server = server_processes(arguments.control_url)
        if not same_server_media(baseline, final_server):
            raise RuntimeError("True Direct clients left incremental server media sessions")
        document = {"schemaVersion": 1, "result": "passed", "platform": platform.platform(),
            "python": platform.python_version(), "durationSeconds": manifest["durationSeconds"],
            "processCount": 1, "streamCount": len(evidence_streams), "serverSamples": samples,
            "rssSamples": len(rss_samples), "rssInitialBytes": rss_samples[0],
            "rssFinalBytes": rss_samples[-1], "rssPeakBytes": max(rss_samples),
            "rssGrowthBytes": rss_growth,
            "streams": evidence_streams,
            "serverRtspSessionsBefore": baseline["rtspSessions"] if baseline else None,
            "serverRtspSessionsDuring": during["rtspSessions"] if during else None,
            "serverRtspSessionsAfter": final_server["rtspSessions"] if final_server else None}
        arguments.evidence.parent.mkdir(parents=True, exist_ok=True)
        temporary = arguments.evidence.with_suffix(arguments.evidence.suffix + ".tmp")
        temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(arguments.evidence)
        print("v2-M2 desktop reference gate passed in one client process: 16 substreams + 1 main, "
              "hardware decode, drop/RSS thresholds, continuous 30-minute server sampling, "
              "and zero incremental media load.")
        return 0
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
        if process is not None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    sys.exit(main())
