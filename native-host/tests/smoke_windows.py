#!/usr/bin/env python3
"""Actual Windows Qt/plugin/portable startup smoke; never camera qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from typing import Sequence


PRODUCT_URLS = tuple(f"rtsp://127.0.0.1:9/smoke-{index}" for index in range(1, 6))
FORBIDDEN_PROCESS_NAMES = frozenset({"ffmpeg.exe", "go2rtc.exe", "mediamtx.exe", "python.exe", "python3.exe",
                                     "node.exe", "caddy.exe", "webobs.exe", "electron.exe"})
SERVICE_LISTENER_PORTS = frozenset({80, 443, 1984, 8554, 8555, 8888, 9000, 8080})


def product_config_payload() -> dict:
    cameras = [{"id": f"cam-{index}", "name": f"Smoke Camera {index}", "url": PRODUCT_URLS[index - 1],
                "hardwareDecode": False} for index in range(1, 6)]
    return {"schema": 1, "cameras": cameras}


def write_product_config(path: Path) -> None:
    """Write the product camera config a real installation would ship privately."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(product_config_payload()), encoding="utf-8")


def check_product_receipt(receipt_path: Path, urls: Sequence[str] = PRODUCT_URLS, *, expect_created: int = 5,
                          expect_reused: int = 0, expect_scene_reused: bool | None = None) -> dict:
    """Validate the URL-free bootstrap receipt; never leak or print camera URLs."""
    text = receipt_path.read_text(encoding="utf-8")
    receipt = json.loads(text)
    if receipt.get("ok") is not True or receipt.get("created") != expect_created or receipt.get("items") != 5:
        raise AssertionError("Product camera bootstrap created/reused an unexpected number of sources")
    if receipt.get("reused") != expect_reused or receipt.get("canvasApplied") not in (True, False):
        raise AssertionError("Product camera bootstrap reuse/canvas flag mismatch")
    if expect_scene_reused is not None and receipt.get("sceneReused") is not expect_scene_reused:
        raise AssertionError("Product camera bootstrap wall reuse mismatch")
    if "error" in receipt:
        raise AssertionError("Product camera bootstrap reported an error")
    for url in urls:
        if url in text:
            raise AssertionError("Product bootstrap receipt leaked a camera URL")
    return receipt


def launch_once(runtime: Path, pwsh: str, environment: dict, token: str, product_file: Path,
                receipt: str, reuse: bool = False, gate: Path | None = None) -> None:
    args = [pwsh, "-NoProfile", "-File", str(runtime / "launch-native.ps1"), "-AllowPrototype",
            "-SmokeToken", token, "-TimeoutSeconds", "90", "-ProductConfig", str(product_file)]
    if gate is not None:
        args.extend(["-ProcessGatePath", str(gate)])
    if reuse:
        args.append("-ReuseProfile")
    environment = dict(environment)
    environment["WEBOBS_NATIVE_SMOKE_RECEIPT"] = receipt
    process = subprocess.run(args, cwd=runtime.parent, env=environment, check=False)
    if process.returncode:
        raise RuntimeError(f"Native startup/normal close failed with exit code {process.returncode}")


def check_process_gate(path: Path) -> dict:
    """Reject helper services and post-exit orphans observed around one real OBS launch."""
    gate = json.loads(path.read_text(encoding="utf-8"))
    if gate.get("schema") != 1 or gate.get("samples", 0) < 1:
        raise AssertionError("Native process gate did not sample the running process tree")
    names = [str(item.get("name", "")).lower() for item in gate.get("observed", [])]
    forbidden = sorted(set(names) & FORBIDDEN_PROCESS_NAMES)
    if forbidden:
        raise AssertionError(f"Native host started unrelated helper processes: {forbidden}")
    orphans = gate.get("orphans", [])
    if orphans:
        raise AssertionError(f"Native host left {len(orphans)} process(es) after normal exit: "
                             + ", ".join(sorted({str(item.get('name', '?')) for item in orphans})))
    service_ports = sorted({int(item.get("port", 0)) for item in gate.get("listeners", [])
                            if int(item.get("port", 0)) in SERVICE_LISTENER_PORTS})
    if service_ports:
        raise AssertionError(f"Native host opened gateway/website listener ports: {service_ports}")
    return {"schema": 1, "samples": int(gate.get("samples", 0)),
            "observedNames": sorted(set(names)), "serviceListenerPorts": [],
            "orphanCount": 0}


def verify_smoke(receipt_path: Path, token: str, profile: Path) -> dict:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("token") != token or receipt.get("obsVersion") != "32.1.2" or receipt.get("qtPlatform") != "windows":
        raise AssertionError("Native plugin identity/token mismatch")
    if Path(receipt["profile"]).resolve() != profile or Path(receipt["moduleConfig"]).resolve() != profile / "plugin_config/webobs-native-host":
        raise AssertionError("OBS reported a non-portable plugin configuration path")
    for flag in ("dockLoaded", "mediaSourceRegistered", "finishedLoading"):
        if receipt.get(flag) is not True:
            raise AssertionError(f"Native startup receipt missing {flag}")
    if receipt.get("mediaQualified") is not False:
        raise AssertionError("A startup smoke cannot qualify media")
    if not (profile / "global.ini").is_file() or not (profile / "user.ini").is_file():
        raise AssertionError("Portable OBS did not persist its own configuration")
    return receipt


def fingerprint(root: Path) -> dict:
    """Private before/after comparison, never print paths or file contents."""
    if not root.exists():
        return {}
    if root.is_symlink():
        raise ValueError("Refuse an external OBS profile symlink")
    state = {}
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("Refuse symlinks in the external OBS profile")
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if len(state) >= 10000 or total > 64 * 1024 * 1024:
            raise ValueError("External OBS profile too large for bounded isolation smoke; use a dedicated Windows test account")
        state[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return state


def run(runtime: Path, result: Path, *, existing_wall: bool = False) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("The Qt startup smoke requires actual Windows x64")
    profile = (runtime / "config/obs-studio").resolve()
    if existing_wall:
        if not profile.is_dir() or not (profile / "global.ini").is_file() or not (profile / "user.ini").is_file():
            raise ValueError("Existing-wall smoke requires an installed private portable profile")
    elif (runtime / "config").exists():
        raise ValueError("Use a NEW disposable runtime; never overwrite private configuration")
    if result.exists():
        raise ValueError("Use a NEW result path")
    pwsh = shutil.which("pwsh")
    if not pwsh:
        raise RuntimeError("PowerShell 7.2+ is required")
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is required for private before/after isolation verification")
    external = Path(appdata) / "obs-studio"
    before = fingerprint(external)
    token = secrets.token_hex(16)
    environment = os.environ.copy()
    # The real launcher must remove these, including Qt's plugin override.
    for name in ("OBS_PLUGINS_PATH", "OBS_PLUGINS_DATA_PATH", "OBS_CONFIG_PATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        environment[name] = str(runtime / "deliberately-nonexistent-external-override")
    product_file = (result.parent / (result.stem + "-product.json")).resolve()
    write_product_config(product_file)
    first_name = f"native-smoke-{token[:12]}-first.json"
    second_name = f"native-smoke-{token[:12]}-second.json"
    gate_path = result.parent / (result.stem + "-process-gate.json")
    try:
        launch_once(runtime, pwsh, environment, token, product_file, first_name, reuse=existing_wall,
                    gate=gate_path)
        process_gate = check_process_gate(gate_path)
        first_receipt = verify_smoke(profile / first_name, token, profile)
        product = check_product_receipt(
            profile / "plugin_config/webobs-native-host/product-bootstrap.json",
            expect_created=0 if existing_wall else 5,
            expect_reused=5 if existing_wall else 0,
            expect_scene_reused=True if existing_wall else None)
        if existing_wall:
            second = product
        else:
            launch_once(runtime, pwsh, environment, token, product_file, second_name, reuse=True)
            verify_smoke(profile / second_name, token, profile)
            second = check_product_receipt(profile / "plugin_config/webobs-native-host/product-bootstrap.json",
                                           expect_created=0, expect_reused=5, expect_scene_reused=True)
    finally:
        product_file.unlink(missing_ok=True)
    if fingerprint(external) != before:
        raise AssertionError("External OBS profile changed during native portable smoke; do not publish private files")
    qualification = ("Single launch over an installed private profile: reuse only; "
                     "no camera/pixel/performance/auth/upgrade claim") if existing_wall else (
        "Two launches in one disposable profile: fresh product creation then reuse; "
        "no camera/pixel/performance/auth/upgrade claim")
    summary = {"schema": 1, "status": "passed", "existingWallMode": existing_wall,
               "obsVersion": "32.1.2", "qtVersion": first_receipt["qtVersion"],
               "dockLoaded": True, "mediaSourceRegistered": True, "normalExit": True,
               "portableProfile": True, "externalObsProfileUnchanged": True,
               "productCameraCreated": product["created"], "productCameraReused": product["reused"],
               "productCameraCreatedSecond": second["created"], "productCameraReusedSecond": second["reused"],
               "productSceneReusedSecond": second["sceneReused"],
               "inheritedPluginOverridesCleared": True, "mediaQualified": False,
               "processGate": process_gate, "qualification": qualification}
    with result.open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2)
        output.write("\n")
    print(json.dumps(summary, indent=2))
    return summary


def _obs64_count() -> int:
    output = subprocess.run(["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/FO", "CSV", "/NH"],
                            check=False, capture_output=True, text=True).stdout
    return sum(1 for line in output.splitlines() if "obs64.exe" in line)


def run_second_instance(runtime: Path, result: Path, *, hold_seconds: int = 30) -> dict:
    """Hold one real host, prove the launcher refuses a second one, then contain the first."""
    if sys.platform != "win32":
        raise RuntimeError("The second-instance smoke requires actual Windows x64")
    if (runtime / "config").exists():
        raise ValueError("Second-instance smoke requires a NEW disposable runtime; never overwrite private configuration")
    if result.exists():
        raise ValueError("Use a NEW result path")
    pwsh = shutil.which("pwsh")
    if not pwsh:
        raise RuntimeError("PowerShell 7.2+ is required")
    environment = os.environ.copy()
    for name in ("WEBOBS_NATIVE_SMOKE_TOKEN", "WEBOBS_NATIVE_SMOKE_RECEIPT", "WEBOBS_NATIVE_PIXEL_TOKEN",
                 "WEBOBS_NATIVE_RESTART_TOKEN", "OBS_PLUGINS_PATH", "OBS_PLUGINS_DATA_PATH", "OBS_CONFIG_PATH",
                 "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        environment.pop(name, None)
    gate_path = result.parent / (result.stem + "-process-gate.json")
    product_file = (result.parent / (result.stem + "-product.json")).resolve()
    write_product_config(product_file)
    first_args = [pwsh, "-NoProfile", "-File", str(runtime / "launch-native.ps1"), "-AllowPrototype",
                  "-CrashProbe", "-TimeoutSeconds", "120", "-CrashAfterSeconds", str(hold_seconds),
                  "-ProcessGatePath", str(gate_path), "-ProductConfig", str(product_file)]
    second_args = [pwsh, "-NoProfile", "-File", str(runtime / "launch-native.ps1"), "-AllowPrototype"]
    try:
        first = subprocess.Popen(first_args, cwd=runtime.parent, env=environment)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline and _obs64_count() < 1:
                time.sleep(0.5)
            if _obs64_count() < 1:
                raise AssertionError("The first host never started")
            time.sleep(4)
            hosts_before = _obs64_count()
            started = time.monotonic()
            second = subprocess.run(second_args, cwd=runtime.parent, env=environment, check=False,
                                    capture_output=True, text=True, timeout=60)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            time.sleep(1)
            hosts_after = _obs64_count()
        finally:
            first.wait(timeout=120)
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        if second.returncode != 0:
            raise AssertionError(f"The refused second launcher exited {second.returncode}: {second.stderr[-400:]}")
        if "already running" not in (second.stdout + second.stderr).lower():
            raise AssertionError(f"The second launcher did not report the single-instance refusal: {second.stdout[-400:]}")
        if elapsed_ms > 20000:
            raise AssertionError(f"The second launcher was not refused promptly: {elapsed_ms} ms")
        if hosts_before != 1 or hosts_after != 1:
            raise AssertionError(f"Expected exactly one real host before/after the refusal, saw {hosts_before}/{hosts_after}")
        if gate.get("crashed") is not True or int(gate.get("samples", 0)) < 2:
            raise AssertionError(f"The held first host was not deliberately killed: {gate.get('crashed')}/{gate.get('samples')}")
        checked = check_process_gate(gate_path)
        summary = {"schema": 1, "kind": "native-second-instance-smoke", "status": "passed",
                   "holdSeconds": hold_seconds, "secondExitCode": int(second.returncode),
                   "secondElapsedMs": elapsed_ms, "hostsBefore": hosts_before, "hostsAfter": hosts_after,
                   "refused": True, "processGate": checked,
                   "qualification": "Launcher-level single instance only: no camera, pixel, performance, auth or upgrade claim"}
        with result.open("x", encoding="utf-8") as output:
            json.dump(summary, output, indent=2)
            output.write("\n")
        print(json.dumps(summary, indent=2))
        return summary
    finally:
        product_file.unlink(missing_ok=True)


def run_crash(runtime: Path, result: Path, *, crash_after: int = 8) -> dict:
    """Kill the real OBS host and require no surviving process from the install root."""
    if sys.platform != "win32":
        raise RuntimeError("The crash containment smoke requires actual Windows x64")
    if (runtime / "config").exists():
        raise ValueError("Crash smoke requires a NEW disposable runtime; never overwrite private configuration")
    if result.exists():
        raise ValueError("Use a NEW result path")
    pwsh = shutil.which("pwsh")
    if not pwsh:
        raise RuntimeError("PowerShell 7.2+ is required")
    environment = os.environ.copy()
    for name in ("OBS_PLUGINS_PATH", "OBS_PLUGINS_DATA_PATH", "OBS_CONFIG_PATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        environment[name] = str(runtime / "deliberately-nonexistent-external-override")
    gate_path = result.parent / (result.stem + "-process-gate.json")
    product_file = (result.parent / (result.stem + "-product.json")).resolve()
    write_product_config(product_file)
    args = [pwsh, "-NoProfile", "-File", str(runtime / "launch-native.ps1"), "-AllowPrototype",
            "-CrashProbe", "-TimeoutSeconds", "120", "-CrashAfterSeconds", str(crash_after),
            "-ProcessGatePath", str(gate_path), "-ProductConfig", str(product_file)]
    try:
        process = subprocess.run(args, cwd=runtime.parent, env=environment, check=False)
    finally:
        product_file.unlink(missing_ok=True)
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if gate.get("crashed") is not True:
        raise AssertionError(f"Crash smoke launcher did not record the deliberate kill "
                             f"(exit={process.returncode}, samples={gate.get('samples')}, "
                             f"observed={[item.get('name') for item in gate.get('observed', [])]})")
    if int(gate.get("samples", 0)) < 2:
        raise AssertionError("Crash smoke did not sample the running process tree before the kill")
    checked = check_process_gate(gate_path)
    summary = {"schema": 1, "kind": "native-crash-smoke", "status": "passed",
               "crashAfterSeconds": crash_after, "exitCode": int(process.returncode),
               "processGate": checked,
               "qualification": "Deliberate host kill only: no camera, pixel, performance, auth or upgrade claim"}
    with result.open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2)
        output.write("\n")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--existing-wall", action="store_true",
                        help="existing installed profile already owns the five-camera wall")
    parser.add_argument("--crash-smoke", action="store_true",
                        help="deliberately kill the host and require no surviving process")
    parser.add_argument("--crash-after-seconds", type=int, default=8)
    parser.add_argument("--second-instance-smoke", action="store_true",
                        help="hold one host and require the launcher to refuse a second one")
    parser.add_argument("--hold-seconds", type=int, default=30)
    args = parser.parse_args()
    if args.second_instance_smoke:
        run_second_instance(args.runtime.resolve(), args.result.resolve(), hold_seconds=args.hold_seconds)
    elif args.crash_smoke:
        run_crash(args.runtime.resolve(), args.result.resolve(), crash_after=args.crash_after_seconds)
    else:
        run(args.runtime.resolve(), args.result.resolve(), existing_wall=args.existing_wall)
