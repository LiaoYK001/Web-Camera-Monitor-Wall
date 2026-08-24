#!/usr/bin/env python3
"""Run all v2-M1 protocols through a locked release client without leaking endpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


PROBES = (
    ("rtsp-h264", "rtsp", "h264", "WEBOBS_PRIVATE_RTSP_H264"),
    ("rtsp-h265", "rtsp", "h265", "WEBOBS_PRIVATE_RTSP_H265"),
    ("server-push-mjpeg", "mjpeg", "mjpeg", "WEBOBS_PRIVATE_MJPEG"),
    ("hls", "hls", "h264", "WEBOBS_PRIVATE_HLS"),
    ("whep", "whep", "h264", "WEBOBS_PRIVATE_WHEP"),
)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: run-exact-protocol-gate.py PATH_TO_LOCKED_WEBOBS_NATIVE")
    binary = Path(sys.argv[1]).resolve()
    if not binary.is_file():
        raise SystemExit("locked native client binary is unavailable")
    evidence: list[dict[str, object]] = []
    for label, adapter, codec, environment_name in PROBES:
        endpoint = os.environ.get(environment_name, "")
        if not endpoint:
            raise SystemExit(f"private endpoint reference is missing: {environment_name}")
        result = subprocess.run([
            str(binary), "--probe-endpoint", endpoint, "--probe-adapter", adapter,
            "--probe-codec", codec, "--probe-seconds", "10",
        ], check=False, capture_output=True, text=True, timeout=30)
        combined = result.stdout + result.stderr
        if endpoint in combined:
            raise SystemExit(f"protocol probe leaked its endpoint: {label}")
        if result.returncode != 0:
            raise SystemExit(f"locked production pipeline rejected protocol: {label}")
        lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
        if not lines:
            raise SystemExit(f"protocol probe returned no bounded JSON evidence: {label}")
        decoded = json.loads(lines[-1])
        evidence.append({
            "protocol": label, "result": decoded.get("result"),
            "decoder": decoded.get("decoder"), "hardwareDecode": decoded.get("hardwareDecode"),
            "framesDecoded": decoded.get("framesDecoded"), "framesDropped": decoded.get("framesDropped"),
        })
    print(json.dumps({"contractVersion": 1, "protocols": evidence}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
