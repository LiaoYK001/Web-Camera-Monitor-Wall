#!/usr/bin/env python3
"""Actual native product entry/Qt/account lifecycle in a new private profile.

This gate drives the shipped controls through Windows UI Automation. It does not
claim installed-product, real-camera, performance or hardware-decode acceptance.
"""
from __future__ import annotations

import argparse
import contextlib
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
# The shipped embedded interpreter intentionally excludes the working directory
# and script directory. Only this test process imports the adjacent test tools.
sys.path.insert(0, str(HERE))


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


def exercise(runtime, report, *, with_media=False, retained_profile=None):
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
        profile = Path(retained_profile).absolute() if retained_profile is not None else private / "profile"
        if profile.exists() or profile.is_symlink():
            raise ValueError("product gate requires a NEW disposable profile")
        environment = dict(os.environ)
        environment["WEBOBS_PRODUCT_TEST_ROOT"] = str(profile)
        if with_media:
            environment["WEBOBS_PRODUCT_ALLOW_TEST_ENDPOINTS"] = "true"
        account = {"username": "native-owner", "password": secrets.token_urlsafe(24)}
        entry = runtime / "bin/webobs-wall.exe"
        process = None
        known_pids = []
        status_path = profile / "run/native-status.json"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        rtsp = None

        def request(path, body=None, cookie="", *, method=None, revision=None):
            origin = status()["origin"]
            headers = {"Origin": origin, "Content-Type": "application/json"}
            if cookie:
                headers["Cookie"] = cookie
            if revision is not None:
                headers["If-Match"] = '"' + str(revision) + '"'
            message = urllib.request.Request(origin + path, headers=headers,
                data=None if body is None else json.dumps(body).encode(), method=method)
            try:
                reply = opener.open(message, timeout=15)
            except urllib.error.HTTPError as error:
                reply = error
            with reply:
                return reply.status, reply.headers.get("Set-Cookie", ""), json.loads(reply.read())

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
            owned = state()
            windows = owned.get("windows", [])
            if len(windows) != 1 or owned.get("pid") != str(frontend_pid):
                return False
            result = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                str(HERE / "product-ui.ps1"), "-FrontendPid", str(frontend_pid), "-RootHwnd", windows[0]["rootHwnd"]],
                input=json.dumps({"action": action, **fields}), capture_output=True, text=True,
                encoding="utf-8", timeout=25)
            try:
                reply = json.loads(result.stdout)
            except ValueError:
                raise AssertionError("product UI Automation did not return a bounded result") from None
            if reply.get("passed") is not True:
                evidence["lastUiFailure"] = {key: reply[key] for key in ("stage", "code", "exceptionType") if key in reply}
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

        def check_graph():
            wait_for(lambda: state().get("phase") == "graph-applied", "UI did not apply authorized camera graph", timeout=35)
            observed = state()
            assert observed["sessionBound"] is True and observed["mediaSources"] == 5
            bindings = observed["bindings"]
            assert [(item["cameraId"], item["profileId"]) for item in bindings] == [
                (f"fixture-{index}", "main") for index in range(1, 6)]
            assert len({item["sourceUuid"] for item in bindings}) == 5
            assert observed["videoInfo"] == {"baseWidth": 1920, "baseHeight": 1080,
                "outputWidth": 1920, "outputHeight": 1080, "fpsNumerator": 30, "fpsDenominator": 1}
            return observed

        def check_pixels(label, *, blank=False):
            from ctypes import wintypes
            import pixel_windows
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x1000, False, frontend_pid)
            if not handle:
                raise AssertionError("could not inspect the exact product frontend")
            try:
                class Frontend:
                    _handle = handle
                created = pixel_windows.creation_time(Frontend())
            finally:
                kernel.CloseHandle(handle)
            observed = state() if blank else check_graph()
            if blank:
                assert observed.get("phase") == "locked" and observed.get("mediaSources") == 0
            assert observed.get("windows", [{}])[0].get("qtClass") == "OBSBasicPreview"
            target = private / ("pixels-" + label)
            target.mkdir()
            metadata = target / "capture-state.json"
            metadata.write_text(json.dumps({"schema": 1, "scope": "synthetic-test-only",
                "pid": str(frontend_pid), "windows": observed["windows"]}), encoding="utf-8")
            result = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-File", str(HERE / "capture-pixels.ps1"),
                "-ExpectedProcessId", str(frontend_pid), "-ExpectedExecutable", str(runtime / "bin/64bit/obs64.exe"),
                "-ExpectedCreationTime", created, "-StateFile", str(metadata), "-OutputDirectory", str(target)],
                capture_output=True, text=True, encoding="utf-8", timeout=35)
            capture = pixel_windows.capture_report(result)
            evidence.setdefault("captures", []).append({"phase": label, **capture})
            assert result.returncode == 0 and capture.get("captureFailed") is False, "actual product preview capture failed"
            analysis = subprocess.run([shutil.which("node"), str(HERE / "pixel-pattern.cjs"), "analyze-empty" if blank else "analyze",
                str(target / "main-preview"), "main-preview", "forward", "true"],
                check=True, capture_output=True, text=True, encoding="utf-8", timeout=20)
            result = json.loads(analysis.stdout)
            evidence["captures"][-1]["analysis"] = result
            assert result.get("passed") is True, "product preview failed the expected final-pixel state"

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
            if with_media:
                phase = "synthetic-fixtures"
                import pixel_windows
                ffmpeg, ffprobe = pixel_windows.locked_ffmpeg(private, False)
                fixtures = pixel_windows.make_fixtures(private, ffmpeg, ffprobe, shutil.which("node"), all_hevc=True)
                assert all(item["codec"] == "hevc" for item in fixtures)
                evidence["fixtures"] = fixtures
                rtsp = pixel_windows.LoopbackRtsp(private, ffmpeg, ffprobe, fixtures, secrets.token_hex(16), False)
                phase = "existing-camera-api"
                code, issued, _ = request("/api/v1/auth/login", account)
                assert code == 200 and issued
                cookie = issued.split(";", 1)[0]
                for index, endpoint in enumerate(rtsp.urls, 1):
                    code, _, _ = request("/api/v1/cameras", {"id": f"fixture-{index}", "name": f"Fixture {index}",
                        "address": endpoint, "adapter": "rtsp", "hardwareDecode": "off", "profiles": [{
                            "id": "main", "name": "Main", "role": "main", "endpoint": endpoint,
                            "transportMode": "rtsp-tcp", "videoCodec": "h265", "width": 320, "height": 180,
                            "fps": 10, "audioCodec": ""}]}, cookie)
                    assert code == 201, "ordinary existing camera API could not create a fixture camera"
                phase = "camera-choice-ui"
                assert ui("refresh")
                wait_for(lambda: state().get("catalogItems") == 5, "product camera choices did not refresh")
                assert ui("choose", indices=[1, 2, 3, 4, 5])
                check_graph()
                phase = "product-final-pixels"
                time.sleep(3)
                check_pixels("watch")
                assert ui("save")
                paths = wait_for(lambda: list((profile / "native-profile").rglob("workspace-*.json")),
                    "product save button did not persist the bound workspace")
                assert len(paths) == 1
                saved = read_json(paths[0])
                assert saved == {"schema": 1, "cameras": [
                    {"cameraId": f"fixture-{index}", "profileId": "main"} for index in range(1, 6)]}
                evidence["checks"].extend(["existing-camera-api-to-native-selection", "five-hevc-final-pixels", "save-only-bound-camera-profile-ids"])
            phase = "logout"
            assert ui("logout")
            wait_for(lambda: state().get("phase") == "locked", "logout did not lock product UI")
            assert state()["mediaSources"] == 0 and state()["sessionBound"] is False
            evidence["checks"].append("logout-clears-bound-session")
            if with_media:
                check_pixels("logout", blank=True)
                phase = "relogin-restores-media"
                assert ui("login", **account)
                check_graph()
                time.sleep(3)
                check_pixels("relogin")
                evidence["checks"].append("relogin-restores-saved-five-hevc-final-pixels")
                for table in ("stream_profiles", "cameras"):
                    phase = "disable-" + table
                    with contextlib.closing(sqlite3.connect(profile / "config/cameras.db")) as database, database:
                        database.execute(f"UPDATE {table} SET enabled=0")
                    wait_for(lambda: state().get("phase") == "locked", "disabled camera/Profile remained viewable", timeout=8)
                    check_pixels("disabled-" + table, blank=True)
                    with contextlib.closing(sqlite3.connect(profile / "config/cameras.db")) as database, database:
                        database.execute(f"UPDATE {table} SET enabled=1")
                    evidence["checks"].append("disabled-" + table + "-clears-final-preview")
                    if table == "stream_profiles":
                        assert ui("login", **account)
                        check_graph()
            phase = "normal-close"
            assert ui("close")
            assert process.wait(timeout=40) == 0, "normal UI close failed orderly shutdown"
            wait_for(lambda: not any(alive(pid) for pid in known_pids), "owned process survived normal close")
            evidence["checks"].append("normal-ui-close-cleans-owned-processes")
            phase = "restart-login"
            start()
            assert ui("login", **account)
            if with_media:
                check_graph()
                time.sleep(3)
                check_pixels("restart")
                evidence["checks"].append("restart-authenticates-before-restoring-five-hevc-final-pixels")
            else:
                wait_for(lambda: state().get("phase") == "authenticated", "persisted account did not log in after restart")
            evidence["checks"].append("restart-keeps-account-requires-login")
            if with_media:
                phase = "configuration-change"
                code, issued, _ = request("/api/v1/auth/login", account)
                assert code == 200 and issued
                cookie = issued.split(";", 1)[0]
                code, _, item = request("/api/v2/source-catalog/fixture-1", cookie=cookie)
                assert code == 200
                code, _, _ = request("/api/v2/source-catalog/fixture-1", {"profiles": [
                    {"id": "main", "transportMode": "auto"}]}, cookie, method="PATCH", revision=item["revision"])
                assert code == 200, "ordinary catalog update API did not save the fixture change"
                wait_for(lambda: state().get("phase") == "locked", "changed connection configuration remained active", timeout=8)
                check_pixels("configuration-changed", blank=True)
                assert ui("login", **account)
                check_graph()
                time.sleep(3)
                check_pixels("configuration-reconnected")
                evidence["checks"].append("real-catalog-change-clears-stale-preview-and-reconnects")
            phase = "revocation"
            with contextlib.closing(sqlite3.connect(profile / "config/cluster.sqlite3")) as database, database:
                database.execute("UPDATE users SET auth_epoch=? WHERE username=?", (secrets.token_hex(16), account["username"]))
            wait_for(lambda: state().get("phase") == "locked", "real account epoch change did not lock product UI", timeout=8)
            assert state()["sessionBound"] is False and state()["mediaSources"] == 0
            if with_media:
                check_pixels("revoked", blank=True)
            evidence["checks"].append("real-authority-revocation-locks-ui")
            phase = "owner-crash"
            process.kill()
            process.wait(timeout=10)
            wait_for(lambda: not any(alive(pid) for pid in known_pids), "Windows Job left owned services after launcher crash", timeout=15)
            evidence["checks"].append("launcher-crash-job-cleans-all-owned-processes")
            evidence.pop("lastUiFailure", None)
            evidence["mediaQualified"] = with_media
            evidence["mediaScope"] = "synthetic-five-hevc-final-preview-pixels" if with_media else "not-run"
            evidence["passed"] = True
        except Exception:
            # Synthetic logs stay private. Only fixed marker categories, bounded
            # counts and numeric exit status leave this disposable test profile.
            evidence["failurePhase"] = phase
            evidence["entryExitCode"] = process.poll() if process is not None else None
            observed = state()
            evidence["observedState"] = {key: observed[key] for key in ("phase", "mediaSources", "sessionBound", "catalogItems") if key in observed}
            markers = ("ModuleNotFoundError", "ImportError", "PermissionError", "FileNotFoundError",
                       "RuntimeError", "AttributeError", "ValueError", "control exited during startup",
                       "control health deadline exceeded", "a required product service exited")
            evidence["privateLogMarkers"] = []
            for log in (profile / "logs").glob("native-*.log"):
                if log.is_file() and not log.is_symlink():
                    with log.open("rb") as source:
                        source.seek(max(0, log.stat().st_size - 131072))
                        tail = source.read(131072).decode("utf-8", errors="replace")
                    evidence["privateLogMarkers"].extend(marker for marker in markers if marker in tail)
            evidence["privateLogMarkers"] = sorted(set(evidence["privateLogMarkers"]))
            raise AssertionError("native product entry/UI gate failed at " + phase) from None
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            wait_for(lambda: not any(alive(pid) for pid in known_pids),
                     "owned Windows process survived gate cleanup", timeout=15)
            if rtsp is not None:
                rtsp.stop()
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(evidence))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--with-media", action="store_true")
    parser.add_argument("--retained-profile", type=Path)
    arguments = parser.parse_args()
    exercise(arguments.runtime.resolve(strict=True), arguments.report.resolve(), with_media=arguments.with_media,
             retained_profile=arguments.retained_profile)
