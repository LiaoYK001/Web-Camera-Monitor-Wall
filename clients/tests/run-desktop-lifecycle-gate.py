#!/usr/bin/env python3
"""Qualify desktop network recovery, real suspend/resume, and GPU fallback."""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
REFERENCE_GATE = Path(__file__).with_name("run-desktop-reference-gate.py")
SPEC = importlib.util.spec_from_file_location("desktop_reference_gate", REFERENCE_GATE)
assert SPEC and SPEC.loader
REFERENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REFERENCE)
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


def validate_private_helper(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if resolved == ROOT.resolve() or resolved.is_relative_to(ROOT.resolve()):
        raise ValueError("desktop lifecycle helper must remain outside the public worktree")
    if not resolved.is_file() or resolved.is_symlink() or not os.access(resolved, os.X_OK):
        raise ValueError("desktop lifecycle helper must be an executable regular file")
    return resolved


def run_private_helper(path: Path, timeout: float) -> float:
    environment = {name: os.environ[name] for name in (
        "PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR") if name in os.environ}
    # CLOCK_MONOTONIC commonly pauses during Linux suspend. Wall time is used
    # only to reject a no-op private suspend helper, never for authorization.
    started = time.time()
    result = subprocess.run([str(path)], capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, check=False,
                            cwd=path.parent, env=environment)
    elapsed = time.time() - started
    if result.returncode != 0 or result.stdout or result.stderr:
        raise RuntimeError("private desktop lifecycle helper failed or emitted unsafe output")
    return elapsed


def bounded_text(handle) -> str:
    handle.flush()
    handle.seek(0, os.SEEK_END)
    if handle.tell() > MAX_OUTPUT_BYTES:
        raise RuntimeError("desktop lifecycle diagnostics exceeded their private bound")
    handle.seek(0)
    return handle.read()


def documents(handle) -> list[dict]:
    values = []
    for line in bounded_text(handle).splitlines():
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            values.append(value)
    return values


def wait_document(handle, result: str, deadline: float) -> dict:
    while time.monotonic() < deadline:
        for value in reversed(documents(handle)):
            if value.get("result") == result:
                return value
        time.sleep(0.2)
    raise RuntimeError(f"desktop lifecycle probe did not emit {result!r}")


def atomic_command(path: Path, command: str) -> None:
    if command not in {"active", "background", "foreground"}:
        raise ValueError("lifecycle command is invalid")
    temporary = path.with_name(path.name + ".next")
    temporary.write_text(command + "\n", encoding="utf-8")
    os.replace(temporary, path)


def control_json(method: str, control_url: str, path: str,
                 body: dict | None = None) -> tuple[int, dict]:
    username, password = REFERENCE.validate_control_credentials()
    headers = {"Accept": "application/json", "Authorization": "Basic " +
        base64.b64encode(f"{username}:{password}".encode()).decode()}
    payload = None
    if body is not None:
        payload = json.dumps(body, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(control_url + path, data=payload,
                                     headers=headers, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        data = response.read(MAX_OUTPUT_BYTES + 1)
        status = response.status
    if len(data) > MAX_OUTPUT_BYTES:
        raise RuntimeError("desktop authorization control response exceeded its bound")
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("desktop authorization control response was invalid") from error
    if not isinstance(value, dict):
        raise RuntimeError("desktop authorization control response must be an object")
    return status, value


def one_stream_manifest(manifest: dict, duration: int) -> dict:
    stream = dict(manifest["streams"][0])
    return {"schemaVersion": 1, "durationSeconds": duration, "streams": [stream]}


def start_probe(client: Path, arguments: list[str], environment: dict[str, str], directory: Path):
    stdout = tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace",
                                    dir=directory)
    stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace",
                                    dir=directory)
    process = subprocess.Popen([str(client), *arguments], stdout=stdout, stderr=stderr,
                               text=True, encoding="utf-8", errors="replace", env=environment)
    return process, stdout, stderr


def finish_probe(process, stdout, stderr, deadline: float) -> tuple[list[dict], str]:
    timeout = max(1.0, deadline - time.monotonic())
    process.wait(timeout=timeout)
    output = bounded_text(stdout) + bounded_text(stderr)
    values = documents(stdout)
    stdout.close()
    stderr.close()
    if process.returncode != 0:
        raise RuntimeError("desktop lifecycle client failed without publishing private logs")
    return values, output


def assert_no_private_output(output: str, manifest: dict) -> None:
    sensitive = [stream["endpoint"] for stream in manifest["streams"]]
    sensitive.extend(value for name, value in os.environ.items()
                     if name.startswith("WEBOBS_PRIVATE_") and value)
    if any(value in output for value in sensitive):
        raise RuntimeError("desktop lifecycle output exposed a private endpoint or credential")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--network-disconnect-helper", type=Path, required=True)
    parser.add_argument("--network-connect-helper", type=Path, required=True)
    parser.add_argument("--suspend-helper", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--control-url", default=os.environ.get(
        "WEBOBS_REFERENCE_CONTROL_URL", ""))
    arguments = parser.parse_args()
    if not arguments.client.is_file():
        raise SystemExit("desktop lifecycle client must exist")
    manifest = REFERENCE.validate_manifest(REFERENCE.unique_json(arguments.manifest))
    evidence = REFERENCE.validate_evidence_path(arguments.evidence)
    control_url = REFERENCE.validate_control_url(arguments.control_url)
    if not control_url:
        raise SystemExit("desktop lifecycle gate requires the server media control URL")
    disconnect_helper = validate_private_helper(arguments.network_disconnect_helper)
    connect_helper = validate_private_helper(arguments.network_connect_helper)
    suspend_helper = validate_private_helper(arguments.suspend_helper)
    environment = REFERENCE.private_environment(manifest)
    environment["WEBOBS_PRIVATE_RTSP_H264"] = os.environ.get("WEBOBS_PRIVATE_RTSP_H264", "")
    if not environment["WEBOBS_PRIVATE_RTSP_H264"]:
        raise ValueError("WEBOBS_PRIVATE_RTSP_H264 is required for GPU fallback qualification")
    environment["WEBOBS_PROBE_USERNAME"] = os.environ.get("WEBOBS_PRIVATE_CAMERA_USER", "")
    environment["WEBOBS_PROBE_PASSWORD"] = os.environ.get("WEBOBS_PRIVATE_CAMERA_PASSWORD", "")
    evidence.parent.mkdir(parents=True, exist_ok=True)
    baseline = REFERENCE.server_processes(control_url)

    with tempfile.TemporaryDirectory(dir=evidence.parent, prefix=".webobs-m2-lifecycle-") as raw:
        private = Path(raw)
        manifest_path = private / "one-stream.json"
        manifest_path.write_text(json.dumps(one_stream_manifest(manifest, 45)), encoding="utf-8")

        process, stdout, stderr = start_probe(arguments.client,
            ["--probe-manifest", str(manifest_path), "--probe-reconnect"], environment, private)
        disconnected = False
        try:
            wait_document(stdout, "ready", time.monotonic() + 45)
            run_private_helper(disconnect_helper, 60)
            disconnected = True
            time.sleep(3)
            reconnect_started = time.monotonic()
            run_private_helper(connect_helper, 60)
            disconnected = False
            reconnected = wait_document(stdout, "reconnected", reconnect_started + 10)
            reconnect_ms = int((time.monotonic() - reconnect_started) * 1000)
            values, output = finish_probe(process, stdout, stderr, time.monotonic() + 60)
            passed = next((item for item in reversed(values) if item.get("result") == "passed"), {})
            streams = passed.get("streams", [])
            if reconnected.get("networkReconnects") != 1 or reconnect_ms > 10_000 or \
                    not isinstance(streams, list) or len(streams) != 1 or \
                    streams[0].get("networkReconnects") != 1:
                raise RuntimeError("desktop network recovery missed its ten-second contract")
            assert_no_private_output(output, manifest)
        finally:
            if disconnected:
                run_private_helper(connect_helper, 60)
            if process.poll() is None:
                process.terminate()

        trigger = private / "lifecycle.command"
        atomic_command(trigger, "active")
        manifest_path.write_text(json.dumps(one_stream_manifest(manifest, 90)), encoding="utf-8")
        process, stdout, stderr = start_probe(arguments.client, ["--probe-manifest",
            str(manifest_path), "--probe-background-release", "--probe-foreground-resume",
            "--probe-lifecycle-trigger", str(trigger)], environment, private)
        try:
            wait_document(stdout, "ready", time.monotonic() + 45)
            release_started = time.monotonic()
            atomic_command(trigger, "background")
            released = wait_document(stdout, "background-released", release_started + 5)
            release_ms = int((time.monotonic() - release_started) * 1000)
            if released.get("streamCount") != 1 or release_ms > 5_000 or \
                    int(released.get("releaseMilliseconds", 5001)) > 5_000:
                raise RuntimeError("desktop suspend did not release media inside five seconds")
            suspend_seconds = run_private_helper(suspend_helper, 300)
            if suspend_seconds < 2:
                raise RuntimeError("desktop suspend helper returned too quickly to prove real sleep")
            resume_started = time.monotonic()
            atomic_command(trigger, "foreground")
            resumed = wait_document(stdout, "foreground-resumed", resume_started + 10)
            resume_ms = int((time.monotonic() - resume_started) * 1000)
            _, output = finish_probe(process, stdout, stderr, time.monotonic() + 15)
            if resumed.get("streamCount") != 1 or resume_ms > 10_000:
                raise RuntimeError("desktop suspend recovery exceeded ten seconds")
            assert_no_private_output(output, manifest)
        finally:
            if process.poll() is None:
                process.terminate()

        process, stdout, stderr = start_probe(arguments.client,
            ["--probe-endpoint-env", "WEBOBS_PRIVATE_RTSP_H264", "--probe-adapter", "rtsp",
             "--probe-codec", "h264", "--probe-seconds", "8",
             "--probe-force-hardware-failure"], environment, private)
        values, output = finish_probe(process, stdout, stderr, time.monotonic() + 40)
        gpu = next((item for item in reversed(values) if item.get("result") == "passed"), {})
        if gpu.get("hardwareDecode") is not False or \
                gpu.get("fallbackReason") != "hardware_decoder_failed_software_fallback" or \
                int(gpu.get("pipelineRestarts", 0)) != 1 or int(gpu.get("framesDecoded", 0)) < 8:
            raise RuntimeError("desktop GPU failure did not prove bounded software fallback")
        assert_no_private_output(output, manifest)

        camera_id = os.environ.get("WEBOBS_DESKTOP_GRANT_CAMERA_ID", "")
        profile_id = os.environ.get("WEBOBS_DESKTOP_GRANT_PROFILE_ID", "")
        if not camera_id or not profile_id:
            raise ValueError("desktop offline startup requires granted Camera/Profile IDs")
        client_id = ""
        enrollment_started = int(time.time())
        process, stdout, stderr = start_probe(arguments.client,
            ["--probe-client-auth", "--probe-preserve-identity",
             "--probe-control-url", control_url, "--probe-camera-id", camera_id,
             "--probe-profile-id", profile_id], environment, private)
        try:
            pairing = wait_document(stdout, "pairing-required", time.monotonic() + 30)
            if pairing.get("temporaryIdentity") is not False or pairing.get(
                    "storageBackend") not in {"windows-dpapi", "linux-secret-service"} or \
                    not re.fullmatch(r"[0-9]{8}", str(pairing.get("pairingCode", ""))):
                raise RuntimeError("desktop offline identity was not stored by the platform backend")
            status, pending = control_json("GET", control_url, "/api/v2/enrollments")
            expected_platform = "windows" if sys.platform == "win32" else "linux"
            candidates = [item for item in pending.get("enrollments", [])
                if isinstance(item, dict) and item.get("name") == "Desktop authorization gate" and
                item.get("platform") == expected_platform and item.get("state") == "pending" and
                int(item.get("createdAt", 0)) >= enrollment_started]
            if status != 200 or len(candidates) != 1:
                raise RuntimeError("desktop enrollment was not uniquely pending")
            enrollment_id = str(candidates[0].get(
                "enrollmentId", candidates[0].get("id", "")))
            status, approval = control_json("POST", control_url,
                f"/api/v2/enrollments/{enrollment_id}/approve", {"pairingCode": pairing[
                    "pairingCode"], "cameraGrants": [{"cameraId": camera_id,
                    "profileIds": [profile_id], "permissions": ["view"],
                    "credentialMode": "existing"}]})
            client_id = str(approval.get("clientId", ""))
            if status != 200 or not re.fullmatch(r"[0-9a-f]{32}", client_id):
                raise RuntimeError("desktop offline enrollment approval failed")
            wait_document(stdout, "authorization-preserved", time.monotonic() + 45)
            _, output = finish_probe(process, stdout, stderr, time.monotonic() + 10)
            assert_no_private_output(output, manifest)

            process, stdout, stderr = start_probe(arguments.client,
                ["--probe-offline-startup", "--probe-camera-id", camera_id,
                 "--probe-profile-id", profile_id], environment, private)
            offline = wait_document(stdout, "offline-startup-ready", time.monotonic() + 30)
            _, output = finish_probe(process, stdout, stderr, time.monotonic() + 10)
            if offline.get("streamCount") != 1 or offline.get("topology") != "true-direct":
                raise RuntimeError("desktop offline startup did not restore True Direct playback")
            assert_no_private_output(output, manifest)
        finally:
            if process.poll() is None:
                process.terminate()
            if client_id:
                status, revoked = control_json("DELETE", control_url,
                                               f"/api/v2/clients/{client_id}")
                if status != 200 or revoked.get("status") != "revoked":
                    raise RuntimeError("desktop offline test client could not be revoked")

    final_server = REFERENCE.server_processes(control_url)
    if not REFERENCE.same_server_media(baseline, final_server):
        raise RuntimeError("desktop lifecycle qualification changed server media sessions")
    document = {"schemaVersion": 1, "result": "passed", "platform": platform.platform(),
        "networkReconnectMilliseconds": reconnect_ms, "suspendHelperSeconds": round(
            suspend_seconds, 3), "suspendReleaseMilliseconds": release_ms,
        "resumeMilliseconds": resume_ms, "gpuFallbackReason": gpu["fallbackReason"],
        "gpuPipelineRestarts": gpu["pipelineRestarts"]}
    document["offlineStartup"] = offline.get("result") == "offline-startup-ready"
    REFERENCE.validate_evidence_path(evidence)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=evidence.parent,
                                     prefix=".webobs-m2-lifecycle-", suffix=".tmp",
                                     delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(document, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    if os.name != "nt":
        temporary.chmod(0o600)
    os.link(temporary, evidence)
    temporary.unlink()
    print("v2-M2 desktop lifecycle gate passed: network recovery, real suspend/release/resume, "
          "GPU software fallback, offline startup, and zero incremental server media.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
