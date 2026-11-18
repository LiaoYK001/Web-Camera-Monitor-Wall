#!/usr/bin/env python3
"""Actual native product entry/Qt/account lifecycle in a new private profile.

This gate drives the shipped controls through Windows UI Automation. It does not
claim installed-product, real-camera, performance or hardware-decode acceptance.
"""
from __future__ import annotations

import argparse
import configparser
import contextlib
import ctypes
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import sqlite3
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from release_policy import delivery

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
    """Poll until the predicate is truthy, then report why it never became so.

    ``message`` may be a callable: a formatted failure string built eagerly at the
    call site would read evidence that only the first probe writes (and crash with
    KeyError before the wait ever starts), so the report is assembled at timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.1)
    detail = message() if callable(message) else message
    raise AssertionError(detail)


def split_workspace(value):
    """Return the media payload and validated optional projector preferences."""
    if not isinstance(value, dict):
        raise AssertionError("account workspace is not a JSON object")
    placements = value.get("projectorPlacements")
    base = {key: item for key, item in value.items() if key != "projectorPlacements"}
    if placements is None:
        return base, {}
    assert isinstance(placements, dict), "account projector preferences are not an object"
    assert set(placements) <= {"fixed-1", "fixed-2", "program"}, \
        "account workspace contains an unknown projector role"
    for role, placement in placements.items():
        assert isinstance(placement, dict), "projector preference is not an object"
        assert set(placement) == {"x", "y", "width", "height", "screen", "fullscreen"}, \
            "projector preference has an unexpected schema"
        assert all(type(placement[key]) is int for key in ("x", "y", "width", "height"))
        assert isinstance(placement["screen"], str) and len(placement["screen"]) <= 128
        assert type(placement["fullscreen"]) is bool
        assert abs(placement["x"]) <= 100000 and abs(placement["y"]) <= 100000
        assert 1 <= placement["width"] <= 16384 and 1 <= placement["height"] <= 16384
    return base, placements


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


def process_creation_time(pid):
    """Return the kernel creation time so a reused Windows PID is not ours."""
    from ctypes import wintypes

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime), ctypes.POINTER(FileTime), ctypes.POINTER(FileTime)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        created, exited, kernel_time, user_time = FileTime(), FileTime(), FileTime(), FileTime()
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
            ctypes.byref(kernel_time), ctypes.byref(user_time)):
            return None
        return (int(created.high) << 32) | int(created.low)
    finally:
        kernel.CloseHandle(handle)


def child_processes(powershell, pid):
    """Direct children of the native host, for on-demand process ownership claims.

    The product claims MediaMTX and the per-source FFmpeg mixer start only when
    a Scene or Program output actually needs them. Enumerating the host's own
    children is the only way to prove that no such helper is running while the
    user is doing plain RTSP monitoring.
    """
    listing = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
        f"Get-CimInstance Win32_Process -Filter 'ParentProcessID={int(pid)}' | "
        'ForEach-Object { "$($_.ProcessId)|$($_.Name)" }'],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
    assert listing.returncode == 0, f"could not enumerate native host children: {listing.stderr[:200]}"
    children = []
    for line in listing.stdout.splitlines():
        pid_text, _, name = line.partition("|")
        if pid_text.strip().isdigit():
            children.append((int(pid_text), name.strip().lower()))
    return children


def terminate_process(powershell, pid):
    """Kill one explicitly identified child PID; never a name-wide sweep."""
    killed = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
        f"Stop-Process -Id {int(pid)} -Force"], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=25)
    assert killed.returncode == 0, f"could not terminate PID {pid}: {killed.stderr[:200]}"


def exercise(runtime, report, *, with_media=False, retained_profile=None):
    if os.name != "nt":
        raise ValueError("actual Windows product gate requires Windows")
    manifest = read_json(runtime / "webobs-native-prototype.json")
    component_receipt = runtime / "product-components.json"
    if component_receipt.is_symlink() or component_receipt.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("missing or oversized component receipt")
    components = json.loads(component_receipt.read_text(encoding="utf-8"))
    preview_delivery = delivery(manifest) == "native-monitor-preview"
    complete_services = all((runtime / marker).is_file() for marker in (
        "services/events/event_service.py", "services/nvr/nvr_service.py",
        "services/v2/client_control_service.py", "bin/go2rtc.exe",
        "bin/node.exe", "bin/webobs-online-source.exe"))
    if manifest.get("productIntegration") is not True:
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
    gate_failed = [False]
    def checkpoint(name):
        evidence["lastCheckpoint"] = name
    with tempfile.TemporaryDirectory(prefix="WebOBS 产品接线-") as temporary:
        private = Path(temporary)
        profile = Path(retained_profile).absolute() if retained_profile is not None else (
            private / "local-data/WebOBS/NativePreview" if preview_delivery else private / "profile")
        if profile.exists() or profile.is_symlink():
            raise ValueError("product gate requires a NEW disposable profile")
        environment = dict(os.environ)
        legacy_markers = []
        if preview_delivery:
            if profile.name != "NativePreview" or profile.parent.name != "WebOBS":
                raise ValueError("preview gate requires the actual isolated default data-root shape")
            # A public preview must ignore a stale internal test-root override.
            environment["WEBOBS_PRODUCT_TEST_ROOT"] = str(private / "must-not-be-used")
            environment["LOCALAPPDATA"] = str(profile.parents[1])
            for relative in ("config/legacy-marker.txt", "NativeIntegration/config/internal-marker.txt"):
                marker = profile.parent / relative
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_bytes(b"synthetic retained older installation data")
                legacy_markers.append(marker)
        else:
            environment["WEBOBS_PRODUCT_TEST_ROOT"] = str(profile)
        if with_media:
            environment["WEBOBS_PRODUCT_ALLOW_TEST_ENDPOINTS"] = "true"
        account = {"username": "native-owner", "password": secrets.token_urlsafe(24)}
        entry = runtime / "bin/webobs-wall.exe"
        process = None
        known_pids = []
        known_pid_creations = {}
        def remember_owned_pids(pids):
            for pid in pids:
                pid = int(pid)
                if pid not in known_pids:
                    known_pids.append(pid)
                created = process_creation_time(pid)
                if created is not None:
                    known_pid_creations[pid] = created
        def owned_alive(pid):
            if not alive(pid):
                return False
            expected = known_pid_creations.get(int(pid))
            return expected is None or process_creation_time(pid) == expected
        status_path = profile / "run/native-status.json"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        rtsp = None
        idle_program_uuid = None
        active_boot_id = None
        boot_started_at = 0.0

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

        def raw_request(path, cookie="", *, headers=None):
            origin = status()["origin"]
            request_headers = {"Origin": origin}
            if cookie:
                request_headers["Cookie"] = cookie
            request_headers.update(headers or {})
            message = urllib.request.Request(origin + path, headers=request_headers, method="GET")
            try:
                reply = opener.open(message, timeout=15)
            except urllib.error.HTTPError as error:
                reply = error
            with reply:
                return reply.status, reply.headers, reply.read(1024 * 1024)

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
                return value if value.get("pid") == str(frontend_pid) and value.get("bootId") == active_boot_id else {}
            except (OSError, ValueError):
                return {}

        def apply_attempt(value):
            """Bounded snapshot of the Program apply machine when a wait stalls.

            Without this the receipt only says a scene "did not apply"; the
            frontend's own reason code lives in the product state file.
            """
            program = value.get("program")
            program = program if isinstance(program, dict) else {}
            return {key: value.get(key) for key in ("programSceneId", "programApplyState",
                "programApplyError", "programApplyTransient", "programApplyAttempts",
                "programTargetSceneId", "phase")} | {
                "programMediaSources": program.get("mediaSources")}

        def ui(action, **fields):
            owned = state()
            wanted_roles = {"main-preview"}
            if action in ("projector-fullscreen", "projector-window-close", "projector-place"):
                slot = fields.get("slot")
                assert type(slot) is int and slot in (1, 2)
                wanted_roles = {f"fixed-scene-{slot}", f"fixed-scene-fullscreen-{slot}"}
            windows = [window for window in owned.get("windows", []) if window.get("role") in wanted_roles]
            if action == "stats-close":
                windows = [owned["statsWindow"]] if owned.get("statsOpen") is True and isinstance(owned.get("statsWindow"), dict) else []
            if len(windows) != 1 or owned.get("pid") != str(frontend_pid):
                return False
            try:
                result = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                    str(HERE / "product-ui.ps1"), "-FrontendPid", str(frontend_pid), "-RootHwnd", windows[0]["rootHwnd"]],
                    input=json.dumps({"action": action, **fields}), capture_output=True, text=True,
                    encoding="utf-8", timeout=45)
            except subprocess.TimeoutExpired:
                evidence["lastUiFailure"] = {"stage": action, "code": "ui-timeout"}
                raise AssertionError("product UI Automation exceeded its deadline") from None
            try:
                assert len(result.stdout) <= 4096
                reply = json.loads(result.stdout)
                assert isinstance(reply, dict)
            except (ValueError, AssertionError):
                evidence["lastUiFailure"] = {"stage": action, "code": "invalid-report"}
                raise AssertionError("product UI Automation did not return a bounded result") from None
            if reply.get("passed") is not True:
                evidence["lastUiFailure"] = {key: reply[key] for key in ("stage", "code", "exceptionType") if key in reply}
            passed = result.returncode == 0 and reply.get("passed") is True
            if passed and action in ("choose", "scene"):
                before = owned.get("mainGeneration")
                assert type(before) is int
                wait_for(lambda: state().get("mainGeneration", -1) > before,
                    "actual native watch action was not acknowledged", timeout=5)
            return passed

        def start():
            nonlocal process, frontend_pid, idle_program_uuid, active_boot_id, boot_started_at
            previous = status().get("bootId")
            active_boot_id = None
            frontend_pid = 0
            boot_started_at = time.time()
            process = subprocess.Popen([str(entry)], env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            def ready():
                assert process.poll() is None, "native product entry exited during startup"
                value = status()
                return value if value.get("phase") == "running" and value.get("bootId") != previous and \
                    isinstance(value.get("bootId"), str) and re.fullmatch(r"[a-f0-9]{32}", value["bootId"]) else None
            value = wait_for(ready, "native entry did not start required services", timeout=45)
            active_boot_id = value["bootId"]
            remember_owned_pids([value["ownerPid"], *(service["pid"] for service in value["services"])])
            frontend_pid = next(service["pid"] for service in value["services"] if service["name"] == "frontend")
            wait_for(lambda: state().get("phase") == "locked", "actual product window did not lock before authentication")
            assert state()["mediaSources"] == 0, "media source restored before login"
            assert state().get("previewLocked") is True, "product monitor preview retained OBS editing guides"
            assert state().get("startupStudioDeferred") is True, "saved OBS mode bypassed product-owned Studio initialization"
            program = state().get("program", {})
            assert program.get("studioMode") is True and program.get("mediaSources") == 0
            assert isinstance(program.get("sceneUuid"), str) and program["sceneUuid"]
            idle_program_uuid = program["sceneUuid"]
            assert program.get("monitorIsProgram") is False
            wait_for(lambda: ui("inspect"), "actual product controls not accessible")
            return value

        def check_graph(*, repeat_first=False, reverse=False, expected_media=None, quick_order=None,
                program_scene=None, program_media=None):
            order = quick_order if quick_order is not None else [1] * 5 if repeat_first else list(range(5, 0, -1)) if reverse else list(range(1, 6))
            expected = expected_media if expected_media is not None else len(set(order))
            pairs = [(f"fixture-{index}", "main") for index in order]

            def ready():
                value = state()
                actual = [(item.get("cameraId"), item.get("profileId")) for item in value.get("bindings", [])]
                return value if value.get("phase") == "graph-applied" and value.get("mediaSources") == expected and actual == pairs else None

            observed = wait_for(ready, "UI did not settle the complete authorized camera graph", timeout=35)
            assert observed["sessionBound"] is True and observed["mediaSources"] == expected
            assert observed.get("previewLocked") is True
            check_monitor_program(observed, program_scene=program_scene, program_media=program_media)
            import smoke_windows
            smoke_windows.check_renderer_receipt(observed.get("renderer"))
            assert len({item["sourceUuid"] for item in observed["bindings"]}) == len(set(order))
            if quick_order is not None:
                assert observed.get("slotCount") == len(order)
            assert observed["videoInfo"] == {"baseWidth": 1920, "baseHeight": 1080,
                "outputWidth": 1920, "outputHeight": 1080, "fpsNumerator": 30, "fpsDenominator": 1}
            return observed

        def check_monitor_program(observed=None, *, program_scene=None, program_media=None):
            value = observed if observed is not None else state()
            program = value.get("program", {})
            assert program.get("studioMode") is True, "local monitor lost Preview/Program separation"
            if program_scene is None:
                assert program.get("sceneUuid") == idle_program_uuid and program.get("mediaSources") == 0, \
                    "local monitor selection changed or populated global Program output"
                assert program.get("monitorIsProgram") is False, "local monitor became the Program scene"
            else:
                expected_media = 0 if program_media is None else program_media
                assert value.get("programSceneId") == program_scene, "native Program did not apply the TAKE target"
                assert value.get("programApplyState") == "applied", "native Program has not confirmed the TAKE"
                assert program.get("mediaSources") == expected_media, \
                    "native Program pixels do not match the applied scene media count"

        def check_projectors(orders, reference):
            observed = state()
            views = observed.get("projectors", [])
            assert [view["slot"] for view in views] == sorted(orders)
            assert observed["mediaSources"] == 5, "fixed views duplicated camera media sources"
            for view in views:
                reverse = orders[view["slot"]] == "reverse"
                assert [(binding["cameraId"], binding["profileId"]) for binding in view["bindings"]] == [
                    (f"fixture-{6 - index if reverse else index}", "main") for index in range(1, 6)]
                assert {binding["cameraId"]: binding["sourceUuid"] for binding in view["bindings"]} == reference
            for binding in observed.get("bindings", []):
                assert reference[binding["cameraId"]] == binding["sourceUuid"]
            return observed

        def fixed_windows():
            return [window for window in state().get("windows", []) if window["role"].startswith("fixed-scene-")]

        def owned_windows_closed(windows):
            from ctypes import wintypes
            user = ctypes.WinDLL("user32", use_last_error=True)
            user.IsWindow.argtypes = [wintypes.HWND]
            user.IsWindow.restype = wintypes.BOOL
            user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user.GetWindowThreadProcessId.restype = wintypes.DWORD
            for window in windows:
                handle = wintypes.HWND(int(window["rootHwnd"], 16))
                if user.IsWindow(handle):
                    owner = wintypes.DWORD()
                    user.GetWindowThreadProcessId(handle, ctypes.byref(owner))
                    if owner.value == frontend_pid:
                        return False
            return True

        def fixture_publisher_health():
            """Bounded harness health: publisher process state and readable loopback paths.

            A frozen final-pixel slot can come from the product decoder or from the test
            fixture that feeds it. This reads only process state and whether each synthetic
            RTSP path is still readable, so the receipt says which side stalled.
            """
            publishers = []
            for index, publisher in enumerate(rtsp.publishers):
                if publisher is None:
                    state = "absent"
                elif publisher.poll() is None:
                    state = "alive"
                else:
                    state = "exited"
                publishers.append({"index": index, "state": state})
            readable = []
            for url in rtsp.urls:
                try:
                    probe = subprocess.run([str(ffprobe), "-v", "error", "-rtsp_transport", "tcp",
                        "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "json", url],
                        capture_output=True, text=True, timeout=8)
                    readable.append(probe.returncode == 0)
                except subprocess.TimeoutExpired:
                    readable.append(False)
            return {"publishers": publishers, "readable": readable}

        def check_pixels(label, *, blank=False, repeat_first=False, reverse=False, expected_media=None,
                projector_orders=None, quick_order=None, program_scene=None, program_media=None,
                fixture_retry=True):
            # A loopback publisher is harness state, not product state: ffmpeg can exit while
            # looping a synthetic file, and then every reader of that path stalls through no
            # fault of the product. Restart dead publishers before capturing and record it.
            dead = [index for index, publisher in enumerate(rtsp.publishers)
                if publisher is None or publisher.poll() is not None]
            if dead and not blank:
                evidence.setdefault("fixturePublisherWatch", []).append({"phase": label, "dead": dead})
                for index in dead:
                    rtsp.restart_publisher(index)
                wait_for(lambda: ui("video-progress", sources=5, stalled=0),
                    "restarted loopback publisher did not resume frame progress", timeout=60)
            checkpoint("pixels-" + label + "-program")
            check_monitor_program(program_scene=program_scene, program_media=program_media)
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
            checkpoint("pixels-" + label + "-graph")
            observed = state() if blank else check_graph(repeat_first=repeat_first, reverse=reverse,
                expected_media=expected_media, quick_order=quick_order,
                program_scene=program_scene, program_media=program_media)
            checkpoint("pixels-" + label + "-observed")
            if blank:
                assert observed.get("phase") == "locked" and observed.get("mediaSources") == 0
            elif observed.get("sessionBound") is not True:
                # A revoked session tears the wall and its projectors down, which shows up
                # later as an opaque stale window handle or frozen pixels. Name the actual
                # revocation category the product reported instead.
                revoked = {"phase": label, "lastLock": str(observed.get("lastLock") or "")[:40],
                    "lockCode": int(observed.get("lockCode") or 0),
                    "renewTransient": int(observed.get("renewTransient") or 0)}
                evidence["sessionRevoked"] = revoked
                raise AssertionError("product session was revoked before the " + label +
                    " capture: " + revoked["lastLock"] + "/" + str(revoked["lockCode"]))
            assert observed.get("windows", [{}])[0].get("qtClass") == "OBSBasicPreview"
            target = private / ("pixels-" + label)
            target.mkdir()
            metadata = target / "capture-state.json"
            metadata.write_text(json.dumps({"schema": 1, "scope": "synthetic-test-only",
                "pid": str(frontend_pid), "windows": observed["windows"]}), encoding="utf-8")
            checkpoint("pixels-" + label + "-capture-setup")
            window_roles = {window["role"] for window in observed["windows"]}
            for attempt in range(2):
                checkpoint("pixels-" + label + "-capture-start")
                try:
                    # Normalize every argument and avoid PowerShell prompts/invalid
                    # console output turning a pixel capture into an opaque launch
                    # TypeError under a fully loaded product host.
                    capture_command = [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                        str(HERE / "capture-pixels.ps1"), "-ExpectedProcessId", str(frontend_pid),
                        "-ExpectedExecutable", str(runtime / "bin/64bit/obs64.exe"),
                        "-ExpectedCreationTime", str(created), "-StateFile", str(metadata),
                        "-OutputDirectory", str(target)]
                    process = subprocess.Popen(capture_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, encoding="utf-8", errors="replace", close_fds=True,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    try:
                        stdout, stderr = process.communicate(timeout=35)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        stdout, stderr = process.communicate()
                        raise
                    result = subprocess.CompletedProcess(capture_command, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    evidence.setdefault("captures", []).append({"phase": label,
                        "captureFailed": True, "diagnostic": {"stage": "timeout", "code": "capture-timeout"}})
                    checkpoint("pixels-" + label + "-capture-timeout")
                    raise
                except Exception as error:
                    # Keep only the exception class and numeric Win32/POSIX code;
                    # never copy paths, command lines or private state.
                    message = str(error)
                    for private_value in (str(metadata), str(target), str(runtime), str(profile)):
                        message = message.replace(private_value, "<private>")
                    evidence["captureLaunchError"] = {
                        "type": type(error).__name__,
                        "winerror": int(getattr(error, "winerror", 0) or 0),
                        "errno": int(getattr(error, "errno", 0) or 0),
                        "message": message[:200],
                    }
                    checkpoint("pixels-" + label + "-capture-error")
                    raise
                checkpoint("pixels-" + label + "-capture-returned")
                capture = pixel_windows.capture_report(result)
                checkpoint("pixels-" + label + "-capture-report")
                stale_identity = capture.get("captureFailed") is True and any(
                    isinstance(role, dict) and role.get("diagnostic", {}).get("code") == "window-identity"
                    for role in capture.get("captures", []))
                if stale_identity and attempt == 0:
                    # A reported window handle is a snapshot: a native client can
                    # recreate its HWND between the status read and the capture
                    # process. Re-read the window identity once and capture again;
                    # every pixel/identity assertion still applies to that retry.
                    evidence.setdefault("captures", []).append({"phase": label + "-stale-handle", **capture})
                    evidence["captureIdentityRetry"] = {"phase": label, "attempt": 1}
                    refreshed = state()
                    if {window.get("role") for window in refreshed.get("windows", [])} != window_roles:
                        break
                    observed = refreshed
                    metadata.write_text(json.dumps({"schema": 1, "scope": "synthetic-test-only",
                        "pid": str(frontend_pid), "windows": observed["windows"]}), encoding="utf-8")
                    continue
                break
            evidence.setdefault("captures", []).append({"phase": label, **capture})
            if not blank:
                # Renewal health at capture time: a tolerated busy authority is recorded,
                # while any lock category makes the receipt explicit.
                evidence["captures"][-1]["renewal"] = {
                    "lastLock": str(observed.get("lastLock") or "")[:40],
                    "lockCode": int(observed.get("lockCode") or 0),
                    "renewTransient": int(observed.get("renewTransient") or 0)}
            checkpoint("pixels-" + label + "-captured")
            assert result.returncode == 0 and capture.get("captureFailed") is False, "actual product preview capture failed"
            orders = {"main-preview": ("quick-" + ",".join(map(str, quick_order))) if quick_order is not None else
                "repeat-first" if repeat_first else "reverse" if reverse else "forward"}
            orders.update(projector_orders or {})
            assert set(orders) == {window["role"] for window in observed["windows"]}
            for role, order in orders.items():
                analysis = subprocess.run([shutil.which("node"), str(HERE / "pixel-pattern.cjs"), "analyze-empty" if blank else "analyze",
                    str(target / role), role, order, "true"], capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=20)
                assert len(analysis.stdout) <= 16384, "oversized synthetic pixel analysis"
                result = json.loads(analysis.stdout)
                assert isinstance(result, dict), "invalid synthetic pixel analysis"
                if role == "main-preview":
                    evidence["captures"][-1]["analysis"] = result
                else:
                    evidence["captures"][-1].setdefault("projectorAnalysis", {})[role] = result
                if result.get("passed") is not True:
                    harness = fixture_publisher_health()
                    dead = [entry["index"] for entry in harness["publishers"] if entry["state"] != "alive"]
                    unreadable = [index for index, ok in enumerate(harness["readable"]) if not ok]
                    evidence["pixelFailureDiagnostics"] = {"phase": label, "role": role,
                        "temporalProgress": result.get("temporalProgress"),
                        "progressError": str(result.get("progressError") or "")[:120],
                        "publisherState": harness["publishers"], "unreadablePaths": unreadable,
                        # A frozen slot is either a source that stopped delivering frames
                        # or a Scene that no longer renders the item. The product reports
                        # both, so the receipt says which one this was.
                        "videoInputs": observed.get("videoInputs", []),
                        "wallItems": int(observed.get("wallItems") or 0),
                        "programItems": int(observed.get("programItems") or 0),
                        "slots": [{"camera": str(binding.get("cameraId") or "")[:24],
                            "uuid": str(binding.get("sourceUuid") or "")[:8]}
                            for binding in observed.get("bindings", [])[:8]
                            if isinstance(binding, dict)]}
                    if (dead or unreadable) and fixture_retry:
                        # The synthetic fixture itself dropped out: restart every dead publisher,
                        # prove the host resumes decoding, then re-run this exact pixel phase
                        # once. A product-side stall with a healthy fixture still fails below.
                        evidence["fixtureRestartedAfterPixelFailure"] = {"phase": label,
                            "deadPublishers": dead, "unreadablePaths": unreadable}
                        for index in sorted(set(dead + unreadable)):
                            rtsp.restart_publisher(index)
                        wait_for(lambda: ui("video-progress", sources=5, stalled=0),
                            "restarted loopback fixture did not resume frame progress", timeout=60)
                        evidence["fixtureRestartResumed"] = label
                        return check_pixels(label, blank=blank, repeat_first=repeat_first, reverse=reverse,
                            expected_media=expected_media, projector_orders=projector_orders,
                            quick_order=quick_order, program_scene=program_scene,
                            program_media=program_media, fixture_retry=False)
                assert analysis.returncode == 0 and result.get("passed") is True, "product view failed its expected final-pixel state"

        frontend_pid = 0
        try:
            phase = "first-entry"
            started = start()
            running_services = sorted(service["name"] for service in started["services"])
            assert {"accounts-and-registry", "control", "frontend"} <= set(running_services)
            if complete_services:
                assert {"events", "nvr", "clients", "go2rtc", "backup"} <= set(running_services)
            else:
                assert running_services == ["accounts-and-registry", "control", "frontend"]
            evidence["checks"].append("single-entry-real-core-authority-and-qt")
            phase = "installed-management-shell"
            expected_shell = (runtime / "web/index.html").read_bytes()
            assert 0 < len(expected_shell) <= 2 * 1024 * 1024
            for path in ("/?native-management=1", "/index.html?native-management=1"):
                with opener.open(started["origin"] + path, timeout=15) as shell:
                    assert shell.status == 200 and shell.headers.get_content_type() == "text/html"
                    assert shell.headers.get("Cache-Control") == "no-cache"
                    assert shell.read(2 * 1024 * 1024 + 1) == expected_shell, "installed management shell differs from payload"
            evidence["checks"].append("management-entry-serves-actual-staged-ui-through-supervised-core")
            phase = "saved-studio-mode-cold-start"
            initial_origin = started["origin"]
            initial_boot = started["bootId"]
            assert ui("close")
            assert process.wait(timeout=40) == 0
            wait_for(lambda: not any(owned_alive(pid) for pid in known_pids), "pre-login close retained owned processes")
            preferences = configparser.ConfigParser(interpolation=None)
            preferences.read_string((profile / "native-profile/obs-studio/user.ini").read_text(encoding="utf-8-sig"))
            assert preferences.getboolean("BasicWindow", "PreviewProgramMode") is True, \
                "cold-start control did not actually persist Studio mode"
            # Let Windows release profile handles after the complete-service
            # process tree has exited; a real user never starts the next launch
            # inside the same millisecond as the previous owner exit.
            time.sleep(1)
            started = start()
            assert started["origin"] == initial_origin and started["bootId"] != initial_boot
            evidence["checks"].append("saved-studio-preference-starts-locked-through-product-only")
            phase = "exclusive-control-listener"
            with socket.socket() as competing_listener:
                competing_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    competing_listener.bind(("127.0.0.1", int(started["origin"].rsplit(":", 1)[1])))
                except OSError as error:
                    assert error.winerror in (10013, 10048), "unexpected listener isolation failure"
                else:
                    raise AssertionError("another listener could force-bind the native account origin")
            evidence["checks"].append("active-control-origin-refuses-forced-rebind")
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
                assert fixtures[0]["audioTracks"] == 2, "dual audio-track fixture was not encoded"
                evidence["fixtures"] = fixtures
                rtsp = pixel_windows.LoopbackRtsp(private, ffmpeg, ffprobe, fixtures, secrets.token_hex(16), False)
                audio_streams = []
                audio_deadline = time.monotonic() + 15
                while time.monotonic() < audio_deadline:
                    audio_probe = subprocess.run(
                        [str(ffprobe), "-v", "error", "-rtsp_transport", "tcp", "-select_streams", "a",
                         "-show_entries", "stream=codec_name,codec_type", "-of", "json", rtsp.urls[0]],
                        capture_output=True, text=True, encoding="utf-8", timeout=20)
                    audio_streams = json.loads(audio_probe.stdout).get("streams", []) \
                        if audio_probe.returncode == 0 else []
                    if len(audio_streams) == 2:
                        break
                    time.sleep(0.5)
                evidence["rtspAudioTracks"] = len(audio_streams)
                assert len(audio_streams) == 2, "loopback RTSP did not expose both synthetic audio tracks"
                # Stream count alone cannot prove the published endpoint kept
                # both tracks distinct. Decode each stream and measure the two
                # fixed pitches so a collapsed or mis-mapped publisher fails
                # here rather than showing up as a silent Program mix later.
                fixture_tones = fixtures[0].get("audioTonesHz")
                assert isinstance(fixture_tones, list) and len(fixture_tones) == 2, \
                    "fixture receipt did not record two decoded audio tones"
                rtsp_tones = []
                tone_deadline = time.monotonic() + 60
                while time.monotonic() < tone_deadline:
                    try:
                        decoded = [pixel_windows.tone_probe(ffmpeg, rtsp.urls[0], index)
                                   for index in (0, 1)]
                    except ValueError:
                        decoded = []
                    if decoded and all(decoded) and all(item[0] > 200 for item in decoded):
                        rtsp_tones = [item[1] for item in decoded]
                        break
                    time.sleep(1)
                evidence["rtspAudioTonesHz"] = rtsp_tones
                assert len(rtsp_tones) == 2, "loopback RTSP did not deliver decodable audio on both tracks"
                assert all(abs(actual - wanted) <= 30 for actual, wanted in zip(rtsp_tones, fixture_tones)), \
                    "loopback RTSP tracks do not match the two tones encoded in the fixture file"
                phase = "existing-camera-api"
                code, issued, _ = request("/api/v1/auth/login", account)
                assert code == 200 and issued
                cookie = issued.split(";", 1)[0]
                if complete_services:
                    phase = "complete-business-services"
                    for path in ("/api/v1/nvr/status", "/api/v1/events?limit=1",
                                 "/api/v1/go2rtc/api", "/api/v2/clients"):
                        code, _, _ = request(path, cookie=cookie)
                        assert code == 200, f"complete business service unavailable: {path}"
                    evidence["checks"].append("complete-business-services-running-in-one-product-entry")
                    phase = "complete-online-source-runtime"
                    online_environment = dict(os.environ)
                    online_environment.update({
                        "WEBOBS_NODE_PATH": str(runtime / "bin/node.exe"),
                        "WEBOBS_FFMPEG_PATH": str(runtime / "bin/ffmpeg.exe"),
                        "WEBOBS_FFPROBE_PATH": str(runtime / "bin/ffprobe.exe"),
                    })
                    online = subprocess.run([str(runtime / "bin/webobs-online-source.exe"), "--self-test"],
                        capture_output=True, text=True, encoding="utf-8", timeout=45, env=online_environment,
                        stdin=subprocess.DEVNULL)
                    assert online.returncode == 0 and '"yt-dlp"' in online.stdout and '"node"' in online.stdout, \
                        "bundled website extractors or Node runtime failed their self-test"
                    evidence["checks"].append("complete-online-source-extractors-and-node-runtime-self-test")
                    phase = "complete-business-management-entries"
                    assert ui("management-entries"), "complete product management entries are not discoverable"
                    evidence["checks"].append("complete-business-management-entries-discoverable")
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
                phase = "authorized-graph-application"
                check_graph()
                phase = "product-final-pixels"
                time.sleep(3)
                check_pixels("watch")
                wait_for(lambda: ui("video-progress", sources=5),
                    "actual five HEVC inputs did not report delivered video progress", timeout=15)
                evidence["checks"].append("five-hevc-delivered-video-progress")
                phase = "native-obs-host-statistics"
                assert ui("stats")
                wait_for(lambda: state().get("statsOpen") is True,
                    "actual OBS statistics window did not open")
                assert state()["statsWindow"]["qtClass"] == "OBSBasicStats"
                assert ui("stats-close")
                wait_for(lambda: state().get("statsOpen") is False,
                    "actual OBS statistics window did not close")
                evidence["checks"].append("authenticated-existing-obs-statistics-window")
                phase = "complete-business-nvr"
                recording_started = int(time.time() * 1000) - 60_000
                nvr_configuration = {
                    "schemaVersion": 1, "segmentSeconds": 2, "maxAgeHours": 1,
                    "maxBytes": 0, "minFreeBytes": 0,
                    "cameras": [{"id": "fixture-recording", "name": "Fixture recording",
                        "policy": "continuous", "cameraId": "fixture-1", "mainProfileId": "main",
                        "stream": "main", "mode": "copy", "transport": "tcp", "segmentSeconds": 2,
                        "maxAgeHours": 1, "maxBytes": 0, "preEventSeconds": 0, "schedule": []}],
                }
                code, _, configured_nvr = request("/api/v1/nvr/config", nvr_configuration,
                    cookie=cookie, method="PUT")
                assert code == 200, "complete product could not configure the real NVR"
                def recorded_segment():
                    code, _, value = request("/api/v1/nvr/status", cookie=cookie)
                    if code != 200:
                        return None
                    camera = next((item for item in value.get("cameras", [])
                        if item.get("id") == "fixture-recording"), None)
                    return camera if camera and camera.get("segments", 0) > 0 else None
                wait_for(recorded_segment, "real NVR did not finish a recorded segment", timeout=35)
                now = int(time.time() * 1000)
                code, _, timeline = request(
                    f"/api/v1/nvr/timeline?from={recording_started}&to={now + 60_000}&cameraId=fixture-recording",
                    cookie=cookie)
                assert code == 200, "recorded NVR timeline is unavailable"
                timeline_cameras = [item for item in timeline.get("cameras", [])
                    if item.get("cameraId") == "fixture-recording"]
                segments = timeline_cameras[0].get("segments", []) if timeline_cameras else []
                assert segments, "real NVR timeline did not contain the recorded segment"
                segment_id = segments[0]["id"]
                code, reply_headers, media = raw_request(f"/api/v1/nvr/media/{segment_id}", cookie,
                    headers={"Range": "bytes=0-63"})
                assert code in (200, 206) and len(media) > 16 and b"ftyp" in media[:64], \
                    "authenticated NVR media was not playable MP4 output"
                assert reply_headers.get("Content-Type", "").startswith("video/"), \
                    "NVR media response has the wrong content type"
                nvr_configuration["cameras"][0]["policy"] = "off"
                code, _, _ = request("/api/v1/nvr/config", nvr_configuration, cookie=cookie, method="PUT")
                assert code == 200, "NVR recording could not be stopped after its gate"
                evidence["checks"].append("nvr-records-real-registry-camera-and-serves-authenticated-media")
                phase = "complete-business-events"
                code, _, created_rule = request("/api/v1/event-rules", {
                    "id": "fixture-rule", "name": "Fixture outbox rule", "enabled": True,
                    "conditions": {"cameraId": "fixture-1"},
                    "actions": [{"kind": "webhook", "destinationRef": "fixture"}],
                    "cooldownMs": 0}, cookie=cookie, method="POST")
                assert code == 201 and created_rule.get("id") == "fixture-rule", \
                    "complete product could not persist an event rule"
                event_body = {"cameraId": "fixture-1", "type": "manual-marker", "source": "manual",
                    "topic": "fixture.qa", "severity": "info", "occurredAt": int(time.time() * 1000),
                    "properties": {"durationMs": 0}, "dedupeKey": "fixture-complete-product-event"}
                code, _, stored_event = request("/api/v1/events", event_body, cookie=cookie, method="POST")
                assert code == 201 and stored_event.get("id"), "complete product could not ingest an event"
                code, _, duplicate = request("/api/v1/events", event_body, cookie=cookie, method="POST")
                assert code == 201 and duplicate.get("deduplicated") is True and \
                    duplicate.get("id") == stored_event.get("id"), "event deduplication changed the event identity"
                def routed_outbox():
                    code, _, value = request("/api/v1/notification-outbox", cookie=cookie)
                    if code != 200:
                        return None
                    entry = next((item for item in value.get("outbox", [])
                        if item.get("event_id") == stored_event["id"]), None)
                    return entry if entry else None
                outbox = wait_for(routed_outbox, "event rule did not create a durable notification outbox entry",
                    timeout=10)
                assert outbox.get("kind") == "webhook" and outbox.get("destination_ref") == "fixture", \
                    "notification outbox lost the configured destination"
                evidence["checks"].append("events-persist-dedupe-and-route-to-durable-outbox")
                assert ui("save")
                paths = wait_for(lambda: list((profile / "native-profile").rglob("workspace-*.json")),
                    "product save button did not persist the bound workspace")
                assert len(paths) == 1
                saved = read_json(paths[0])
                assert saved == {"schema": 1, "cameras": [
                    {"cameraId": f"fixture-{index}", "profileId": "main"} for index in range(1, 6)]}
                evidence["checks"].extend(["existing-camera-api-to-native-selection", "five-hevc-final-pixels", "save-only-bound-camera-profile-ids"])
                phase = "repeated-camera-source-sharing"
                assert ui("choose", indices=[1, 1, 1, 1, 1])
                check_graph(repeat_first=True)
                time.sleep(3)
                check_pixels("shared-camera", repeat_first=True)
                wait_for(lambda: ui("video-progress", sources=1),
                    "five repeated tiles duplicated input progress accounting", timeout=15)
                evidence["checks"].append("five-items-one-owned-hevc-source-final-pixels")
                # Preserve the five DISTINCT-channel baseline and saved workspace.
                assert ui("choose", indices=[1, 2, 3, 4, 5])
                check_graph()
                time.sleep(3)
                check_pixels("distinct-after-sharing")
                phase = "variable-quick-wall-layout"
                previous = state()["bindings"]
                for indices in ([1], [1, 2, 3, 4], [1, 2, 3, 4, 5, 1, 2]):
                    assert ui("resize", count=len(indices))
                    wait_for(lambda: state().get("slotCount") == len(indices), "actual count control did not resize selectors")
                    assert state()["bindings"] == previous, "editing slot count changed the running media graph"
                    check_monitor_program()
                    assert ui("choose", indices=indices)
                    current = check_graph(quick_order=indices)
                    before = {item["cameraId"]: item["sourceUuid"] for item in previous}
                    after = {item["cameraId"]: item["sourceUuid"] for item in current["bindings"]}
                    assert all(before[key] == after[key] for key in before.keys() & after.keys()), \
                        "resizing the quick wall restarted retained compatible inputs"
                    wait_for(lambda: ui("video-progress", sources=len(set(indices))),
                        "variable-layout inputs did not advance before visible capture", timeout=15)
                    check_pixels("quick-wall-" + str(len(indices)), quick_order=indices)
                    previous = current["bindings"]
                evidence["checks"].extend(["quick-wall-one-four-seven-final-pixels", "quick-wall-draft-does-not-change-running-media",
                    "quick-wall-resize-retains-shared-inputs-and-idle-program"])
                assert ui("save")
                wait_for(lambda: len(read_json(paths[0]).get("cameras", [])) == 7,
                    "seven-slot workspace was not persisted")
                assert ui("logout")
                wait_for(lambda: state().get("phase") == "locked" and state().get("mediaSources") == 0,
                    "variable quick wall retained media after logout")
                assert ui("login", **account)
                check_graph(quick_order=[1, 2, 3, 4, 5, 1, 2])
                wait_for(lambda: ui("video-progress", sources=5), "restored quick-wall inputs did not advance", timeout=15)
                check_pixels("quick-wall-seven-restored", quick_order=[1, 2, 3, 4, 5, 1, 2])
                evidence["checks"].append("quick-wall-seven-save-logout-authenticated-restore")
                assert ui("choose", indices=[1, 2, 3, 4, 5])
                check_graph()
                assert ui("save")
                wait_for(lambda: len(read_json(paths[0]).get("cameras", [])) == 5,
                    "five-slot baseline was not restored to workspace")
                phase = "native-input-stall-and-rtsp-recovery"
                before_fault = {item["cameraId"]: item["sourceUuid"] for item in state()["bindings"]}
                interrupted_at = time.monotonic()
                rtsp.interrupt_publisher(0)
                wait_for(lambda: ui("video-progress", sources=5, stalled=1),
                    "native media source did not expose the interrupted input's stalled video callbacks", timeout=25)
                stalled_after = round((time.monotonic() - interrupted_at) * 1000)
                check_graph()
                resumed_at = time.monotonic()
                rtsp.restart_publisher(0)
                wait_for(lambda: ui("video-progress", sources=5),
                    "actual OBS media input did not recover after RTSP publishing resumed", timeout=35)
                recovered = check_graph()
                assert {item["cameraId"]: item["sourceUuid"] for item in recovered["bindings"]} == before_fault, \
                    "RTSP recovery replaced product media sources"
                check_pixels("native-rtsp-recovered")
                evidence["inputFault"] = {"interruptedInputs": 1, "stallObservedMs": stalled_after,
                    "recoveryAndPixelObservedMs": round((time.monotonic() - resumed_at) * 1000),
                    "sameSourceUuids": True}
                evidence["checks"].append("actual-obs-input-stall-and-rtsp-recovery-final-pixels")
                phase = "existing-studio-api-to-native-scene"
                code, _, studio = request("/api/v1/studio", cookie=cookie)
                assert code == 200
                fixture_scene = {"schemaVersion": 6, "revision": 0, "id": "fixture-five", "name": "Fixture Studio five",
                    "canvas": {"width": 1920, "height": 1080, "backgroundColor": "#000000"}, "sources": [], "items": []}
                for index in range(5):
                    source_id = f"fixture-source-{index}"
                    fixture_scene["sources"].append({"id": source_id, "kind": "camera", "name": f"Camera {index}",
                        "cameraId": f"fixture-{index + 1}", "profileId": "main", "hardwareDecode": "auto",
                        "muted": True, "volume": 1, "syncOffsetMs": 0, "monitoring": "off", "audioTrack": 1})
                    if index == 4:
                        # Existing schema explicitly selects no audio; video
                        # must remain usable rather than reject the scene.
                        fixture_scene["sources"][-1]["audioInputs"] = []
                    fixture_scene["items"].append({"id": f"fixture-item-{index}", "sourceId": source_id,
                        "x": (index % 3) * 640, "y": (index // 3) * 540, "width": 640, "height": 540,
                        "scaleMode": "contain", "crop": {"top": 0, "right": 0, "bottom": 0, "left": 0},
                        "visible": True, "locked": True, "zIndex": index})
                empty_scene = {"schemaVersion": 6, "revision": 0, "id": "fixture-empty", "name": "Empty Program",
                    "canvas": {"width": 1920, "height": 1080, "backgroundColor": "#000000"}, "sources": [], "items": []}
                studio.update(programSceneId="fixture-empty", previewSceneId="fixture-five",
                    scenes=[fixture_scene, empty_scene])
                code, _, studio = request("/api/v1/studio", studio, cookie, method="PUT", revision=studio["revision"])
                assert code == 200, "ordinary Studio API could not save the camera scene"
                assert ui("refresh")
                wait_for(lambda: state().get("studioChoices", [])[:1] == ["fixture-five"],
                    "saved Studio scene did not enter native choices")
                assert ui("scene", index=1, fixtureName="Fixture Studio five")
                wait_for(lambda: state().get("sceneId") == "fixture-five", "native action did not select saved Studio scene")
                check_graph()
                time.sleep(3)
                check_pixels("studio-scene")
                phase = "unrelated-studio-revision-preserves-fixed-scene"
                scene_state = state()
                scene_fingerprint = scene_state.get("sceneFingerprint")
                assert isinstance(scene_fingerprint, str) and len(scene_fingerprint) == 64
                scene_sources = {item["cameraId"]: item["sourceUuid"] for item in scene_state["bindings"]}
                assert ui("projector", slot=1)
                wait_for(lambda: len(state().get("projectors", [])) == 1, "saved-scene fixed projector did not open")
                unrelated = json.loads(json.dumps(studio["scenes"][0]))
                unrelated.update(id="fixture-unrelated", name="Unrelated saved scene")
                studio["scenes"].append(unrelated)
                studio["previewSceneId"] = unrelated["id"]
                code, _, studio = request("/api/v1/studio", studio, cookie, method="PUT", revision=studio["revision"])
                assert code == 200
                wait_for(lambda: state().get("phase") == "graph-applied" and
                    state().get("studioRevision") == studio["revision"] and
                    all(view["studioRevision"] == studio["revision"] for view in state().get("projectors", [])),
                    "unchanged displayed scene did not survive an unrelated Studio revision", timeout=8)
                assert state().get("sceneFingerprint") == scene_fingerprint
                assert len(state().get("projectors", [])) == 1
                check_projectors({1: "forward"}, scene_sources)
                check_pixels("studio-unrelated-revision", projector_orders={"fixed-scene-1": "forward"})
                assert ui("projector-close")
                wait_for(lambda: not state().get("projectors"), "saved-scene projector did not close")
                evidence["checks"].append("unrelated-studio-save-preserves-authorized-fixed-scene-and-main")
                assert ui("save")
                wait_for(lambda: split_workspace(read_json(paths[0]))[0] ==
                    {"schema": 2, "sceneId": "fixture-five"},
                    "scene-ID workspace save did not commit")
                assert ui("logout")
                wait_for(lambda: state().get("phase") == "locked", "Studio scene did not retire on logout")
                check_pixels("studio-logout", blank=True)
                assert ui("login", **account)
                wait_for(lambda: state().get("sceneId") == "fixture-five", "saved scene ID did not restore after authentication")
                check_graph()
                time.sleep(3)
                check_pixels("studio-restored")
                phase = "studio-revision-renewal"
                studio["scenes"][0]["name"] = "Fixture Studio five updated"
                code, _, changed_studio = request("/api/v1/studio", studio, cookie, method="PUT", revision=studio["revision"])
                assert code == 200
                wait_for(lambda: state().get("phase") == "locked", "changed canonical scene kept stale native media", timeout=8)
                check_pixels("studio-changed", blank=True)
                assert ui("login", **account)
                wait_for(lambda: state().get("sceneId") == "fixture-five" and
                    state().get("studioRevision") == changed_studio["revision"], "current Studio revision did not restore")
                check_graph()
                time.sleep(3)
                check_pixels("studio-current-revision")
                evidence["checks"].extend(["ordinary-studio-document-to-native-final-pixels",
                    "saved-scene-id-restores-only-after-login", "studio-revision-change-clears-stale-native-pixels"])
                # Restore the original five-camera workspace for subsequent
                # independent account, restart and permission regressions.
                phase = "restore-five-camera-workspace"
                assert ui("choose", indices=[1, 2, 3, 4, 5])
                wait_for(lambda: state().get("phase") == "graph-applied" and state().get("sceneId") == "",
                    "manual camera graph did not replace saved-scene mode")
                check_graph()
                assert ui("save")
                wait_for(lambda: split_workspace(read_json(paths[0]))[0] == saved,
                    "five-camera workspace save did not commit")
                phase = "same-canvas-source-retention"
                reference = {binding["cameraId"]: binding["sourceUuid"] for binding in state()["bindings"]}
                assert ui("choose", indices=[5, 4, 3, 2, 1])
                changed = check_graph(reverse=True)
                assert {binding["cameraId"]: binding["sourceUuid"] for binding in changed["bindings"]} == reference, \
                    "same-canvas layout change recreated compatible media sources"
                time.sleep(3)
                check_pixels("continuous-reordered", reverse=True)
                assert ui("choose", indices=[1, 2, 3, 4, 5])
                changed = check_graph()
                assert {binding["cameraId"]: binding["sourceUuid"] for binding in changed["bindings"]} == reference, \
                    "return layout recreated compatible media sources"
                evidence["checks"].append("same-canvas-layout-retains-owned-sources-without-projectors")
                evidence["checks"].append("local-monitor-switches-preserve-independent-program-output")
                phase = "fixed-scene-projectors"
                reference = {binding["cameraId"]: binding["sourceUuid"] for binding in state()["bindings"]}
                assert ui("projector", slot=1)
                wait_for(lambda: len(state().get("projectors", [])) == 1, "first native Scene projector did not open")
                checkpoint("projector-first-open")
                previous_geometry = state()["projectors"][0].get("geometry")
                previous_placement = read_json(paths[0]).get("projectorPlacements", {}).get("fixed-1")
                assert ui("projector-place", slot=1)
                moved = wait_for(lambda: next((view for view in state().get("projectors", [])
                    if view.get("slot") == 1 and view.get("geometry") != previous_geometry), None),
                    "actual projector move was not observed in the runtime state")
                placement = wait_for(lambda: (lambda value: value if value and value != previous_placement else None)(
                    read_json(paths[0]).get("projectorPlacements", {}).get("fixed-1")),
                    "actual projector move was not saved in its account workspace")
                assert {key: placement[key] for key in ("x", "y", "width", "height")} == moved.get("geometry"), \
                    "projector runtime geometry and saved preference disagree"
                evidence["projectorPlacement"] = placement
                checkpoint("projector-placed-and-saved")
                assert ui("projector-window-close", slot=1)
                wait_for(lambda: not state().get("projectors"), "placement probe did not close")
                checkpoint("projector-window-closed")
                assert ui("projector", slot=1)
                restored = wait_for(lambda: next((view for view in state().get("projectors", [])
                    if view.get("slot") == 1), None), "placement probe did not reopen")
                expected_rect = {key: placement[key] for key in ("x", "y", "width", "height")}
                evidence["projectorReopenGeometry"] = restored.get("geometry")
                evidence["projectorExpectedGeometry"] = expected_rect
                checkpoint("projector-reopened")
                wait_for(lambda: next((view for view in state().get("projectors", [])
                    if view.get("slot") == 1 and view.get("geometry") == expected_rect), None),
                    "reopened OBS projector did not restore its logical geometry")
                check_graph()
                evidence["checks"].append("account-projector-geometry-persists-and-restores-with-shared-inputs")
                assert ui("choose", indices=[5, 4, 3, 2, 1])
                check_graph(reverse=True)
                check_projectors({1: "forward"}, reference)
                assert ui("projector", slot=2)
                wait_for(lambda: len(state().get("projectors", [])) == 2, "second native Scene projector did not open")
                assert ui("choose", indices=[1, 1, 1, 1, 1])
                check_graph(repeat_first=True, expected_media=5)
                check_projectors({1: "forward", 2: "reverse"}, reference)
                time.sleep(3)
                check_pixels("fixed-different-scenes", repeat_first=True, expected_media=5,
                    projector_orders={"fixed-scene-1": "forward", "fixed-scene-2": "reverse"})
                wait_for(lambda: ui("video-progress", sources=5),
                    "main and fixed projector input progress was not shared", timeout=15)
                assert ui("projector-fullscreen", slot=1)
                wait_for(lambda: any(view["slot"] == 1 and view["fullscreen"] for view in state().get("projectors", [])),
                    "native Scene projector did not enter fullscreen")
                check_projectors({1: "forward", 2: "reverse"}, reference)
                check_pixels("fixed-fullscreen", repeat_first=True, expected_media=5,
                    projector_orders={"fixed-scene-fullscreen-1": "forward", "fixed-scene-2": "reverse"})
                assert ui("projector-fullscreen", slot=1)
                wait_for(lambda: any(view["slot"] == 1 and not view["fullscreen"] for view in state().get("projectors", [])),
                    "native Scene projector did not return to windowed mode")
                first_window = [window for window in fixed_windows() if window["role"] == "fixed-scene-1"]
                assert len(first_window) == 1 and ui("projector-window-close", slot=1)
                wait_for(lambda: len(state().get("projectors", [])) == 1 and owned_windows_closed(first_window),
                    "closed native projector retained its window or graph consumer")
                check_projectors({2: "reverse"}, reference)
                check_pixels("fixed-one-closed", repeat_first=True, expected_media=5,
                    projector_orders={"fixed-scene-2": "reverse"})
                assert ui("choose", indices=[1, 2, 3, 4, 5])
                check_graph()
                check_projectors({2: "reverse"}, reference)
                remaining_windows = fixed_windows()
                assert ui("projector-close")
                wait_for(lambda: state().get("projectors") == [] and owned_windows_closed(remaining_windows),
                    "close-projectors button did not retire the remaining window")
                check_graph()
                check_pixels("fixed-all-closed")
                evidence["checks"].extend(["two-fixed-scene-projectors-share-owned-decoders",
                    "main-switch-preserves-two-different-projector-scenes", "native-projector-fullscreen-windowed-final-pixels",
                    "closing-one-projector-preserves-other-and-main"])
                # Direct-only operation: plain RTSP monitoring with a silent Program
                # Scene must not have started the private MediaMTX relay or any
                # FFmpeg audio mixer as a child of the native host. Both appear
                # later only because a Scene or a Program output asked for them.
                host_pid = int(state()["pid"])
                remember_owned_pids([pid for pid, _ in child_processes(powershell, host_pid)])
                monitoring_children = child_processes(powershell, host_pid)
                unwanted = sorted({name for pid, name in monitoring_children
                    if name in ("mediamtx.exe", "ffmpeg.exe")})
                assert not unwanted, \
                    f"Program output helpers were running during Direct-only monitoring: {unwanted}"
                evidence["directOnlyHostChildren"] = sorted({name for _, name in monitoring_children})
                evidence["checks"].append("program-output-helpers-start-on-demand-only")
                phase = "native-program-take"
                checkpoint("program-choose")
                assert ui("choose", indices=[1, 2, 3, 4, 5])
                check_graph()
                checkpoint("program-choose-applied")
                alt_scene = {"schemaVersion": 6, "revision": 0, "id": "fixture-alt", "name": "Fixture Program alt",
                    "canvas": {"width": 1920, "height": 1080, "backgroundColor": "#000000"},
                    "sources": [{"id": "fixture-alt-source", "kind": "camera", "name": "Program alt camera",
                        "cameraId": "fixture-1", "profileId": "main", "hardwareDecode": "auto",
                        "muted": False, "volume": 0.75, "syncOffsetMs": 0, "monitoring": "off", "audioTrack": 2,
                        "audioInputs": [{"track": 0, "gain": 1, "muted": False, "syncOffsetMs": 0},
                            {"track": 1, "gain": 0.5, "muted": False, "syncOffsetMs": 0}]}],
                    "items": [{"id": "fixture-alt-item", "sourceId": "fixture-alt-source", "x": 0, "y": 0,
                        "width": 1920, "height": 1080, "scaleMode": "contain",
                        "crop": {"top": 0, "right": 0, "bottom": 0, "left": 0},
                        "visible": True, "locked": True, "zIndex": 0}]}
                code, _, studio = request("/api/v1/studio", cookie=cookie)
                assert code == 200
                kept = [scene for scene in studio["scenes"] if scene["id"] in ("fixture-five", "fixture-empty")]
                assert {scene["id"] for scene in kept} == {"fixture-five", "fixture-empty"}
                studio.update(programSceneId="fixture-five", previewSceneId="fixture-alt",
                    transition={"kind": "fade", "durationMs": 400}, scenes=kept + [alt_scene])
                code, _, studio = request("/api/v1/studio", studio, cookie=cookie, method="PUT", revision=studio["revision"])
                assert code == 200, "Studio accepted a second scene for the Program TAKE"
                wait_for(lambda: state().get("programSceneId") == "fixture-five" and
                    state().get("programApplyState") == "applied" and
                    state().get("program", {}).get("mediaSources") == 5,
                    "native Program did not apply the saved scene", timeout=20)
                check_monitor_program(program_scene="fixture-five", program_media=5)
                checkpoint("program-five-applied")
                # Audio configuration matrix, negative controls. Sources that
                # omit audioInputs keep the legacy single-source path, and the
                # fifth source's explicit empty audioInputs must silence that
                # source without starting an audio-only mixer. Neither variant
                # may create a mix source, so no native mixer entry exists yet
                # and the identically named TAKE source must not leak forward.
                wait_for(lambda: state().get("audioSources", []) == [],
                    "Program Scene without non-empty audioInputs started native audio mixers", timeout=10)
                evidence["audioMatrix"] = {"silentProgramScene": "fixture-five",
                    "mixersBeforeTake": len(state().get("audioSources", []))}
                assert ui("program-projector")
                wait_for(lambda: any(window.get("role") == "program-projector" for window in state().get("windows", [])),
                    "native Program projector did not open", timeout=8)
                checkpoint("program-projector-open")
                # fixture-five deliberately keeps its fifth source with explicit
                # empty audioInputs, so its silent video variant is a separate
                # owned source from the normal quick-wall input (5 + 1 = 6).
                check_pixels("program-before-take", quick_order=[1, 2, 3, 4, 5],
                    expected_media=6, program_scene="fixture-five", program_media=5,
                    projector_orders={"program-projector": "forward"})
                checkpoint("program-before-pixels")
                before_take = state().get("program", {}).get("sceneUuid")
                assert isinstance(before_take, str) and before_take
                # The initial Program application above exercised the real fade.
                # Use a cut for the TAKE so the outgoing scene must retire
                # immediately; this also verifies the transition selection path.
                studio["transition"] = {"kind": "cut", "durationMs": 0}
                code, _, studio = request("/api/v1/studio", studio, cookie=cookie, method="PUT",
                    revision=studio["revision"])
                assert code == 200
                checkpoint("program-take-request")
                code, _, taken = request("/api/v1/studio/take", cookie=cookie, method="POST", revision=studio["revision"])
                assert code == 200 and taken["programSceneId"] == "fixture-alt", "Studio TAKE did not commit the preview scene"
                checkpoint("program-take-committed")
                # The core flattens every runtime source identity into
                # "<scene>.<source>", and the product reports that full identity.
                # Comparing the short "fixture-alt-source" suffix would also
                # accept an identically named source owned by a different Scene
                # and could hide a cross-Scene audio leak.
                program_audio_id = "fixture-alt.fixture-alt-source"
                assert not any(item.get("sourceId") == program_audio_id
                               for item in state().get("audioSources", [])), \
                    "Program TAKE audio source leaked before the TAKE was applied"

                def audio_diagnostics(stage, observed):
                    """Bounded, redacted mixer evidence for one failed stage."""
                    return {"stage": stage, "expectedSourceId": program_audio_id,
                        "expectedMonitorMixers": 2,
                        "programSceneId": state().get("programSceneId"),
                        "programApplyState": state().get("programApplyState"),
                        "programMediaSources": state().get("program", {}).get("mediaSources"),
                        "observed": [{key: item.get(key) for key in ("sourceId", "available", "active",
                            "showing", "processExitCode", "mediaState", "peakDbfs", "mixers", "muted",
                            "volume", "syncOffset")} for item in observed],
                        "mixerLog": [str(item.get("mixerLog", ""))[:160] for item in observed]}

                def wait_program_audio(stage, predicate, timeout=20):
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        observed = state().get("audioSources", [])
                        assert len({item.get("sourceId") for item in observed}) == len(observed), \
                            "duplicate native audio mixers share one Program source identity"
                        result = predicate(observed)
                        if result:
                            return result
                        time.sleep(.1)
                    detail = audio_diagnostics(stage, state().get("audioSources", []))
                    evidence["programAudioFailure"] = detail
                    raise AssertionError(f"Program TAKE audio gate failed at {stage}: "
                        + json.dumps(detail, sort_keys=True)[:1500])

                def program_scene_applied():
                    current = state()
                    return current if (current.get("programSceneId") == "fixture-alt"
                        and current.get("programApplyState") == "applied"
                        and current.get("program", {}).get("mediaSources") == 2) else None

                wait_for(program_scene_applied, "native Program did not switch to the TAKE Scene", timeout=20)
                checkpoint("program-take-scene-applied")

                def designated_mixer(observed):
                    matches = [item for item in observed if item.get("sourceId") == program_audio_id]
                    if len(matches) != 1:
                        return None
                    return matches[0] if matches[0].get("available") is True else None

                mixer = wait_program_audio("designated-mixer", designated_mixer)
                checkpoint("program-take-audio-source")

                def designated_signal(observed):
                    entry = designated_mixer(observed)
                    if entry and entry.get("mediaState") == 1 and entry.get("peakDbfs", -120) > -60:
                        return entry
                    return None

                mixer = wait_program_audio("designated-mixer-signal", designated_signal)
                checkpoint("program-take-audio-signal")
                assert mixer.get("mixers") == 2, \
                    f"audioTrack 2 did not route to the second OBS monitor bus (mixers={mixer.get('mixers')})"
                assert mixer.get("volume") == 0.75 and mixer.get("muted") is False, \
                    "Program mix source did not apply its saved volume and mute settings"
                evidence["programAudio"] = {key: mixer.get(key) for key in ("sourceId", "available", "active",
                    "showing", "processExitCode", "mediaState", "peakDbfs", "mixers", "muted", "volume")}
                evidence["checks"].extend(["nonempty-audio-inputs-native-mix-peak",
                    "program-take-mixer-identity-and-bus", "explicit-empty-audio-inputs-stay-silent"])
                after_take = state().get("program", {}).get("sceneUuid")
                assert isinstance(after_take, str) and after_take != before_take, "TAKE reused the previous Program scene"
                time.sleep(1)  # Allow the cut TAKE and source retirement to settle.
                code, _, studio_runtime = request("/api/v1/studio/runtime", cookie=cookie)
                assert code == 200 and studio_runtime["native"] is True and studio_runtime["status"] == "applied" and \
                    studio_runtime["appliedRevision"] == taken["revision"] and \
                    studio_runtime["appliedSceneId"] == "fixture-alt", \
                    "Program runtime receipt did not match the committed TAKE"
                checkpoint("program-runtime-receipt")
                check_pixels("program-after-take", quick_order=[1, 2, 3, 4, 5],
                    expected_media=7, program_scene="fixture-alt", program_media=2,
                    projector_orders={"program-projector": "quick-1"})
                checkpoint("program-after-pixels")
                # The same native host must produce real composite output, not a
                # separate prototype or an NVR restream. Record the applied
                # Program scene, then verify the finalized MP4's streams and
                # final pixels, including distinct temporal timecode frames.
                phase = "program-recording"
                # Negative control on the real output path: a blocked recording root
                # must refuse the start and report the concrete reason in the status
                # receipt instead of leaving the product claiming an active recording.
                program_recordings = profile / "recordings" / "program"
                assert program_recordings.is_dir(), "supervisor did not prepare the Program recordings root"
                program_recordings.rmdir()
                program_recordings.write_text("blocked by the product gate", encoding="utf-8")
                assert ui("record-program")
                wait_for(lambda: state().get("programOutput", {}).get("recording") is False and
                    state().get("programOutput", {}).get("recordingError") == "recording-directory-failed",
                    "blocked Program recording root did not surface a concrete failure", timeout=10)
                evidence["recordingFailureReceipt"] = state().get("programOutput", {}).get("recordingError")
                assert not state().get("programOutput", {}).get("recordingPath"), \
                    "refused recording still promised an artifact path"
                program_recordings.unlink()
                program_recordings.mkdir()
                checkpoint("program-recording-refused")
                # The Scene routes its audio through the dedicated mix source while the
                # camera source stays muted, so the reported selection mask is the
                # evidence that the recorder will encode the Scene's bus and not bus 0.
                selected = state().get("programOutput", {}).get("selectedAudioTracks")
                assert selected == 2, \
                    f"applied Program Scene reported audio track mask {selected}; expected 2 (audioTrack 2)"
                evidence["programSelectedAudioTrackMask"] = selected
                assert ui("record-program")
                wait_for(lambda: state().get("programOutput", {}).get("recording") is True,
                    "native Program recording did not start", timeout=20)
                checkpoint("program-recording-started")
                time.sleep(5.5)
                assert ui("record-program")
                def recording_ready():
                    value = state().get("programOutput", {})
                    path = value.get("recordingPath") if isinstance(value, dict) else None
                    return value if (value.get("recording") is False and value.get("recordingReady") is True and
                        isinstance(path, str) and Path(path).is_file() and Path(path).suffix.lower() == ".mp4") else None
                recorded = wait_for(recording_ready, "native Program MP4 was not finalized", timeout=120)
                checkpoint("program-recording-finalized")
                recorded_path = Path(recorded["recordingPath"])
                probe = subprocess.run([str(runtime / "bin/ffprobe.exe"), "-v", "error", "-show_entries",
                    "stream=codec_name,codec_type,width,height:format=duration", "-of", "json", str(recorded_path)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
                assert probe.returncode == 0, "recorded Program MP4 is not readable"
                document = json.loads(probe.stdout)
                streams = document.get("streams", [])
                video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
                audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
                assert len(video_streams) == 1 and video_streams[0].get("codec_name") == "h264" and \
                    video_streams[0].get("width") == 1920 and video_streams[0].get("height") == 1080, \
                    "recorded Program video stream is not H.264 1920x1080"
                assert len(audio_streams) == 1 and audio_streams[0].get("codec_name") == "aac", \
                    "recorded Program audio stream is not AAC"
                assert float(document.get("format", {}).get("duration", 0)) >= 4.0, "recorded Program is too short"
                frames = private / "program-recording-frames"
                frames.mkdir()
                ffmpeg = runtime / "bin/ffmpeg.exe"
                for index, offset in enumerate((0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)):
                    extract = subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-i", str(recorded_path), "-ss", str(offset), "-frames:v", "1",
                        str(frames / f"client-{index}.bmp")], capture_output=True, timeout=30)
                    assert extract.returncode == 0 and (frames / f"client-{index}.bmp").is_file(), \
                        "could not extract a recorded Program frame"
                analysis = subprocess.run([shutil.which("node"), str(HERE / "pixel-pattern.cjs"), "analyze",
                    str(frames), "program-projector", "quick-1", "true"], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=20)
                pixel_result = json.loads(analysis.stdout) if analysis.returncode == 0 else {}
                assert pixel_result.get("passed") is True, "recorded Program frames did not match the applied scene"
                evidence["checks"].append("program-composite-mp4-recording")
                checkpoint("program-recording-pixels")
                # Decoded audio, the output-bus positive control. The Program mix
                # sums the fixture's two fixed pitches, so both bands must appear
                # in the finished file. A recorder pinned to OBS track 0 while the
                # Scene selects track 2 produces a silent MP4 even though the
                # product meter reports a peak, which a stream header cannot show.
                recording_mask = recorded.get("audioTracks")
                assert recording_mask == 2, \
                    f"Program recording encoded audio track mask {recording_mask}; expected 2 for audioTrack 2"
                recorded_low = pixel_windows.band_rms(ffmpeg, str(recorded_path), 0, lowpass=600)
                recorded_high = pixel_windows.band_rms(ffmpeg, str(recorded_path), 0, highpass=660)
                evidence["programRecordingBandRms"] = {"below600Hz": recorded_low,
                    "above660Hz": recorded_high, "audioTrackMask": recording_mask}
                assert recorded_low > 150 and recorded_high > 150, \
                    "recorded Program audio lost one of the two fixture pitches"
                evidence["checks"].append("program-recording-decodes-both-fixture-pitches")
                checkpoint("program-recording-audio-decoded")
                # Second bus configuration: the same host must stay audible when
                # the Program source selects the default output track. This is the
                # non-default-versus-default reproduction the output bus needs.
                phase = "program-recording-default-bus"
                default_scene = json.loads(json.dumps(alt_scene))
                default_scene.update(id="fixture-audio-default", name="Fixture Program default bus")
                default_scene["sources"][0]["audioTrack"] = 1
                code, _, studio = request("/api/v1/studio", cookie=cookie)
                assert code == 200
                studio["scenes"] = [scene for scene in studio["scenes"]
                    if scene["id"] != "fixture-audio-default"] + [default_scene]
                studio["programSceneId"] = "fixture-audio-default"
                code, _, studio = request("/api/v1/studio", studio, cookie=cookie, method="PUT",
                    revision=studio["revision"])
                assert code == 200, "Studio did not accept the default-bus Program scene"
                # Which half of the chain refused the Scene? The core stores the host's
                # own Program apply receipt (state plus bounded error), so a product
                # refusal cannot be read as a timing problem. The native transport
                # endpoints are host-token only and are deliberately not used here.
                def program_runtime():
                    code, _, runtime_receipt = request("/api/v1/studio/runtime", cookie=cookie)
                    if code != 200:
                        return {"code": code}
                    return {key: runtime_receipt.get(key) for key in
                        ("native", "studioRevision", "programSceneId", "status", "targetRevision",
                         "targetSceneId", "appliedRevision", "appliedSceneId", "error")}

                evidence["programDefaultBusRuntimeReceipt"] = program_runtime()

                def default_bus_applied():
                    value = state()
                    evidence["programDefaultBusApplyAttempt"] = apply_attempt(value)
                    evidence["programDefaultBusRuntimeReceipt"] = program_runtime()
                    return value if (value.get("programSceneId") == "fixture-audio-default" and
                        value.get("programApplyState") == "applied" and
                        isinstance(value.get("program"), dict) and
                        value["program"].get("mediaSources") == 2) else None
                def default_bus_failure():
                    return ("default-bus Program scene did not apply: core="
                        + json.dumps(evidence.get("programDefaultBusRuntimeReceipt", {}), sort_keys=True)[:340]
                        + " host=" + json.dumps(evidence.get("programDefaultBusApplyAttempt", {}), sort_keys=True)[:400])
                wait_for(default_bus_applied, default_bus_failure, timeout=45)
                checkpoint("program-default-bus-applied")
                default_selection = state().get("programOutput", {}).get("selectedAudioTracks")
                assert default_selection == 1, \
                    f"default-bus Program Scene reported audio track mask {default_selection}; expected 1"
                evidence["programDefaultBusSelectedMask"] = default_selection
                assert ui("record-program")
                wait_for(lambda: state().get("programOutput", {}).get("recording") is True,
                    "default-bus Program recording did not start", timeout=20)
                time.sleep(5.5)
                assert ui("record-program")
                def default_recording_ready():
                    value = state().get("programOutput", {})
                    path = value.get("recordingPath") if isinstance(value, dict) else None
                    return value if (value.get("recording") is False and value.get("recordingReady") is True and
                        isinstance(path, str) and Path(path).is_file() and Path(path).suffix.lower() == ".mp4") else None
                default_recorded = wait_for(default_recording_ready, "default-bus Program MP4 was not finalized",
                    timeout=120)
                default_path = Path(default_recorded["recordingPath"])
                assert default_path != recorded_path, "second Program recording reused the first file"
                assert default_recorded.get("audioTracks") == 1, \
                    f"default-bus recording encoded mask {default_recorded.get('audioTracks')}, expected 1"
                default_low = pixel_windows.band_rms(ffmpeg, str(default_path), 0, lowpass=600)
                default_high = pixel_windows.band_rms(ffmpeg, str(default_path), 0, highpass=660)
                evidence["programRecordingDefaultBus"] = {"path": default_path.name,
                    "below600Hz": default_low, "above660Hz": default_high,
                    "audioTrackMask": default_recorded.get("audioTracks")}
                assert default_low > 150 and default_high > 150, \
                    "default-bus Program recording lost one of the two fixture pitches"
                evidence["checks"].append("program-recording-default-and-nondefault-bus-both-audible")
                checkpoint("program-default-bus-recording-decoded")
                # WHIP publishing uses the same Program OBS output and owns a
                # private MediaMTX only while streaming. RTSP playback proves
                # the packets reached a real consumer, not just an active flag.
                phase = "program-streaming"
                assert ui("stream-program")
                def streaming_ready():
                    value = state().get("programOutput", {})
                    return value if (isinstance(value, dict) and value.get("streaming") is True and
                        value.get("streamConnected") is True and
                        isinstance(value.get("streamPlaybackUrl"), str)) else None
                streamed = wait_for(streaming_ready, "native Program WHIP publishing did not start", timeout=40)
                playback_url = streamed["streamPlaybackUrl"]
                assert re.fullmatch(r"rtsp://127\.0\.0\.1:[0-9]{2,5}/program", playback_url), \
                    "native Program publisher exposed an unexpected playback URL"
                checkpoint("program-streaming-started")
                def readable_stream():
                    probe = subprocess.run([str(runtime / "bin/ffprobe.exe"), "-v", "error",
                        "-rtsp_transport", "tcp", "-show_entries", "stream=codec_name,codec_type", "-of", "json",
                        playback_url], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
                    return json.loads(probe.stdout).get("streams", []) if probe.returncode == 0 else []
                stream_streams = []
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    stream_streams = readable_stream()
                    if stream_streams:
                        break
                    time.sleep(0.5)
                assert stream_streams, "published Program stream is not readable"
                assert any(stream.get("codec_type") == "video" and stream.get("codec_name") == "h264"
                    for stream in stream_streams), "published Program has no H.264 video"
                assert any(stream.get("codec_type") == "audio" and stream.get("codec_name") == "opus"
                    for stream in stream_streams), "published Program has no Opus audio"
                # An Opus stream header is not audible evidence. Decode the real
                # consumer and require both fixture pitches inside the band split.
                assert streamed.get("audioTracks") == 1, \
                    f"WHIP publisher encoded mask {streamed.get('audioTracks')}, expected the default bus 1"
                published_low = pixel_windows.band_rms(ffmpeg, playback_url, 0, lowpass=600)
                published_high = pixel_windows.band_rms(ffmpeg, playback_url, 0, highpass=660)
                evidence["programStreamBandRms"] = {"below600Hz": published_low,
                    "above660Hz": published_high, "audioTrackMask": streamed.get("audioTracks")}
                assert published_low > 150 and published_high > 150, \
                    "published Program audio lost one of the two fixture pitches"
                evidence["checks"].append("program-whip-decodes-both-fixture-pitches")
                stream_frames = subprocess.run([str(runtime / "bin/ffprobe.exe"), "-v", "error",
                    "-rtsp_transport", "tcp", "-select_streams", "v:0", "-read_intervals", "%+#20",
                    "-show_entries", "frame=pts_time", "-of", "json", playback_url],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
                assert stream_frames.returncode == 0 and len(json.loads(stream_frames.stdout).get("frames", [])) >= 10, \
                    "published Program did not deliver enough video frames"
                assert ui("stream-program")
                wait_for(lambda: state().get("programOutput", {}).get("streaming") is False and
                    state().get("programOutput", {}).get("mediaMtxRunning") is False,
                    "native Program publisher did not release MediaMTX", timeout=30)
                evidence["checks"].append("program-composite-whip-stream")
                checkpoint("program-streaming-stopped")
                # --- Received-output audio acceptance ---------------------------
                # Everything below decodes what the user actually receives: the
                # finished Program MP4 and the published stream. Scene booleans and
                # stream headers are not evidence that a chosen bus carried the
                # expected tone or that another bus stayed free of cross-talk.
                def apply_program_scene(scene, expected_media):
                    code, _, studio = request("/api/v1/studio", cookie=cookie)
                    assert code == 200
                    studio["scenes"] = [item for item in studio["scenes"]
                        if item["id"] != scene["id"]] + [scene]
                    studio["programSceneId"] = scene["id"]
                    code, _, studio = request("/api/v1/studio", studio, cookie=cookie, method="PUT",
                        revision=studio["revision"])
                    assert code == 200, f"Studio did not accept the {scene['id']} Program Scene"
                    def scene_applied():
                        value = state()
                        evidence["programApplyAttempt"] = apply_attempt(value)
                        return value if (value.get("programSceneId") == scene["id"] and
                            value.get("programApplyState") == "applied" and
                            isinstance(value.get("program"), dict) and
                            value["program"].get("mediaSources") == expected_media) else None
                    def scene_applied_with_receipt():
                        value = scene_applied()
                        evidence["programRuntimeReceipt"] = program_runtime()
                        return value
                    wait_for(scene_applied_with_receipt,
                        f"native Program did not apply the {scene['id']} Scene: core="
                        + json.dumps(evidence.get("programRuntimeReceipt", {}), sort_keys=True)[:340]
                        + " host=" + json.dumps(evidence.get("programApplyAttempt", {}), sort_keys=True)[:400],
                        timeout=30)

                def record_program_output(label):
                    assert ui("record-program")
                    wait_for(lambda: state().get("programOutput", {}).get("recording") is True,
                        f"{label} Program recording did not start", timeout=20)
                    time.sleep(5.5)
                    assert ui("record-program")
                    def finished():
                        value = state().get("programOutput", {})
                        path = value.get("recordingPath") if isinstance(value, dict) else None
                        return value if (value.get("recording") is False and
                            value.get("recordingReady") is True and isinstance(path, str) and
                            Path(path).is_file() and Path(path).suffix.lower() == ".mp4") else None
                    receipt = wait_for(finished, f"{label} Program MP4 was not finalized", timeout=120)
                    assert audio_stream_count(Path(receipt["recordingPath"])) >= 1, \
                        f"{label} Program MP4 has no decodable stream"
                    return receipt

                def advancing_video_frames(path, minimum):
                    """Video really moved: enough frames and strictly rising timestamps."""
                    probe = subprocess.run([str(runtime / "bin/ffprobe.exe"), "-v", "error",
                        "-select_streams", "v:0", "-read_intervals", "%+#40",
                        "-show_entries", "frame=pts_time", "-of", "json", str(path)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
                    assert probe.returncode == 0, f"{path.name} video stream is not probeable"
                    stamps = [float(item["pts_time"]) for item in json.loads(probe.stdout).get("frames", [])
                        if item.get("pts_time") is not None]
                    assert len(stamps) >= minimum, f"{path.name} delivered fewer than {minimum} video frames"
                    assert all(later > earlier for earlier, later in zip(stamps, stamps[1:])), \
                        f"{path.name} video timestamps are not advancing"
                    return len(stamps)

                def audio_stream_count(path):
                    probe = subprocess.run([str(runtime / "bin/ffprobe.exe"), "-v", "error",
                        "-select_streams", "a", "-show_entries", "stream=index,codec_name,codec_type",
                        "-of", "json", str(path)], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=30)
                    assert probe.returncode == 0, f"{path.name} audio streams are not probeable"
                    streams = json.loads(probe.stdout).get("streams", [])
                    assert all(item.get("codec_type") == "audio" for item in streams), \
                        "audio stream probe returned a non-audio stream"
                    return len(streams)

                def program_audio_entry(source_id):
                    """The applied native mix source, or None while a Scene switch settles."""
                    matches = [item for item in state().get("audioSources", [])
                        if item.get("sourceId") == source_id]
                    return matches[0] if len(matches) == 1 else None

                phase = "program-bus-isolation"
                # Two Sources on two different output buses with two different fixed
                # pitches. The finished file must show each bus carrying only its own
                # tone: a recorder or mix source that leaks across buses produces the
                # other pitch in the same encoded track.
                isolation_scene = {"schemaVersion": 6, "revision": 0, "id": "fixture-isolation",
                    "name": "Fixture Program bus isolation",
                    "canvas": {"width": 1920, "height": 1080, "backgroundColor": "#000000"},
                    "sources": [
                        {"id": "iso-low", "kind": "camera", "name": "Bus two camera",
                            "cameraId": "fixture-1", "profileId": "main", "hardwareDecode": "auto",
                            "muted": False, "volume": 1, "syncOffsetMs": 0, "monitoring": "off",
                            "audioTrack": 2, "audioInputs": [
                                {"track": 0, "gain": 1, "muted": False, "syncOffsetMs": 0}]},
                        {"id": "iso-high", "kind": "camera", "name": "Bus three camera",
                            "cameraId": "fixture-2", "profileId": "main", "hardwareDecode": "auto",
                            "muted": False, "volume": 1, "syncOffsetMs": 0, "monitoring": "off",
                            "audioTrack": 3, "audioInputs": [
                                {"track": 0, "gain": 1, "muted": False, "syncOffsetMs": 0}]}],
                    "items": [
                        {"id": "iso-low-item", "sourceId": "iso-low", "x": 0, "y": 0,
                            "width": 960, "height": 1080, "scaleMode": "contain",
                            "crop": {"top": 0, "right": 0, "bottom": 0, "left": 0},
                            "visible": True, "locked": True, "zIndex": 0},
                        {"id": "iso-high-item", "sourceId": "iso-high", "x": 960, "y": 0,
                            "width": 960, "height": 1080, "scaleMode": "contain",
                            "crop": {"top": 0, "right": 0, "bottom": 0, "left": 0},
                            "visible": True, "locked": True, "zIndex": 1}]}
                apply_program_scene(isolation_scene, 4)
                checkpoint("program-bus-isolation-applied")
                assert {item.get("sourceId") for item in state().get("audioSources", [])} == {
                    "fixture-isolation.iso-low", "fixture-isolation.iso-high"}, \
                    "bus isolation Scene did not create exactly two native mix sources"
                assert {item.get("mixers") for item in state().get("audioSources", [])} == {2.0, 4.0}, \
                    "the two mix sources did not route to two different OBS output buses"
                isolation = record_program_output("bus isolation")
                isolation_path = Path(isolation["recordingPath"])
                assert isolation.get("audioTracks") == 6, \
                    f"bus isolation recording encoded mask {isolation.get('audioTracks')}, expected 6"
                assert audio_stream_count(isolation_path) == 2, \
                    "bus isolation recording did not encode one audio track per selected bus"
                isolation_first_440 = pixel_windows.tone_amplitude(ffmpeg, str(isolation_path), 0, 440)
                isolation_first_1200 = pixel_windows.tone_amplitude(ffmpeg, str(isolation_path), 0, 1200)
                isolation_second_1200 = pixel_windows.tone_amplitude(ffmpeg, str(isolation_path), 1, 1200)
                isolation_second_440 = pixel_windows.tone_amplitude(ffmpeg, str(isolation_path), 1, 440)
                evidence["programBusIsolation"] = {
                    "busTwo": {"at440Hz": isolation_first_440, "at1200Hz": isolation_first_1200},
                    "busThree": {"at1200Hz": isolation_second_1200, "at440Hz": isolation_second_440}}
                assert isolation_first_440 > 200 and isolation_first_1200 < 60, \
                    "bus two recording lost its 440 Hz tone or leaked the other bus's pitch"
                assert isolation_second_1200 > 200 and isolation_second_440 < 60, \
                    "bus three recording lost its 1200 Hz tone or leaked the other bus's pitch"
                advancing_video_frames(isolation_path, 15)
                evidence["checks"].append("program-output-buses-are-isolated-in-the-recorded-file")
                checkpoint("program-bus-isolation-decoded")
                phase = "program-track-controls"
                # Per-track mute and gain, verified acoustically in the same file.
                def alt_variant(scene_id, inputs):
                    variant = json.loads(json.dumps(alt_scene))
                    variant.update(id=scene_id, name="Fixture Program " + scene_id)
                    variant["sources"][0]["audioInputs"] = inputs
                    return variant
                muted_scene = alt_variant("fixture-alt-mute", [
                    {"track": 0, "gain": 1, "muted": False, "syncOffsetMs": 0},
                    {"track": 1, "gain": 1, "muted": True, "syncOffsetMs": 0}])
                apply_program_scene(muted_scene, 2)
                muted = record_program_output("per-track mute")
                muted_path = Path(muted["recordingPath"])
                muted_440 = pixel_windows.tone_amplitude(ffmpeg, str(muted_path), 0, 440)
                muted_880 = pixel_windows.tone_amplitude(ffmpeg, str(muted_path), 0, 880)
                evidence["programTrackMute"] = {"at440Hz": muted_440, "at880Hz": muted_880,
                    "audioTrackMask": muted.get("audioTracks")}
                assert muted.get("audioTracks") == 2, \
                    f"muted-track recording encoded mask {muted.get('audioTracks')}, expected 2"
                assert muted_440 > 200 and muted_880 < 60, \
                    "muting one input track did not remove that pitch from the received file"
                evidence["checks"].append("per-track-mute-is-audible-in-the-recorded-file")
                checkpoint("program-track-mute-decoded")
                full_gain = alt_variant("fixture-alt-gain-full", [
                    {"track": 0, "gain": 1, "muted": False, "syncOffsetMs": 0},
                    {"track": 1, "gain": 1, "muted": False, "syncOffsetMs": 0}])
                apply_program_scene(full_gain, 2)
                gain_full = record_program_output("per-track gain reference")
                gain_full_path = Path(gain_full["recordingPath"])
                gain_full_440 = pixel_windows.tone_amplitude(ffmpeg, str(gain_full_path), 0, 440)
                gain_full_880 = pixel_windows.tone_amplitude(ffmpeg, str(gain_full_path), 0, 880)
                low_gain = alt_variant("fixture-alt-gain-low", [
                    {"track": 0, "gain": 1, "muted": False, "syncOffsetMs": 0},
                    {"track": 1, "gain": 0.2, "muted": False, "syncOffsetMs": 0}])
                apply_program_scene(low_gain, 2)
                gain_low = record_program_output("per-track gain reduced")
                gain_low_path = Path(gain_low["recordingPath"])
                gain_low_440 = pixel_windows.tone_amplitude(ffmpeg, str(gain_low_path), 0, 440)
                gain_low_880 = pixel_windows.tone_amplitude(ffmpeg, str(gain_low_path), 0, 880)
                evidence["programTrackGain"] = {"gainOne": {"at440Hz": gain_full_440,
                    "at880Hz": gain_full_880}, "gainPointTwo": {"at440Hz": gain_low_440,
                    "at880Hz": gain_low_880}}
                assert gain_full_440 > 200 and gain_full_880 > 200, \
                    "both tracks at gain one were not audible in the received file"
                # Linear gain 0.2 leaves about a fifth of that pitch's amplitude.
                # The tolerance excludes "gain reached the mix source but the
                # mixer ignored it" while allowing for AAC and resampler loss.
                assert 0.05 < gain_low_880 / gain_full_880 < 0.55, \
                    f"gain 0.2 did not scale the second track ({gain_low_880} of {gain_full_880})"
                assert gain_low_440 > 200 and 0.6 < gain_low_440 / gain_full_440 < 1.5, \
                    "reducing one track's gain also changed the other track"
                evidence["checks"].append("per-track-gain-is-audible-in-the-recorded-file")
                checkpoint("program-track-gain-decoded")
                phase = "program-track-offset"
                # Per-track sync offsets reach the owned mixer as leading silence, and
                # the negative offset normalizes into the mix source's own sync offset.
                offset_scene = alt_variant("fixture-alt-offset", [
                    {"track": 0, "gain": 1, "muted": False, "syncOffsetMs": 300},
                    {"track": 1, "gain": 1, "muted": False, "syncOffsetMs": -200}])
                apply_program_scene(offset_scene, 2)
                def offset_ready():
                    # The entry is legitimately absent while the previous Program
                    # source retires, so probe it instead of dereferencing None.
                    entry = program_audio_entry("fixture-alt-offset.fixture-alt-source")
                    return entry if entry and entry.get("available") else None
                offset_entry = wait_for(offset_ready,
                    "offset Scene mix source did not become available", timeout=20)
                assert offset_entry.get("syncOffset") == -200_000_000, \
                    f"negative per-track offset did not normalize into the mix source ({offset_entry.get('syncOffset')})"
                applied = [(item.get("track"), item.get("appliedDelayMs"), item.get("syncOffsetMs"))
                    for item in offset_entry.get("audioInputs", [])]
                assert applied == [(0, 500, 300), (1, 0, -200)], \
                    f"per-track offsets did not reach the applied mixer as configured: {applied}"
                assert offset_entry.get("mixers") == 2, "offset Scene mix source changed its output bus"
                evidence["programTrackOffsets"] = {"sourceSyncNs": offset_entry.get("syncOffset"),
                    "appliedInputs": applied}
                evidence["checks"].append("per-track-sync-offsets-reach-the-applied-mixer")
                checkpoint("program-track-offset-applied")
                phase = "program-whip-disconnect"
                # WHIP relay loss: killing the product's own private MediaMTX child
                # must surface a concrete disconnect instead of a permanently
                # "connected" publisher, and the next start must recover. The Scene
                # audio mixers are separate owned helpers, so record them first and
                # require the same set afterwards instead of demanding no FFmpeg at all.
                scene_mixers = sorted(pid for pid, name in child_processes(powershell, int(state()["pid"]))
                    if name == "ffmpeg.exe")
                relay_children = [pid for pid, name in child_processes(powershell, int(state()["pid"]))
                    if name == "mediamtx.exe"]
                assert relay_children == [], "MediaMTX survived the normal publisher stop"
                assert ui("stream-program")
                recovered_stream = wait_for(streaming_ready, "Program WHIP did not start for the disconnect probe",
                    timeout=40)
                relay_children = [pid for pid, name in child_processes(powershell, int(state()["pid"]))
                    if name == "mediamtx.exe"]
                remember_owned_pids(relay_children)
                assert len(relay_children) == 1, \
                    f"Program streaming owned {len(relay_children)} MediaMTX children, expected one"
                evidence["whipRelayPid"] = relay_children[0]
                terminate_process(powershell, relay_children[0])
                wait_for(lambda: state().get("programOutput", {}).get("streaming") is False and
                    str(state().get("programOutput", {}).get("streamError", "")).startswith("whip-") and
                    state().get("programOutput", {}).get("mediaMtxRunning") is False,
                    "killing the private MediaMTX relay did not surface a WHIP disconnect", timeout=30)
                evidence["whipDisconnectError"] = str(state().get("programOutput", {}).get("streamError"))[:120]
                disconnected_url = recovered_stream.get("streamPlaybackUrl")
                checkpoint("program-whip-disconnect-reported")
                assert ui("stream-program")
                restarted_stream = wait_for(streaming_ready,
                    "Program WHIP could not start again after a relay loss", timeout=40)
                assert restarted_stream.get("streamConnected") is True, \
                    "restarted publisher never delivered frames again"
                assert restarted_stream.get("streamPlaybackUrl") != disconnected_url, \
                    "recovered publisher reused the relay endpoint of the killed process"
                replay = subprocess.run([str(runtime / "bin/ffprobe.exe"), "-v", "error",
                    "-rtsp_transport", "tcp", "-show_entries", "stream=codec_name,codec_type", "-of", "json",
                    restarted_stream["streamPlaybackUrl"]], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=30)
                assert replay.returncode == 0 and any(item.get("codec_type") == "video"
                    for item in json.loads(replay.stdout).get("streams", [])), \
                    "recovered publisher is not readable by a real consumer"
                assert ui("stream-program")
                wait_for(lambda: state().get("programOutput", {}).get("streaming") is False and
                    state().get("programOutput", {}).get("mediaMtxRunning") is False,
                    "recovered publisher did not release MediaMTX after stopping", timeout=30)
                after_stop = child_processes(powershell, int(state()["pid"]))
                leaked_relay = sorted(pid for pid, name in after_stop if name == "mediamtx.exe")
                mixers_after = sorted(pid for pid, name in after_stop if name == "ffmpeg.exe")
                assert leaked_relay == [], \
                    f"Program output kept the private MediaMTX relay after stopping: {leaked_relay}"
                assert mixers_after == scene_mixers, \
                    f"stopping Program output changed the Scene audio mixers ({scene_mixers} -> {mixers_after})"
                evidence["sceneAudioMixers"] = mixers_after
                evidence["checks"].extend(["whip-relay-loss-is-reported-and-recoverable",
                    "program-output-helpers-are-released-after-stop"])
                checkpoint("program-output-resources-released")
                phase = "support-bundle"
                assert ui("support-bundle")
                def support_bundle_ready():
                    value = state().get("supportBundle", {})
                    path = value.get("path") if isinstance(value, dict) else None
                    return value if isinstance(path, str) and Path(path).is_file() else None
                bundle_state = wait_for(support_bundle_ready, "native support bundle was not written", timeout=20)
                bundle_path = Path(bundle_state["path"])
                assert bundle_path.stat().st_size <= 262144, "native support bundle exceeds its bound"
                bundle_text = bundle_path.read_text(encoding="utf-8")
                assert all(marker not in bundle_text for marker in ("rtsp://", "rtsps://", "http://", "https://")), \
                    "native support bundle retained a private media or service URL"
                bundle = json.loads(bundle_text)
                assert bundle.get("schema") == 1 and bundle.get("kind") == "native-product-support-bundle"
                assert isinstance(bundle.get("audioSources"), list) and isinstance(bundle.get("obsLogMarkers"), dict)
                assert isinstance(bundle.get("windows"), list) and isinstance(bundle.get("programOutput"), dict)
                evidence["checks"].append("native-support-bundle-redacted")
                checkpoint("support-bundle-written")
                checkpoint("program-projector-close")
                assert ui("projector-close")
                checkpoint("program-projector-closed")
                wait_for(lambda: not state().get("windows") or
                    all(window.get("role") == "main-preview" for window in state().get("windows", [])),
                    "Program projector did not close", timeout=8)
                code, _, studio = request("/api/v1/studio", cookie=cookie)
                assert code == 200
                studio["programSceneId"] = "fixture-empty"
                code, _, studio = request("/api/v1/studio", studio, cookie=cookie, method="PUT",
                    revision=studio["revision"])
                assert code == 200
                checkpoint("program-cleared-put")
                wait_for(lambda: state().get("programApplyState") == "idle" and
                    state().get("program", {}).get("mediaSources") == 0,
                    "empty Program scene did not clear the previous protected output", timeout=25)
                checkpoint("program-cleared-applied")
                wait_for(lambda: state().get("audioSources", []) == [],
                    "retired Program Scene retained its native audio mixer process", timeout=10)
                evidence["programAudioReleasedAfterClear"] = True
                check_pixels("program-cleared", quick_order=[1, 2, 3, 4, 5])
                evidence["checks"].extend(["studio-take-applies-real-obs-program-final-pixels",
                    "program-projector-shows-real-program-not-preview",
                    "take-document-revision-and-program-receipt-match",
                    "empty-program-scene-clears-previous-output"])
            phase = "logout"
            assert ui("logout")
            wait_for(lambda: state().get("phase") == "locked", "logout did not lock product UI")
            assert state()["mediaSources"] == 0 and state()["sessionBound"] is False
            assert state().get("audioSources", []) == [], "logout retained native audio mixer processes"
            evidence["logoutRetirementMs"] = state().get("lastRetirementMs")
            assert type(evidence["logoutRetirementMs"]) is int and 0 <= evidence["logoutRetirementMs"] <= 2000, \
                "native logout did not retire the actual media references within two seconds"
            evidence["checks"].append("logout-clears-bound-session")
            if with_media:
                check_pixels("logout", blank=True)
                phase = "scoped-viewer-account-api"
                viewer_credentials = {"username": "native-viewer", "password": secrets.token_urlsafe(24)}
                viewer_scopes = [{"kind": "camera", "id": f"fixture-{index}"} for index in range(1, 6)]
                code, _, viewer = request("/api/v2/users", {**viewer_credentials,
                    "roles": ["viewer"], "scopes": viewer_scopes}, cookie)
                assert code == 201, "ordinary account API could not create a scoped viewer"
                code, _, _ = request("/api/v1/cameras", {"id": "fixture-denied", "name": "Forbidden fixture",
                    "address": rtsp.urls[0], "adapter": "rtsp", "hardwareDecode": "off", "profiles": [{
                        "id": "main", "name": "Main", "role": "main", "endpoint": rtsp.urls[0],
                        "transportMode": "rtsp-tcp", "videoCodec": "h265", "width": 320, "height": 180,
                        "fps": 10, "audioCodec": ""}]}, cookie)
                assert code == 201, "could not create the separate forbidden catalog entry"
                owner_workspace = paths[0]
                owner_bytes = owner_workspace.read_bytes()
                phase = "scoped-viewer-product-ui"
                assert ui("login", **viewer_credentials)
                wait_for(lambda: state().get("phase") == "authenticated" and state().get("catalogItems") == 5,
                    "viewer catalog did not expose exactly the five permitted cameras")
                assert ui("choose", indices=[1, 2, 3, 4, 5])
                check_graph()
                time.sleep(3)
                check_pixels("scoped-viewer")
                assert ui("save")
                viewer_paths = wait_for(lambda: list((profile / "native-profile").rglob(
                    "workspace-" + viewer["id"] + ".json")), "viewer workspace was not bound to its account identity")
                assert len(viewer_paths) == 1 and viewer_paths[0] != owner_workspace
                viewer_workspace, _ = split_workspace(read_json(viewer_paths[0]))
                assert viewer_workspace == saved and owner_workspace.read_bytes() == owner_bytes
                evidence["checks"].extend(["scoped-viewer-catalog-excludes-forbidden-camera",
                    "scoped-viewer-five-hevc-final-pixels", "separate-account-workspace-does-not-overwrite-owner"])
                viewer_reference = {binding["cameraId"]: binding["sourceUuid"] for binding in state()["bindings"]}
                assert ui("projector", slot=1)
                wait_for(lambda: len(state().get("projectors", [])) == 1, "viewer fixed projector did not open")
                assert ui("choose", indices=[1, 1, 1, 1, 1])
                check_graph(repeat_first=True, expected_media=5)
                check_projectors({1: "forward"}, viewer_reference)
                check_pixels("viewer-projector-only-camera", repeat_first=True, expected_media=5,
                    projector_orders={"fixed-scene-1": "forward"})
                viewer_projector_windows = fixed_windows()
                phase = "camera-scope-revocation-api"
                code, _, changed_viewer = request("/api/v2/users/" + viewer["id"],
                    {"scopes": viewer_scopes[:-1]}, cookie, method="PATCH", revision=viewer["revision"])
                assert code == 200, "ordinary user API did not revoke one camera scope"
                wait_for(lambda: state().get("phase") == "locked", "revoked camera scope remained viewable", timeout=8)
                assert state()["sessionBound"] is False and state()["mediaSources"] == 0
                wait_for(lambda: state().get("projectors") == [] and owned_windows_closed(viewer_projector_windows),
                    "revoked camera retained its fixed projector window")
                check_pixels("camera-scope-revoked", blank=True)
                evidence["checks"].extend(["ordinary-camera-scope-change-clears-actual-viewer-preview",
                    "revoked-camera-only-in-fixed-projector-closes-protected-views"])
                code, _, _ = request("/api/v2/users/" + viewer["id"], {"scopes": viewer_scopes}, cookie,
                    method="PATCH", revision=changed_viewer["revision"])
                assert code == 200
                assert ui("login", **viewer_credentials)
                check_graph()
                time.sleep(3)
                check_pixels("viewer-scope-restored")
                assert ui("logout")
                wait_for(lambda: state().get("phase") == "locked", "viewer logout did not release its graph")
                check_pixels("viewer-logout", blank=True)
                assert owner_workspace.read_bytes() == owner_bytes
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
            evidence["normalCloseUi"] = bool(ui("close"))
            assert evidence["normalCloseUi"], "main product window was not closable"
            try:
                exit_code = process.wait(timeout=70)
            except subprocess.TimeoutExpired:
                evidence["normalCloseTimeout"] = True
                raise AssertionError("normal UI close exceeded the shutdown deadline") from None
            evidence["normalCloseExitCode"] = exit_code
            assert exit_code == 0, "normal UI close failed orderly shutdown"
            try:
                wait_for(lambda: not any(owned_alive(pid) for pid in known_pids), "owned process survived normal close")
            except AssertionError:
                evidence["normalCloseAlivePids"] = sum(1 for pid in known_pids if owned_alive(pid))
                raise
            evidence["checks"].append("normal-ui-close-cleans-owned-processes")
            if complete_services:
                phase = "real-plugin-workspace-import"
                # Reuse only this gate's stopped disposable data. The source
                # workspace was created by the actual Qt UI/OBS module path.
                original_profile = profile
                before_workspaces = {p.relative_to(original_profile): p.read_bytes()
                                     for p in (original_profile / "native-profile").rglob("workspace-*.json")}
                assert before_workspaces, "product gate did not create real saved workspaces"
                imported = private / "migrated-native"
                migration = subprocess.run([str(runtime / "python/python.exe"), "-B",
                    str(runtime / "services/product/migrate_legacy.py"),
                    "--source", str(original_profile / "config"),
                    "--destination", str(imported / "config"), "--confirm-stopped",
                    "--include-preview-workspaces"], capture_output=True, text=True, timeout=60)
                assert migration.returncode == 0, "packaged workspace migration failed"
                migration_receipt = json.loads(migration.stdout)
                assert migration_receipt["previewWorkspacesCopied"] == len(before_workspaces)
                for relative, content in before_workspaces.items():
                    assert (original_profile / relative).read_bytes() == content
                    assert (imported / relative).read_bytes() == content
                profile = imported
                status_path = profile / "run/native-status.json"
                environment["WEBOBS_PRODUCT_TEST_ROOT"] = str(profile)
                started = start()
                if with_media:
                    check_pixels("import-before-authentication", blank=True)
                assert ui("login", **account)
                if with_media:
                    check_graph()
                    time.sleep(3)
                    check_pixels("imported-plugin-workspace")
                else:
                    wait_for(lambda: state().get("phase") == "authenticated", "imported account login failed")
                assert ui("close")
                assert process.wait(timeout=70) == 0
                wait_for(lambda: not any(owned_alive(pid) for pid in known_pids), "migration probe retained processes")
                evidence["checks"].extend(["actual-plugin-workspace-import-restores-after-authentication",
                                           "import-preserves-source-account-workspace"])
            phase = "persistent-origin-conflict"
            original_origin = started["origin"]
            network_path = profile / "config/native-network.json"
            saved_network = network_path.read_bytes()
            with socket.socket() as blocker:
                # No Windows SO_REUSEADDR: the gate must not force-bind or
                # steal another listener in order to report a conflict pass.
                blocker.bind(("127.0.0.1", int(original_origin.rsplit(":", 1)[1])))
                blocker.listen(1)
                rejected = subprocess.run([str(entry)], env=environment, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=40)
                assert rejected.returncode == 1, "occupied saved origin was silently replaced"
                assert network_path.read_bytes() == saved_network
                assert status()["phase"] == "stopped" and status()["services"] == []
            phase = "restart-login"
            restarted = start()
            assert restarted["origin"] == original_origin and network_path.read_bytes() == saved_network
            evidence["checks"].append("persistent-control-origin-and-conflict-refusal")
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
            phase = "password-change-api"
            code, issued, _ = request("/api/v1/auth/login", account)
            assert code == 200 and issued
            code, _, changed_password = request("/api/v2/account/password", {
                "currentPassword": account["password"], "newPassword": secrets.token_urlsafe(24)}, issued.split(";", 1)[0])
            assert code == 200 and changed_password.get("changed") is True, "ordinary password change failed"
            phase = "revocation"
            wait_for(lambda: state().get("phase") == "locked", "real account epoch change did not lock product UI", timeout=8)
            assert state()["sessionBound"] is False and state()["mediaSources"] == 0
            if with_media:
                check_pixels("revoked", blank=True)
            evidence["checks"].append("real-authority-revocation-locks-ui")
            evidence["checks"].append("ordinary-password-change-revokes-active-native-session")
            phase = "owner-crash"
            process.kill()
            process.wait(timeout=10)
            wait_for(lambda: not any(owned_alive(pid) for pid in known_pids), "Windows Job left owned services after launcher crash", timeout=15)
            evidence["checks"].append("launcher-crash-job-cleans-all-owned-processes")
            if preview_delivery:
                assert all(marker.read_bytes() == b"synthetic retained older installation data" for marker in legacy_markers)
                evidence["checks"].append("preview-default-data-root-isolated-from-legacy-and-internal")
            evidence.pop("lastUiFailure", None)
            evidence["mediaQualified"] = with_media
            evidence["mediaScope"] = "synthetic-five-hevc-final-preview-pixels" if with_media else "not-run"
            evidence["passed"] = True
        except Exception as error:
            gate_failed[0] = True
            # Synthetic logs stay private. Only fixed marker categories, bounded
            # counts and numeric exit status leave this disposable test profile.
            evidence["failurePhase"] = phase
            detail = f"{type(error).__name__}: {error}"
            for private_value in (str(private), str(runtime), str(profile)):
                detail = detail.replace(private_value, "<private>")
            evidence["failureDetail"] = detail[:300]
            evidence["entryExitCode"] = process.poll() if process is not None else None
            stopped = status()
            if stopped.get("bootId") == active_boot_id or (process is not None and stopped.get("ownerPid") == process.pid):
                reason = stopped.get("failureReason")
                evidence["currentBootFailure"] = reason if reason in {
                    "", "saved-control-port-unavailable", "frontend-exited", "startup-or-service-error"} else "unknown"
                evidence["serviceExits"] = [{"name": service["name"], "running": service.get("running") is True,
                    "exitCode": service.get("exitCode") if type(service.get("exitCode")) is int else None}
                    for service in stopped.get("services", []) if service.get("name") in {
                        "control", "frontend", "accounts-and-registry"}]
            observed = state()
            evidence["observedState"] = {key: observed[key] for key in (
                "phase", "mediaSources", "sessionBound", "catalogItems", "selectionIndices", "previewLocked",
                "lastRetirementMs", "mainGeneration", "studioRevision", "renderer", "program",
                "programSceneId", "programSceneFingerprint", "programApplyState", "programApplyError",
                "programApplyTransient", "programApplyAttempts", "programTargetSceneId",
                "startupStudioDeferred", "lastLock", "lockCode", "renewTransient") if key in observed}
            evidence["observedState"]["watchingSavedScene"] = bool(observed.get("sceneId"))
            evidence["observedState"]["programOutput"] = observed.get("programOutput", {})
            evidence["observedState"]["supportBundle"] = observed.get("supportBundle", {})
            evidence["observedState"]["projectorCount"] = len(observed.get("projectors", []))
            evidence["observedState"]["projectorGeometry"] = [
                {"slot": view.get("slot"), "geometry": view.get("geometry"),
                 "fullscreen": view.get("fullscreen")}
                for view in observed.get("projectors", []) if isinstance(view, dict)]
            preferences = observed.get("projectorPreferences", {})
            evidence["observedState"]["projectorPreferenceRoles"] = (
                sorted(preferences) if isinstance(preferences, dict) else [])
            evidence["observedState"]["windowRoles"] = [window.get("role") for window in observed.get("windows", [])
                                                       if isinstance(window, dict)]
            evidence["observedState"]["audioSources"] = observed.get("audioSources", [])
            # Only fixed categories/counts from this boot's newest OBS log.
            # Never publish its contents, path, exception text or camera URL.
            obs_markers = ("Switched to Preview/Program mode", "Switched to regular Preview mode",
                "Failed to initialize", "Failed to create", "QWidget", "QObject", "QLayout",
                "Shutting down", "All scene data cleared", "Number of remaining allocations")
            obs_logs = [path for path in (profile / "native-profile/obs-studio/logs").glob("*.txt")
                if not path.is_symlink() and path.is_file() and path.stat().st_mtime >= boot_started_at - 2]
            evidence["currentBootObsLogPresent"] = bool(obs_logs)
            if obs_logs:
                newest = max(obs_logs, key=lambda path: path.stat().st_mtime)
                with newest.open("rb") as log:
                    log.seek(max(0, newest.stat().st_size - 2 * 1024 * 1024))
                    tail = log.read(2 * 1024 * 1024).decode("utf-8", errors="replace")
                evidence["currentBootObsMarkers"] = {marker: min(1000, tail.count(marker)) for marker in obs_markers}
                audio_markers = ("MP: Failed to open media", "MP: Failed to find stream info",
                    "MP: Could not initialize audio or video", "Disconnected. Reconnecting",
                    "Reconnected.", "ffmpeg_source", "Error opening input", "frame size not set",
                    "Stream specifier", "matches no streams", "Could not open", "Audio",
                    "Writing file", "Failed to open AAC codec", "Couldn't find encoder",
                    "bad settings specified", "x264 failed to load", "has no media set",
                    "Failed to create process pipe", "Unable to write", "encoder '")
                diagnostic_lines = []
                for line in tail.splitlines():
                    if not any(marker in line for marker in audio_markers):
                        continue
                    clean = re.sub(r"(?:rtsp|rtsps|udp|http|https)://\S+", "<url>", line)
                    for private_value in (str(private), str(runtime), str(profile)):
                        clean = clean.replace(private_value, "<private>")
                    diagnostic_lines.append(clean[:200])
                evidence["obsDiagnosticLines"] = diagnostic_lines[-12:]
            markers = ("ModuleNotFoundError", "ImportError", "PermissionError", "FileNotFoundError",
                       "RuntimeError", "AttributeError", "ValueError", "control exited during startup",
                       "control health deadline exceeded", "a required product service exited", "saved control port is unavailable")
            evidence["privateLogMarkers"] = []
            for log in (profile / "logs").glob("native-*.log"):
                if log.is_file() and not log.is_symlink():
                    with log.open("rb") as source:
                        source.seek(max(0, log.stat().st_size - 131072))
                        tail = source.read(131072).decode("utf-8", errors="replace")
                    evidence["privateLogMarkers"].extend(f"{log.name}:{marker}" for marker in markers if marker in tail)
            evidence["privateLogMarkers"] = sorted(set(evidence["privateLogMarkers"]))
            raise AssertionError("native product entry/UI gate failed at " + phase) from None
        finally:
            cleanup_failed = False
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            try:
                wait_for(lambda: not any(owned_alive(pid) for pid in known_pids),
                         "owned Windows process survived gate cleanup", timeout=15)
            except Exception:
                cleanup_failed = True
                evidence["cleanupFailed"] = True
                for pid in known_pids:
                    if not owned_alive(pid):
                        continue
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    wait_for(lambda: not any(owned_alive(pid) for pid in known_pids),
                             "owned Windows process survived forced cleanup", timeout=10)
                except Exception:
                    evidence["forcedCleanupFailed"] = True
            if rtsp is not None:
                rtsp.stop()
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(evidence))
            if cleanup_failed and not gate_failed[0]:
                raise AssertionError("owned Windows process survived gate cleanup")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--with-media", action="store_true")
    parser.add_argument("--retained-profile", type=Path)
    arguments = parser.parse_args()
    exercise(arguments.runtime.resolve(strict=True), arguments.report.resolve(), with_media=arguments.with_media,
             retained_profile=arguments.retained_profile)
