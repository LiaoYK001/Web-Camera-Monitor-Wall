#!/usr/bin/env python3
"""Run the private v2-M3 Android 9-stream, thermal, media-load and background gate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse


ROOT = Path(__file__).resolve().parents[2]
DESKTOP_GATE = Path(__file__).with_name("run-desktop-reference-gate.py")
SPEC = importlib.util.spec_from_file_location("desktop_reference_gate", DESKTOP_GATE)
assert SPEC and SPEC.loader
DESKTOP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DESKTOP)
MAX_LOG_BYTES = 8 * 1024 * 1024
PACKAGE = "org.webobs.nativeclient"
DRIVER = "org.webobs.nativeclient.acceptance"
INSTRUMENTATION = DRIVER + "/.WebObsAcceptanceInstrumentation"


def run(command: list[str], *, timeout: float = 30, check: bool = True) -> str:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"device command failed safely: {command[0]} {command[1]}")
    return result.stdout + result.stderr


def adb(serial: str, *arguments: str, timeout: float = 30, check: bool = True) -> str:
    return run(["adb", "-s", serial, *arguments], timeout=timeout, check=check)


def validate_manifest(value: object) -> dict:
    root_fields = {"schemaVersion", "durationSeconds", "maxDroppedPercent",
                   "maxThermalStatus", "streams"}
    stream_fields = {"name", "adapter", "endpoint", "codec", "expectedWidth",
                     "expectedHeight", "expectedFps", "usernameEnv", "passwordEnv"}
    if not isinstance(value, dict) or set(value) != root_fields or value["schemaVersion"] != 1:
        raise ValueError("Android reference manifest fields are invalid")
    if value["durationSeconds"] != 1800:
        raise ValueError("Android reference playback must run for exactly 1800 seconds")
    if not isinstance(value["maxDroppedPercent"], (int, float)) or \
            isinstance(value["maxDroppedPercent"], bool) or \
            not 0 <= value["maxDroppedPercent"] < 2:
        raise ValueError("Android dropped-frame threshold must be below two percent")
    if value["maxThermalStatus"] != 2:
        raise ValueError("Android gate must reject severe (3) or higher thermal status")
    streams = value["streams"]
    if not isinstance(streams, list) or len(streams) != 9:
        raise ValueError("Android reference gate requires exactly nine substreams")
    names: set[str] = set()
    for stream in streams:
        if not isinstance(stream, dict) or set(stream) != stream_fields:
            raise ValueError("Android stream fields are invalid")
        endpoint = urllib.parse.urlsplit(stream["endpoint"] if isinstance(
            stream["endpoint"], str) else "")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", stream["name"] or "") or \
                stream["name"] in names or stream["adapter"] not in DESKTOP.ALLOWED_ADAPTERS or \
                stream["codec"] not in DESKTOP.ALLOWED_CODECS or not endpoint.hostname or \
                endpoint.username is not None or endpoint.password is not None or \
                len(stream["endpoint"]) > 2048 or \
                (stream["expectedWidth"], stream["expectedHeight"], stream["expectedFps"]) != \
                (640, 360, 15) or stream["usernameEnv"] or stream["passwordEnv"]:
            raise ValueError("Android stream endpoint, shape, or credential boundary is invalid")
        names.add(stream["name"])
    return value


def certificate_digest(apksigner: Path, apk: Path) -> str:
    output = run([str(apksigner), "verify", "--print-certs", str(apk)])
    match = re.search(r"certificate SHA-256 digest:\s*([0-9a-fA-F]{64})", output)
    if match is None:
        raise RuntimeError("APK signer certificate digest is unavailable")
    return match.group(1).lower()


def log_documents(serial: str) -> tuple[str, list[dict]]:
    output = adb(serial, "logcat", "-d", "-v", "raw", timeout=20)
    if len(output.encode("utf-8")) > MAX_LOG_BYTES:
        raise RuntimeError("Android diagnostics exceeded the bounded log limit")
    documents: list[dict] = []
    for line in output.splitlines():
        start, end = line.find("{"), line.rfind("}")
        if start < 0 or end <= start:
            continue
        try:
            value = json.loads(line[start:end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("result"), str):
            documents.append(value)
    return output, documents


def thermal_status(serial: str) -> int:
    output = adb(serial, "shell", "dumpsys", "thermalservice", timeout=15)
    matches = [int(value) for value in re.findall(
        r"(?:mStatus|Thermal Status)\s*[:=]\s*([0-6])", output, re.IGNORECASE)]
    if not matches:
        raise RuntimeError("Android thermal status is unavailable")
    return max(matches)


def launch_probe(serial: str, remote_manifest: str, background: bool) -> None:
    adb(serial, "shell", "am", "force-stop", PACKAGE)
    adb(serial, "logcat", "-c")
    adb(serial, "shell", "am", "instrument", "-w", "-r",
        "-e", "manifestPath", remote_manifest,
        "-e", "backgroundRelease", "true" if background else "false",
        INSTRUMENTATION, timeout=60)


def wait_for_document(serial: str, result: str, deadline: float) -> tuple[str, dict]:
    last_log = ""
    while time.monotonic() < deadline:
        last_log, documents = log_documents(serial)
        for document in reversed(documents):
            if document.get("result") == result:
                return last_log, document
        time.sleep(1)
    raise RuntimeError(f"Android client did not emit bounded {result!r} evidence")


def write_evidence(path: Path, document: dict) -> None:
    target = DESKTOP.validate_evidence_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n",
                                         dir=target.parent, prefix=".webobs-m3-",
                                         suffix=".json.tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            temporary.chmod(0o600)
        os.link(temporary, target)
        temporary.unlink()
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--driver-apk", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--apksigner", type=Path, required=True)
    parser.add_argument("--control-url", default=os.environ.get("WEBOBS_REFERENCE_CONTROL_URL", ""))
    arguments = parser.parse_args()
    for artifact in (arguments.apk, arguments.driver_apk, arguments.manifest,
                     arguments.apksigner):
        if not artifact.is_file():
            raise SystemExit(f"required private gate input is missing: {artifact.name}")
    manifest = validate_manifest(DESKTOP.unique_json(arguments.manifest))
    if certificate_digest(arguments.apksigner, arguments.apk) != \
            certificate_digest(arguments.apksigner, arguments.driver_apk):
        raise SystemExit("client and private acceptance driver signatures differ")
    if not arguments.control_url:
        raise SystemExit("reference control URL is required for zero-server-media evidence")
    control_url = DESKTOP.validate_control_url(arguments.control_url)
    DESKTOP.validate_control_credentials()
    state = adb(arguments.serial, "get-state").strip()
    api = int(adb(arguments.serial, "shell", "getprop", "ro.build.version.sdk").strip())
    abi = adb(arguments.serial, "shell", "getprop", "ro.product.cpu.abi").strip()
    if state != "device" or api < 29 or abi != "arm64-v8a":
        raise SystemExit("reference device must be an authorized API 29+ arm64-v8a device")

    digest = hashlib.sha256(arguments.manifest.read_bytes()).hexdigest()[:16]
    remote = f"/data/local/tmp/webobs-m3-{digest}.json"
    baseline = DESKTOP.server_processes(control_url)
    temperatures: list[int] = []
    server_samples = 0
    final_log = ""
    try:
        adb(arguments.serial, "install", "-r", "--no-streaming", str(arguments.apk), timeout=180)
        adb(arguments.serial, "install", "-r", "--no-streaming", str(arguments.driver_apk), timeout=120)
        adb(arguments.serial, "push", str(arguments.manifest), remote, timeout=60)
        adb(arguments.serial, "shell", "chmod", "0644", remote)
        launch_probe(arguments.serial, remote, False)
        wait_for_document(arguments.serial, "ready", time.monotonic() + 45)
        deadline = time.monotonic() + manifest["durationSeconds"] + 45
        passed: dict | None = None
        while time.monotonic() < deadline:
            final_log, documents = log_documents(arguments.serial)
            passed = next((item for item in reversed(documents)
                           if item.get("result") == "passed"), None)
            if passed is not None:
                break
            current = DESKTOP.server_processes(control_url)
            if not DESKTOP.same_server_media(baseline, current):
                raise RuntimeError("Android True Direct playback changed server media sessions")
            temperatures.append(thermal_status(arguments.serial))
            if temperatures[-1] > manifest["maxThermalStatus"]:
                raise RuntimeError("Android device entered severe thermal status")
            server_samples += 1
            time.sleep(10)
        if passed is None:
            raise RuntimeError("Android 30-minute reference playback did not complete")
        for stream in manifest["streams"]:
            if stream["endpoint"] in final_log:
                raise RuntimeError("Android log exposed a private endpoint")
        results = passed.get("streams")
        if passed.get("processCount") != 1 or not isinstance(results, list) or len(results) != 9:
            raise RuntimeError("Android playback returned an invalid process or stream set")
        by_name = {item.get("name"): item for item in results if isinstance(item, dict)}
        evidence_streams = []
        for expected in manifest["streams"]:
            observed = by_name.get(expected["name"], {})
            decoded = int(observed.get("framesDecoded", 0))
            dropped = int(observed.get("framesDropped", 0))
            dropped_percent = 100.0 * dropped / max(1, decoded + dropped)
            decoder = str(observed.get("decoder", "")).lower()
            if observed.get("hardwareDecode") is not True or \
                    not ("amc" in decoder or "mediacodec" in decoder) or \
                    decoded < 0.95 * 1800 * 15 or \
                    dropped_percent >= manifest["maxDroppedPercent"] or \
                    (observed.get("width"), observed.get("height")) != (640, 360) or \
                    int(observed.get("blackSamples", -1)) != 0 or \
                    int(observed.get("pipelineRestarts", -1)) != 0:
                raise RuntimeError(f"stream {expected['name']} missed the MediaCodec/frame/drop gate")
            evidence_streams.append({"name": expected["name"], "decoder": decoder[:128],
                "framesDecoded": decoded, "framesDropped": dropped,
                "droppedPercent": round(dropped_percent, 5)})

        short = dict(manifest)
        short["durationSeconds"] = 60
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json",
                                         delete=False) as handle:
            short_path = Path(handle.name)
            json.dump(short, handle)
        try:
            adb(arguments.serial, "push", str(short_path), remote, timeout=60)
        finally:
            short_path.unlink(missing_ok=True)
        launch_probe(arguments.serial, remote, True)
        wait_for_document(arguments.serial, "ready", time.monotonic() + 45)
        background_started = time.monotonic()
        adb(arguments.serial, "shell", "input", "keyevent", "KEYCODE_HOME")
        release_log, released = wait_for_document(
            arguments.serial, "background-released", background_started + 5.5)
        release_wall_ms = int((time.monotonic() - background_started) * 1000)
        if int(released.get("streamCount", 0)) != 9 or \
                int(released.get("releaseMilliseconds", 6000)) > 5000 or release_wall_ms > 5500:
            raise RuntimeError("Android background resource release exceeded five seconds")
        power = adb(arguments.serial, "shell", "dumpsys", "power", timeout=15)
        if "WebObs:ForegroundMonitor" in power:
            raise RuntimeError("Android background probe left its monitor Wake Lock held")
        if any(stream["endpoint"] in release_log for stream in manifest["streams"]):
            raise RuntimeError("Android background log exposed a private endpoint")
        final_server = DESKTOP.server_processes(control_url)
        if not DESKTOP.same_server_media(baseline, final_server):
            raise RuntimeError("Android gate left incremental server media sessions")
        write_evidence(arguments.evidence, {"schemaVersion": 1, "result": "passed",
            "apiLevel": api, "abi": abi, "durationSeconds": 1800, "streamCount": 9,
            "serverSamples": server_samples, "maxThermalStatus": max(temperatures),
            "backgroundReleaseMilliseconds": int(released["releaseMilliseconds"]),
            "backgroundReleaseWallMilliseconds": release_wall_ms, "streams": evidence_streams,
            "serverRtspSessionsBefore": baseline["rtspSessions"],
            "serverRtspSessionsAfter": final_server["rtspSessions"]})
        print("v2-M3 Android reference gate passed: 9 MediaCodec streams for 30 minutes, "
              "<2% drops, no severe thermal state, zero server media increment, and <=5s "
              "background release.")
        return 0
    finally:
        adb(arguments.serial, "shell", "rm", "-f", remote, check=False)
        adb(arguments.serial, "uninstall", DRIVER, check=False)


if __name__ == "__main__":
    sys.exit(main())
