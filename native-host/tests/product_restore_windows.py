#!/usr/bin/env python3
"""Actual frontend restore I/O control and protected product startup on Windows.

Only an agent-owned synthetic RTSP endpoint is involved. An unguarded frontend
must attempt that endpoint from a saved collection; the identical collection in
the product must reach the pre-load refusal and perform zero media requests.
No real camera, hardware decode, full native-menu or migration claim is made.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
from ctypes import wintypes
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from product_windows import read_json, wait_for
from smoke_windows import fingerprint
from product_restore_protocol import inspect_request

COLLECTION = "WebOBS restore isolation fixture"
FILENAME = "webobs-restore-isolation"


def load(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def collection(endpoint):
    source_uuid, scene_uuid = str(uuid.uuid4()), str(uuid.uuid4())
    return json.dumps({"version": 1, "name": COLLECTION, "current_scene": "Synthetic scene",
        "current_program_scene": "Synthetic scene", "current_transition": "Fade", "transition_duration": 300,
        "scene_order": [{"name": "Synthetic scene"}], "sources": [
            {"id": "ffmpeg_source", "versioned_id": "ffmpeg_source", "name": "Synthetic protected source",
             "uuid": source_uuid, "enabled": True, "settings": {"is_local_file": False, "input": endpoint,
                 "hw_decode": False, "close_when_inactive": False, "restart_on_activate": True,
                 "ffmpeg_options": "rtsp_transport=tcp", "reconnect_delay_sec": 1}},
            {"id": "scene", "versioned_id": "scene", "name": "Synthetic scene", "uuid": scene_uuid,
             "settings": {"items": [{"name": "Synthetic protected source", "source_uuid": source_uuid,
                 "visible": True, "locked": True, "pos": {"x": 0.0, "y": 0.0},
                 "scale": {"x": 1.0, "y": 1.0}, "rot": 0.0, "align": 5,
                 "bounds_type": 0, "bounds_align": 0, "bounds": {"x": 0.0, "y": 0.0}}]}}]},
        separators=(",", ":")).encode("utf-8")


def seed(config, encoded):
    scenes = config / "obs-studio/basic/scenes"
    scenes.mkdir(parents=True)
    path = scenes / (FILENAME + ".json")
    path.write_bytes(encoded)
    (config / "obs-studio/user.ini").write_text(
        "[General]\nFirstRun=true\n[Basic]\nConfigOnNewProfile=false\n"
        f"SceneCollection={COLLECTION}\nSceneCollectionFile={FILENAME}\n"
        "[BasicWindow]\nSysTrayEnabled=false\nSceneDuplicationMode=true\nPreviewProgramMode=false\n",
        encoding="utf-8")
    return path


def close_windows(pid, expected_window=None):
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.PostMessageW.restype = wintypes.BOOL
    user.EnumWindows.argtypes = [callback, wintypes.LPARAM]
    user.EnumWindows.restype = wintypes.BOOL
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetClassNameW.restype = ctypes.c_int
    user.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetWindow.restype = wintypes.HWND
    posted = 0

    def close(window, _):
        nonlocal posted
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == pid:
            name = ctypes.create_unicode_buffer(256)
            user.GetClassNameW(window, name, len(name))
            # Media restore can start before the main native HWND exists. Qt's
            # earlier clipboard/theme/tool windows are not a closable frontend.
            if ((expected_window is not None and window == expected_window) or
                    (expected_window is None and re.fullmatch(r"Qt[0-9]+QWindowIcon", name.value) and
                     user.GetWindowLongPtrW(window, -16) & 0x00C00000 and not user.GetWindow(window, 4))):
                if user.PostMessageW(window, 0x0010, 0, 0):
                    posted += 1
        return True

    if not user.EnumWindows(callback(close), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return posted


def exercise(runtime, control_frontend, report):
    if os.name != "nt":
        raise ValueError("actual frontend restore isolation requires Windows x64")
    process_api = load("restore_test_windows_process_api", ROOT / "native-host/qualification/win32.py")
    supervisor = load("restore_test_supervisor", ROOT / "native-host/scripts/product_supervisor.py")
    package = load("restore_test_package_verifier", ROOT / "native-host/scripts/product_package.py")
    payload = package.verify(runtime)
    if control_frontend.is_symlink() or not control_frontend.is_file():
        raise ValueError("a separate compiled frontend control is required")
    private_directory = load("restore_test_private_directory", ROOT / "desktop/python/private_directory.py")
    external = Path(os.environ["APPDATA"]) / "obs-studio"
    external_before = fingerprint(external)
    result = {"schema": 1, "kind": "native-product-restore-isolation", "sourceRevision": payload["sourceRevision"],
        "passed": False, "publicationForbidden": True, "fullFeatureMigrationQualified": False,
        "nativeMenuBypassesQualified": False, "checks": []}
    phase = "prepare"
    with tempfile.TemporaryDirectory(prefix="WebOBS 恢复拦截-") as temporary, contextlib.ExitStack() as cleanup:
        private = Path(temporary)
        private_directory.protect(private)
        processes, identities = [], []
        token = ("restore-" + secrets.token_hex(16)).encode("ascii")
        request_count = 0
        probe_counts = {"tcpConnections": 0, "completeHeaders": 0, "options": 0,
                        "describe": 0, "matchingRequests": 0}
        requests_lock = threading.Lock()

        class Probe(socketserver.ThreadingTCPServer):
            daemon_threads = True
            block_on_close = True

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                nonlocal request_count
                observed = inspect_request(self.request, token)
                with requests_lock:
                    request_count += observed["matchingRequests"]
                    for key in probe_counts:
                        probe_counts[key] += observed[key]

        server = Probe(("127.0.0.1", 0), Handler)
        cleanup.callback(server.server_close)
        cleanup.callback(server.shutdown)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        encoded = collection(f"rtsp://127.0.0.1:{server.server_address[1]}/" + token.decode("ascii"))
        control = private / "control"
        for path in ("bin/64bit", "obs-plugins", "data"):
            shutil.copytree(runtime / path, control / path)
        shutil.copy2(control_frontend, control / "bin/64bit/obs64.exe")
        (control / "portable_mode.txt").write_bytes(b"")
        control_collection = seed(control / "config", encoded)
        profile = private / "protected-profile"
        protected_collection = seed(profile / "native-profile", encoded)
        assert control_collection.read_bytes() == protected_collection.read_bytes() == encoded
        result["fixtureSha256"] = hashlib.sha256(encoded).hexdigest()
        environment = supervisor.clean_environment(os.environ)
        environment["PATH"] = str(control / "bin/64bit") + ";" + str(Path(os.environ["SystemRoot"]) / "System32")
        job_host = runtime / "bin/webobs-job.exe"
        current = None

        def remember(pid, parent=0, name="owned", parent_identity=None):
            identity = process_api.Process(pid, parent, name, parent_identity)
            identities.append(identity)
            return identity

        def exited(identity):
            return process_api.WaitForSingleObject(identity.handle, 0) == 0

        try:
            phase = "unguarded-launch"
            with (private / "private-control.log").open("wb") as log:
                current = subprocess.Popen([str(job_host), "--stdio", str(control / "bin/64bit/obs64.exe"),
                    "--portable", "--disable-updater", "--only-bundled-plugins"],
                    cwd=control / "bin/64bit", env=environment, stdin=subprocess.PIPE,
                    stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
                processes.append(current)
                owner = remember(current.pid)

                def control_child():
                    assert current.poll() is None, "unguarded frontend owner exited before restore"
                    children = [row for row in process_api.snapshot() if row["parentPid"] == current.pid and
                                row["exeName"].lower() == "obs64.exe"]
                    if len(children) != 1:
                        return None
                    child = remember(children[0]["pid"], current.pid, "obs64.exe", owner.identity)
                    assert child.created >= owner.created and Path(child.image()).resolve() == (control / "bin/64bit/obs64.exe").resolve()
                    return child

                phase = "unguarded-child-identity"
                frontend = wait_for(control_child, "unguarded frontend was not launched inside the owned Job")
                result["checks"].append("exact-unguarded-frontend-owned-by-job")

                def restored_io():
                    assert current.poll() is None, "unguarded frontend exited without media restore I/O"
                    with requests_lock:
                        return request_count > 0

                phase = "unguarded-restore-rtsp"
                wait_for(restored_io, "saved collection positive control did not perform RTSP media I/O", timeout=30)
                result["checks"].append("unguarded-saved-collection-rtsp-request-observed")
                phase = "unguarded-normal-close"
                result["controlCloseWindows"] = wait_for(lambda: close_windows(frontend.pid),
                    "unguarded main Qt window never became available for normal close", timeout=10)
                assert current.wait(timeout=30) == 0, "unguarded frontend did not close normally"
                wait_for(lambda: exited(frontend), "owned control frontend survived normal close")
            result["checks"].append("same-saved-collection-performs-rtsp-io-without-product-guard")
            # Drain any request already queued by the now-exited control. The
            # protected phase must not misattribute a late handler to the product.
            phase = "control-io-quiescence"
            stable_since, previous = time.monotonic(), -1
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with requests_lock:
                    baseline = request_count
                if baseline != previous:
                    previous, stable_since = baseline, time.monotonic()
                if time.monotonic() - stable_since >= 1.2:
                    break
                time.sleep(.05)
            else:
                raise AssertionError("owned control media I/O did not quiesce")
            result["unguardedRtspRequests"] = baseline
            phase = "protected-preauthentication-restore"
            product_environment = dict(os.environ, WEBOBS_PRODUCT_TEST_ROOT=str(profile))
            current = subprocess.Popen([str(runtime / "bin/webobs-wall.exe")], env=product_environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(current)
            remember(current.pid)
            status_path = profile / "run/native-status.json"

            def running():
                assert current.poll() is None, "protected product exited before startup"
                if not status_path.is_file():
                    return None
                value = read_json(status_path)
                return value if value.get("phase") == "running" else None

            status = wait_for(running, "protected product did not start required services", timeout=45)
            for pid in {status["ownerPid"], *(service["pid"] for service in status["services"])}:
                remember(pid)
            frontend_pid = next(service["pid"] for service in status["services"] if service["name"] == "frontend")

            def locked():
                paths = list((profile / "native-profile").rglob("product-state.json"))
                if len(paths) != 1:
                    return None
                state = read_json(paths[0])
                return state if state.get("pid") == str(frontend_pid) and state.get("phase") == "locked" else None

            observation = wait_for(locked, "protected product did not reach locked native UI")
            assert observation.get("restoreGuardHits", 0) >= 1 and observation.get("refusedCollection") == COLLECTION, \
                "the actual pre-load guard did not observe the injected collection"
            assert observation["mediaSources"] == 0 and observation["sessionBound"] is False
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                assert current.poll() is None and locked(), "protected startup state changed before login"
                with requests_lock:
                    assert request_count == baseline, "protected collection attempted media I/O before authentication"
                time.sleep(.1)
            assert protected_collection.read_bytes() == encoded, "product changed the refused saved collection"
            result["checks"].extend(["actual-selected-collection-refused-before-load", "zero-preauthentication-rtsp-requests",
                "locked-ui-zero-media-and-no-session", "refused-collection-preserved"])
            phase = "normal-shutdown"
            main_window = int(observation["windows"][0]["rootHwnd"], 16)
            result["productCloseWindows"] = wait_for(lambda: close_windows(frontend_pid, main_window),
                "protected main Qt window never became available for normal close", timeout=10)
            assert current.wait(timeout=40) == 0
            wait_for(lambda: all(exited(identity) for identity in identities), "owned restore processes survived shutdown")
            assert fingerprint(external) == external_before, "external OBS profile changed during isolated restore test"
            result["checks"].extend(["normal-product-shutdown", "external-obs-profile-unchanged"])
            result["passed"] = True
        except Exception as error:
            result["failurePhase"] = phase
            result["exceptionType"] = type(error).__name__
            result["ownedEntryExitCode"] = current.poll() if current is not None else None
            with requests_lock:
                result["probeCounts"] = dict(probe_counts)
            markers = ("Portable mode: true", "Third-party plugins disabled.", "Loaded scenes:",
                       "No scene file found, creating default scene", "Synthetic protected source",
                       "Failed to load module", "Failed to initialize video", "Failed to create source")
            result["privateControlLogMarkers"] = []
            logs = [private / "private-control.log", *sorted((control / "config/obs-studio/logs").glob("*.txt"))[-3:]]
            for log in logs:
                if log.is_file() and not log.is_symlink():
                    with log.open("rb") as source:
                        source.seek(max(0, log.stat().st_size - 262144))
                        tail = source.read(262144).decode("utf-8", errors="replace")
                    result["privateControlLogMarkers"].extend(marker for marker in markers if marker in tail)
            result["privateControlLogMarkers"] = sorted(set(result["privateControlLogMarkers"]))
            raise AssertionError("actual product restore isolation failed at " + phase) from None
        finally:
            cleanup_failed = False
            try:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=10)
                    if process.stdin is not None:
                        process.stdin.close()
                wait_for(lambda: all(exited(identity) for identity in identities), "restore test Job cleanup did not finish")
            except Exception:
                cleanup_failed = True
                result["passed"] = False
                result["cleanupFailed"] = True
            finally:
                for identity in identities:
                    identity.close()
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                print(json.dumps(result))
            if cleanup_failed:
                raise AssertionError("owned restore Job cleanup failed") from None
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--control-frontend", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    exercise(args.runtime.resolve(strict=True), args.control_frontend.resolve(strict=True), args.report.resolve())
