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


def launch_probe(serial: str, remote_manifest: str, background: bool,
                 reconnect: bool = False, microphone_permission: bool = False,
                 foreground_resume: bool = False) -> None:
    adb(serial, "shell", "am", "force-stop", PACKAGE)
    adb(serial, "logcat", "-c")
    adb(serial, "shell", "am", "instrument", "-w", "-r",
        "-e", "manifestPath", remote_manifest,
        "-e", "backgroundRelease", "true" if background else "false",
        "-e", "reconnect", "true" if reconnect else "false",
        "-e", "foregroundResume", "true" if foreground_resume else "false",
        "-e", "microphonePermission", "true" if microphone_permission else "false",
        INSTRUMENTATION, timeout=60)


def resume_probe(serial: str, remote_manifest: str) -> None:
    adb(serial, "shell", "am", "instrument", "-w", "-r",
        "-e", "manifestPath", remote_manifest,
        "-e", "resumeOnly", "true", INSTRUMENTATION, timeout=60)


def wait_for_document(serial: str, result: str, deadline: float) -> tuple[str, dict]:
    last_log = ""
    while time.monotonic() < deadline:
        last_log, documents = log_documents(serial)
        for document in reversed(documents):
            if document.get("result") == result:
                return last_log, document
        time.sleep(1)
    raise RuntimeError(f"Android client did not emit bounded {result!r} evidence")


def wait_for_reconnections(serial: str, expected_names: set[str],
                           deadline: float) -> tuple[str, set[str]]:
    observed: set[str] = set()
    last_log = ""
    while time.monotonic() < deadline:
        last_log, documents = log_documents(serial)
        for document in documents:
            if document.get("result") == "reconnected" and \
                    isinstance(document.get("name"), str):
                observed.add(document["name"])
        if observed == expected_names:
            return last_log, observed
        time.sleep(0.5)
    raise RuntimeError("Android streams did not all reconnect inside the ten-second budget")


def android_setting(serial: str, namespace: str, name: str) -> str:
    return adb(serial, "shell", "settings", "get", namespace, name).strip()


def put_android_setting(serial: str, namespace: str, name: str, value: str) -> None:
    adb(serial, "shell", "settings", "put", namespace, name, value)


def wifi_enabled(serial: str) -> bool | None:
    output = adb(serial, "shell", "cmd", "wifi", "status", check=False).lower()
    if "wi-fi is enabled" in output or "wifi is enabled" in output:
        return True
    if "wi-fi is disabled" in output or "wifi is disabled" in output:
        return False
    value = android_setting(serial, "global", "wifi_on")
    return True if value == "1" else False if value == "0" else None


def set_wifi_enabled(serial: str, enabled: bool, deadline_seconds: float = 30) -> None:
    adb(serial, "shell", "svc", "wifi", "enable" if enabled else "disable", check=False)
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if wifi_enabled(serial) is enabled:
            return
        time.sleep(0.5)
    raise RuntimeError("reference device Wi-Fi state did not reach the requested value")


def package_installed(serial: str, package: str) -> bool:
    output = adb(serial, "shell", "pm", "path", package, check=False)
    return any(line.startswith("package:") for line in output.splitlines())


def validate_private_helper(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("VPN helper must remain outside the public worktree")
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ValueError("VPN helper must be an executable private file")
    return resolved


def run_private_helper(path: Path, serial: str) -> None:
    helper_environment = {name: os.environ[name] for name in (
        "PATH", "LANG", "LC_ALL", "ANDROID_HOME", "ANDROID_SDK_ROOT",
        "ADB_SERVER_SOCKET") if name in os.environ}
    result = subprocess.run([str(path), serial], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=60, check=False,
                            env=helper_environment, cwd=path.parent)
    if result.returncode != 0 or result.stdout or result.stderr:
        raise RuntimeError("private VPN helper failed or emitted unsafe output")


def emit_network_status(serial: str, remote_manifest: str) -> None:
    adb(serial, "shell", "am", "instrument", "-w", "-r",
        "-e", "manifestPath", remote_manifest,
        "-e", "resumeOnly", "true", "-e", "networkStatus", "true",
        INSTRUMENTATION, timeout=60)


def wait_for_network_status(serial: str, remote_manifest: str, expected: str,
                            deadline: float) -> dict:
    while time.monotonic() < deadline:
        emit_network_status(serial, remote_manifest)
        _, documents = log_documents(serial)
        for document in reversed(documents):
            if document.get("result") == "network-status" and \
                    document.get("status") == expected:
                return document
        time.sleep(0.5)
    raise RuntimeError(f"Android network status did not become {expected!r}")


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
    parser.add_argument("--vpn-connect-helper", type=Path, required=True)
    parser.add_argument("--vpn-disconnect-helper", type=Path, required=True)
    parser.add_argument("--control-url", default=os.environ.get("WEBOBS_REFERENCE_CONTROL_URL", ""))
    arguments = parser.parse_args()
    for artifact in (arguments.apk, arguments.driver_apk, arguments.manifest,
                     arguments.apksigner):
        if not artifact.is_file():
            raise SystemExit(f"required private gate input is missing: {artifact.name}")
    manifest = validate_manifest(DESKTOP.unique_json(arguments.manifest))
    try:
        vpn_connect_helper = validate_private_helper(arguments.vpn_connect_helper)
        vpn_disconnect_helper = validate_private_helper(arguments.vpn_disconnect_helper)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
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
    if state != "device" or api < 29 or abi != "arm64-v8a" or \
            ":" in arguments.serial or "_adb-tls" in arguments.serial:
        raise SystemExit("reference device must be an authorized API 29+ arm64-v8a device")
    if package_installed(arguments.serial, PACKAGE) or \
            package_installed(arguments.serial, DRIVER):
        raise SystemExit("dedicated reference device must not contain a prior client or driver")

    digest = hashlib.sha256(arguments.manifest.read_bytes()).hexdigest()[:16]
    remote = f"/data/local/tmp/webobs-m3-{digest}.json"
    baseline = DESKTOP.server_processes(control_url)
    temperatures: list[int] = []
    server_samples = 0
    final_log = ""
    original_accelerometer_rotation = android_setting(
        arguments.serial, "system", "accelerometer_rotation")
    original_user_rotation = android_setting(arguments.serial, "system", "user_rotation")
    rotation_steps = {3: "1", 6: "0", 9: "3", 12: "0"}
    rotations_tested = 0
    wifi_toggled = False
    client_installed = False
    driver_installed = False
    vpn_connected = False
    try:
        adb(arguments.serial, "install", "-r", "--no-streaming", str(arguments.apk), timeout=180)
        client_installed = True
        adb(arguments.serial, "install", "-r", "--no-streaming", str(arguments.driver_apk), timeout=120)
        driver_installed = True
        adb(arguments.serial, "push", str(arguments.manifest), remote, timeout=60)
        adb(arguments.serial, "shell", "chmod", "0644", remote)
        put_android_setting(arguments.serial, "system", "accelerometer_rotation", "0")
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
            if server_samples in rotation_steps:
                put_android_setting(arguments.serial, "system", "user_rotation",
                                    rotation_steps[server_samples])
                rotations_tested += 1
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

        reconnect_manifest = dict(manifest)
        reconnect_manifest["durationSeconds"] = 75
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json",
                                         delete=False) as handle:
            reconnect_path = Path(handle.name)
            json.dump(reconnect_manifest, handle)
        try:
            adb(arguments.serial, "push", str(reconnect_path), remote, timeout=60)
        finally:
            reconnect_path.unlink(missing_ok=True)
        if wifi_enabled(arguments.serial) is not True:
            raise RuntimeError("Android lifecycle gate requires an enabled USB-controlled Wi-Fi device")
        launch_probe(arguments.serial, remote, False, reconnect=True)
        wait_for_document(arguments.serial, "ready", time.monotonic() + 45)
        set_wifi_enabled(arguments.serial, False)
        wifi_toggled = True
        time.sleep(5)
        reconnect_started = time.monotonic()
        set_wifi_enabled(arguments.serial, True)
        reconnect_log, reconnected_names = wait_for_reconnections(
            arguments.serial, {item["name"] for item in manifest["streams"]},
            reconnect_started + 10)
        reconnect_wall_ms = int((time.monotonic() - reconnect_started) * 1000)
        _, reconnect_passed = wait_for_document(
            arguments.serial, "passed", time.monotonic() + 80)
        reconnect_results = reconnect_passed.get("streams")
        if reconnect_wall_ms > 10_000 or len(reconnected_names) != 9 or \
                not isinstance(reconnect_results, list) or len(reconnect_results) != 9 or \
                any(not isinstance(item, dict) or int(item.get("networkReconnects", 0)) < 1
                    for item in reconnect_results):
            raise RuntimeError("Android Wi-Fi recovery did not prove all nine stream reconnections")
        if any(stream["endpoint"] in reconnect_log for stream in manifest["streams"]):
            raise RuntimeError("Android reconnect log exposed a private endpoint")
        if not DESKTOP.same_server_media(baseline, DESKTOP.server_processes(control_url)):
            raise RuntimeError("Android reconnect gate changed server media sessions")

        vpn_manifest = dict(manifest)
        vpn_manifest["durationSeconds"] = 60
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json",
                                         delete=False) as handle:
            vpn_path = Path(handle.name)
            json.dump(vpn_manifest, handle)
        try:
            adb(arguments.serial, "push", str(vpn_path), remote, timeout=60)
        finally:
            vpn_path.unlink(missing_ok=True)
        launch_probe(arguments.serial, remote, False, reconnect=True)
        wait_for_document(arguments.serial, "ready", time.monotonic() + 45)
        run_private_helper(vpn_connect_helper, arguments.serial)
        vpn_connected = True
        wait_for_network_status(arguments.serial, remote, "vpn", time.monotonic() + 15)
        run_private_helper(vpn_disconnect_helper, arguments.serial)
        vpn_connected = False
        wait_for_network_status(arguments.serial, remote, "wifi", time.monotonic() + 15)
        vpn_log, vpn_passed = wait_for_document(
            arguments.serial, "passed", time.monotonic() + 75)
        if vpn_passed.get("processCount") != 1 or \
                len(vpn_passed.get("streams", [])) != 9:
            raise RuntimeError("Android VPN handoff did not preserve all nine streams")
        if any(stream["endpoint"] in vpn_log for stream in manifest["streams"]):
            raise RuntimeError("Android VPN handoff log exposed a private endpoint")
        if not DESKTOP.same_server_media(baseline, DESKTOP.server_processes(control_url)):
            raise RuntimeError("Android VPN handoff changed server media sessions")

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
        launch_probe(arguments.serial, remote, True, foreground_resume=True)
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
        foreground_started = time.monotonic()
        resume_probe(arguments.serial, remote)
        foreground_log, resumed = wait_for_document(
            arguments.serial, "foreground-resumed", foreground_started + 10)
        foreground_resume_wall_ms = int((time.monotonic() - foreground_started) * 1000)
        if int(resumed.get("streamCount", 0)) != 9 or foreground_resume_wall_ms > 10_000:
            raise RuntimeError("Android foreground stream recovery exceeded ten seconds")
        if any(stream["endpoint"] in foreground_log for stream in manifest["streams"]):
            raise RuntimeError("Android foreground recovery log exposed a private endpoint")

        launch_probe(arguments.serial, remote, True)
        wait_for_document(arguments.serial, "ready", time.monotonic() + 45)
        lock_started = time.monotonic()
        adb(arguments.serial, "shell", "input", "keyevent", "KEYCODE_SLEEP")
        try:
            lock_log, lock_released = wait_for_document(
                arguments.serial, "background-released", lock_started + 5.5)
        finally:
            adb(arguments.serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP", check=False)
            adb(arguments.serial, "shell", "wm", "dismiss-keyguard", check=False)
        lock_release_wall_ms = int((time.monotonic() - lock_started) * 1000)
        if int(lock_released.get("streamCount", 0)) != 9 or \
                int(lock_released.get("releaseMilliseconds", 6000)) > 5000 or \
                lock_release_wall_ms > 5500:
            raise RuntimeError("Android lock-screen resource release exceeded five seconds")
        if any(stream["endpoint"] in lock_log for stream in manifest["streams"]):
            raise RuntimeError("Android lock-screen log exposed a private endpoint")

        adb(arguments.serial, "shell", "pm", "revoke", PACKAGE,
            "android.permission.RECORD_AUDIO", check=False)
        adb(arguments.serial, "shell", "appops", "set", PACKAGE, "RECORD_AUDIO", "deny",
            check=False)
        launch_probe(arguments.serial, remote, False, microphone_permission=True)
        _, denied_permission = wait_for_document(
            arguments.serial, "microphone-permission", time.monotonic() + 30)
        if denied_permission.get("granted") is not False:
            raise RuntimeError("Android microphone-denial boundary did not fail closed")
        adb(arguments.serial, "shell", "am", "force-stop", PACKAGE)
        adb(arguments.serial, "shell", "appops", "set", PACKAGE, "RECORD_AUDIO", "allow")
        adb(arguments.serial, "shell", "pm", "grant", PACKAGE,
            "android.permission.RECORD_AUDIO")
        launch_probe(arguments.serial, remote, False, microphone_permission=True)
        _, granted_permission = wait_for_document(
            arguments.serial, "microphone-permission", time.monotonic() + 30)
        if granted_permission.get("granted") is not True:
            raise RuntimeError("Android microphone grant was not observed by the client boundary")
        adb(arguments.serial, "shell", "am", "force-stop", PACKAGE)
        final_server = DESKTOP.server_processes(control_url)
        if not DESKTOP.same_server_media(baseline, final_server):
            raise RuntimeError("Android gate left incremental server media sessions")
        write_evidence(arguments.evidence, {"schemaVersion": 1, "result": "passed",
            "apiLevel": api, "abi": abi, "durationSeconds": 1800, "streamCount": 9,
            "serverSamples": server_samples, "maxThermalStatus": max(temperatures),
            "backgroundReleaseMilliseconds": int(released["releaseMilliseconds"]),
            "backgroundReleaseWallMilliseconds": release_wall_ms,
            "foregroundResumeWallMilliseconds": foreground_resume_wall_ms,
            "lockScreenReleaseMilliseconds": int(lock_released["releaseMilliseconds"]),
            "lockScreenReleaseWallMilliseconds": lock_release_wall_ms,
            "wifiReconnectMilliseconds": reconnect_wall_ms,
            "wifiReconnectedStreams": len(reconnected_names),
            "vpnHandoff": "vpn-to-wifi",
            "rotationsTested": rotations_tested,
            "microphoneDeniedThenGranted": True, "streams": evidence_streams,
            "serverRtspSessionsBefore": baseline["rtspSessions"],
            "serverRtspSessionsAfter": final_server["rtspSessions"]})
        print("v2-M3 Android reference gate passed: 9 MediaCodec streams for 30 minutes, "
              "<2% drops, four rotations, <=10s Wi-Fi recovery, VPN handoff, no severe "
              "thermal state, zero server media increment, and bounded lifecycle release/resume.")
        return 0
    finally:
        try:
            if vpn_connected:
                try:
                    run_private_helper(vpn_disconnect_helper, arguments.serial)
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    pass
            if wifi_toggled:
                set_wifi_enabled(arguments.serial, True)
            if original_accelerometer_rotation in {"0", "1"}:
                put_android_setting(arguments.serial, "system", "accelerometer_rotation",
                                    original_accelerometer_rotation)
            if original_user_rotation in {"0", "1", "2", "3"}:
                put_android_setting(arguments.serial, "system", "user_rotation",
                                    original_user_rotation)
        finally:
            adb(arguments.serial, "shell", "rm", "-f", remote, check=False)
            if driver_installed:
                adb(arguments.serial, "uninstall", DRIVER, check=False)
            if client_installed:
                adb(arguments.serial, "uninstall", PACKAGE, check=False)


if __name__ == "__main__":
    sys.exit(main())
