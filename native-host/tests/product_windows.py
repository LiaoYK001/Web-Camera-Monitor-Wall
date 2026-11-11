#!/usr/bin/env python3
"""Actual native product entry/Qt/account lifecycle in a new private profile.

This gate drives the shipped controls through Windows UI Automation. It does not
claim installed-product, real-camera, performance or hardware-decode acceptance.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def read_json(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 262144:
        raise ValueError("missing or invalid private state")
    return json.loads(path.read_text(encoding="utf-8"))


def wait_for(predicate, message, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.1)
    raise AssertionError(message)


def alive(pid):
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


def exercise(runtime, report):
    if os.name != "nt":
        raise ValueError("actual Windows product gate requires Windows")
    manifest = read_json(runtime / "webobs-native-prototype.json")
    component_receipt = runtime / "product-components.json"
    if component_receipt.is_symlink() or component_receipt.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("missing or oversized component receipt")
    components = json.loads(component_receipt.read_text(encoding="utf-8"))
    if manifest.get("productIntegration") is not True or manifest.get("publicationForbidden") is not True:
        raise ValueError("internal integrated build required")
    if components.get("fullFeatureMigrationQualified") is not False:
        raise ValueError("R1 test must not imply a complete product")
    powershell = shutil.which("pwsh")
    if not powershell:
        raise ValueError("test-side PowerShell 7 required")
    evidence = {"schema": 1, "kind": "native-product-entry-ui", "sourceRevision": components["sourceRevision"],
        "version": manifest["version"], "passed": False, "checks": [],
        "installedProductQualified": False, "mediaQualified": False, "hardwareDecodeVerified": False,
        "fullFeatureMigrationQualified": False}
    phase = "prepare"
    with tempfile.TemporaryDirectory(prefix="WebOBS 产品接线-") as temporary:
        private = Path(temporary)
        profile = private / "profile"
        environment = dict(os.environ)
        environment["WEBOBS_PRODUCT_TEST_ROOT"] = str(profile)
        account = {"username": "native-owner", "password": secrets.token_urlsafe(24)}
        entry = runtime / "bin/webobs-wall.exe"
        process = None
        known_pids = []
        status_path = profile / "run/native-status.json"

        def status():
            try:
                return read_json(status_path)
            except (OSError, ValueError):
                return {}

        def state():
            paths = list((profile / "native-profile").rglob("product-state.json"))
            if len(paths) != 1:
                return {}
            try:
                value = read_json(paths[0])
                return value if value.get("pid") == str(frontend_pid) else {}
            except (OSError, ValueError):
                return {}

        def ui(action, **fields):
            result = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                str(HERE / "product-ui.ps1"), "-FrontendPid", str(frontend_pid)],
                input=json.dumps({"action": action, **fields}), capture_output=True, text=True,
                encoding="utf-8", timeout=25)
            try:
                reply = json.loads(result.stdout)
            except ValueError:
                raise AssertionError("product UI Automation did not return a bounded result") from None
            return result.returncode == 0 and reply.get("passed") is True

        def start():
            nonlocal process, frontend_pid
            previous = status().get("ownerPid")
            process = subprocess.Popen([str(entry)], env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            def ready():
                assert process.poll() is None, "native product entry exited during startup"
                value = status()
                return value if value.get("phase") == "running" and value.get("ownerPid") != previous else None
            value = wait_for(ready, "native entry did not start required services", timeout=45)
            known_pids.extend([value["ownerPid"], *(service["pid"] for service in value["services"])])
            frontend_pid = next(service["pid"] for service in value["services"] if service["name"] == "frontend")
            wait_for(lambda: state().get("phase") == "locked", "actual product window did not lock before authentication")
            assert state()["mediaSources"] == 0, "media source restored before login"
            wait_for(lambda: ui("inspect"), "actual product controls not accessible")
            return value

        frontend_pid = 0
        try:
            phase = "first-entry"
            started = start()
            assert sorted(service["name"] for service in started["services"]) == ["accounts-and-registry", "control", "frontend"]
            evidence["checks"].append("single-entry-real-core-authority-and-qt")
            phase = "first-account-ui"
            wait_for(lambda: ui("create", **account), "actual first-account button not usable")
            wait_for(lambda: state().get("phase") == "authenticated", "first account did not authenticate through real UI")
            assert state()["mediaSources"] == 0
            evidence["checks"].append("first-account-through-product-ui")
            phase = "logout"
            assert ui("logout")
            wait_for(lambda: state().get("phase") == "locked", "logout did not lock product UI")
            assert state()["mediaSources"] == 0 and state()["sessionBound"] is False
            evidence["checks"].append("logout-clears-bound-session")
            phase = "normal-close"
            assert ui("close")
            assert process.wait(timeout=40) == 0, "normal UI close failed orderly shutdown"
            wait_for(lambda: not any(alive(pid) for pid in known_pids), "owned process survived normal close")
            evidence["checks"].append("normal-ui-close-cleans-owned-processes")
            phase = "restart-login"
            start()
            assert ui("login", **account)
            wait_for(lambda: state().get("phase") == "authenticated", "persisted account did not log in after restart")
            evidence["checks"].append("restart-keeps-account-requires-login")
            phase = "revocation"
            with sqlite3.connect(profile / "config/cluster.sqlite3") as database:
                database.execute("UPDATE users SET auth_epoch=? WHERE username=?", (secrets.token_hex(16), account["username"]))
            wait_for(lambda: state().get("phase") == "locked", "real account epoch change did not lock product UI", timeout=8)
            assert state()["sessionBound"] is False and state()["mediaSources"] == 0
            evidence["checks"].append("real-authority-revocation-locks-ui")
            phase = "owner-crash"
            process.kill()
            process.wait(timeout=10)
            wait_for(lambda: not any(alive(pid) for pid in known_pids), "Windows Job left owned services after launcher crash", timeout=15)
            evidence["checks"].append("launcher-crash-job-cleans-all-owned-processes")
            evidence["passed"] = True
        except Exception:
            # Synthetic logs stay private; public result contains fixed phase only.
            evidence["failurePhase"] = phase
            raise AssertionError("native product entry/UI gate failed at " + phase) from None
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(evidence))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    exercise(arguments.runtime.resolve(strict=True), arguments.report.resolve())
