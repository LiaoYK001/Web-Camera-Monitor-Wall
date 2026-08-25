#!/usr/bin/env python3
"""Prove that 1-16 True Direct viewers do not add Docker NVR upstream sessions."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request


CONTROL = os.environ.get("WEBOBS_FIXTURE_CONTROL", "http://webobs-nvr-direct:8080")
ENDPOINT = os.environ.get("WEBOBS_FIXTURE_RTSP", "rtsp://camera:8554/v2-direct")
VIEWERS = 16


def get_json(path: str) -> dict:
    request = urllib.request.Request(CONTROL + path, headers={
        "Accept": "application/json", "Host": "127.0.0.1:8080"})
    with urllib.request.urlopen(request, timeout=5) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError("server returned an invalid bounded document")
    return value


def wait_ready() -> dict:
    previous = None
    stable_samples = 0
    for _ in range(180):
        try:
            status = get_json("/api/v1/nvr/status")
            processes = get_json("/api/v1/system/processes")
            cameras = status.get("cameras", [])
            signature = media_signature(processes)
            ffmpeg_instances = dict(signature[1]).get("ffmpeg", 0)
            if status.get("status") == "ok" and isinstance(cameras, list) and \
                    any(item.get("state") == "recording" for item in cameras) and \
                    processes.get("rtspSessions", 0) >= 1 and ffmpeg_instances >= 1:
                stable_samples = stable_samples + 1 if signature == previous else 1
                previous = signature
                if stable_samples >= 3:
                    return processes
            else:
                stable_samples = 0
                previous = None
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError("NVR did not establish its baseline upstream session")


def media_signature(value: dict) -> tuple:
    processes = value.get("processes")
    if not isinstance(processes, list):
        raise RuntimeError("server process diagnostics are invalid")
    counts = tuple(sorted((str(item.get("name")), int(item.get("instances", -1)))
                          for item in processes if item.get("name") in {
                              "mediamtx", "ffmpeg", "obs-browser"}))
    return (int(value.get("rtspSessions", -1)), counts, value.get("engineActive"),
            value.get("compositePublisherActive"))


def main() -> None:
    baseline = wait_ready()
    signature = media_signature(baseline)
    viewers: list[subprocess.Popen[str]] = []
    try:
        for _ in range(VIEWERS):
            viewers.append(subprocess.Popen([
                "ffprobe", "-v", "error", "-rtsp_transport", "tcp",
                "-read_intervals", "%+15", "-select_streams", "v:0", "-count_frames",
                "-show_entries", "stream=codec_name,nb_read_frames", "-of", "json", ENDPOINT,
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace"))
        samples = 0
        deadline = time.monotonic() + 30
        while any(viewer.poll() is None for viewer in viewers):
            if time.monotonic() >= deadline:
                raise RuntimeError("concurrent True Direct viewers exceeded their deadline")
            current_signature = media_signature(get_json("/api/v1/system/processes"))
            if current_signature != signature:
                raise RuntimeError("True Direct viewer count changed Docker NVR media ownership: "
                                   f"baseline={signature!r}, current={current_signature!r}")
            samples += 1
            time.sleep(1)
        decoded = []
        for viewer in viewers:
            stdout, _ = viewer.communicate(timeout=2)
            if viewer.returncode != 0 or ENDPOINT in stdout:
                raise RuntimeError("a True Direct viewer failed without publishing private logs")
            streams = json.loads(stdout).get("streams", [])
            frames = int(streams[0].get("nb_read_frames", 0)) if streams else 0
            if frames < 30:
                raise RuntimeError("a True Direct viewer decoded insufficient video")
            decoded.append(frames)
        if media_signature(get_json("/api/v1/system/processes")) != signature:
            raise RuntimeError("True Direct viewers left an incremental Docker media session")
        print(json.dumps({"result": "passed", "viewers": len(decoded),
                          "minimumDecodedFrames": min(decoded), "serverSamples": samples,
                          "nvrRtspSessions": signature[0]}, separators=(",", ":")))
    finally:
        for viewer in viewers:
            if viewer.poll() is None:
                viewer.terminate()
        for viewer in viewers:
            try:
                viewer.wait(timeout=3)
            except subprocess.TimeoutExpired:
                viewer.kill()


if __name__ == "__main__":
    main()
