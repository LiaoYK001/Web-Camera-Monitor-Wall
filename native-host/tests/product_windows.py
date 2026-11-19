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
import hashlib
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
import threading
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


# product_output.cpp sets keyint_sec 2 on both Program outputs, so a consumer that
# joins after publishing starts lands inside the encoder's current GOP and cannot
# decode until the next IDR arrives.
PROGRAM_ENCODER_KEYINT_SECONDS = 2
PROGRAM_VIDEO_WINDOW_SECONDS = PROGRAM_ENCODER_KEYINT_SECONDS * 3


def published_video_window(ffprobe, url, window_seconds):
    """Read decodable video from one RTSP connection across a wall-clock window.

    Reading a fixed packet count is not evidence about the published picture: a
    late consumer's first packets are P-slices with no reference picture, so a
    20-packet read decoded zero frames twice (runs 44524750280 and 44534272424)
    with return code 0 and "co located POCs unavailable"/"mmco: unref short
    failure" while OBS advanced its own render counter and the relay reported a
    connected stream. The window is therefore measured in seconds across at least
    two keyframe intervals, and ffprobe's string pts_time is parsed rather than
    dropped (the numeric-only check used to record a span of 0 for any stream).
    """
    stamps, unparsed, first_frame_ms = [], [], [-1]
    reader_finished = threading.Event()
    stderr_tail = [""]
    started = time.monotonic()
    probe = subprocess.Popen([str(ffprobe), "-v", "error", "-rtsp_transport", "tcp",
        "-select_streams", "v:0", "-show_entries", "frame=pts_time", "-of", "csv=p=0", url],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace")

    def read_frames():
        try:
            for line in iter(probe.stdout.readline, ""):
                value = line.strip()
                if not value:
                    continue
                try:
                    stamp = float(value)
                except ValueError:
                    unparsed.append(value[:24])
                    continue
                if first_frame_ms[0] < 0:
                    first_frame_ms[0] = int((time.monotonic() - started) * 1000)
                stamps.append(stamp)
        finally:
            reader_finished.set()

    def drain_stderr():
        # Decoder warnings repeat per frame, so a full stderr pipe would block the
        # child and turn a healthy stream into a timed-out window.
        try:
            stderr_tail[0] = (probe.stderr.read() or "")[-260:]
        except (OSError, ValueError):
            pass

    readers = [threading.Thread(target=read_frames, daemon=True),
        threading.Thread(target=drain_stderr, daemon=True)]
    for reader in readers:
        reader.start()
    while time.monotonic() < started + window_seconds and not reader_finished.is_set():
        time.sleep(0.1)
    window_timed_out = not reader_finished.is_set()
    if window_timed_out:
        probe.kill()
    try:
        probe.wait(timeout=15)
    except subprocess.TimeoutExpired:
        probe.kill()
    readers[1].join(timeout=5)
    for pipe in (probe.stdout, probe.stderr):
        if pipe is not None:
            pipe.close()
    span = (max(stamps) - min(stamps)) if len(stamps) > 1 else 0.0
    return {"windowSeconds": window_seconds,
        "firstDecodableFrameMs": first_frame_ms[0],
        "windowTimedOut": window_timed_out,
        "elapsedMs": int((time.monotonic() - started) * 1000),
        "returnCode": int(probe.returncode or 0),
        "stderrTail": stderr_tail[0],
        "unparsableStamps": unparsed[:4],
        "frames": len(stamps),
        "stamps": stamps,
        "ptsSpanSeconds": round(float(span), 3),
        "measuredFramesPerSecond": round(len(stamps) / span, 2) if span > 0 else 0,
        "monotonicTimestamps": all(later > earlier for earlier, later in zip(stamps, stamps[1:]))}


def published_packet_window(ffprobe, url, window_seconds):
    """Ask the relay, on a second connection, whether a late client gets an IDR.

    Zero key packets across the window points at the published stream; key packets
    that still decode nothing points at the parameter sets reaching the decoder. Run
    44544305133 lost the primary frame measurement because this diagnostic raised
    "unsupported format character" from its own %%-style interval, so the interval is
    concatenated and every failure here is reported as a diagnostic instead of
    replacing the decodable-frame assertion.
    """
    read_interval = "%+00:00:" + str(window_seconds)
    summary = {"readInterval": read_interval, "packets": 0, "keyframes": 0,
        "firstPacketIsKey": False, "firstKeyPacketPts": -1, "keyPacketGapsSeconds": [],
        "returnCode": -1, "stderrTail": ""}
    try:
        probe = subprocess.run([str(ffprobe), "-v", "error", "-rtsp_transport", "tcp",
            "-select_streams", "v:0", "-read_intervals", read_interval,
            "-show_entries", "packet=pts_time,flags", "-of", "json", url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=window_seconds + 25)
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        summary["diagnosticFailed"] = f"{type(error).__name__}: {error}"[:200]
        return summary
    entries = []
    try:
        entries = json.loads(probe.stdout or "{}").get("packets", []) or [] if probe.returncode == 0 else []
    except ValueError as error:
        summary["diagnosticFailed"] = f"invalid packet probe JSON: {type(error).__name__}"
    key_stamps = []
    for entry in entries:
        if "K" not in str(entry.get("flags") or ""):
            continue
        try:
            key_stamps.append(float(entry.get("pts_time")))
        except (TypeError, ValueError):
            pass
    summary.update({"returnCode": int(probe.returncode), "packets": len(entries),
        "keyframes": len(key_stamps),
        "firstPacketIsKey": bool(entries and "K" in str(entries[0].get("flags") or "")),
        "firstKeyPacketPts": key_stamps[0] if key_stamps else -1,
        "keyPacketGapsSeconds": [round(b - a, 3) for a, b in zip(key_stamps, key_stamps[1:])][:6],
        "stderrTail": (probe.stderr or "")[-200:]})
    return summary


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


LOOPBACK_MIX_PORT = re.compile(r"tcp://(?:127\.0\.0\.1|localhost):(\d+)[^\s]*")


def sanitize_helper_command(command):
    """Mask a helper command line so a receipt can name it without exposing the run.

    Camera URLs and any remote endpoint become `<url>`. The loopback mix port stays as
    `tcp:<port>`: it is ephemeral, carries no credential, and is the only key that ties
    an owned FFmpeg mixer process to the mix source it serves. Run 44548882087 lost one
    of two helpers and a bare PID diff could not say which mix lost its feeder.
    """
    clean = LOOPBACK_MIX_PORT.sub(lambda match: "tcp:" + match.group(1), command)
    return re.sub(r"(?:rtsp|rtsps|udp|tcp|http|https)://\S+", "<url>", clean)


def helper_port(identity):
    """The loopback mix port carried by a masked helper command line, or None.

    `identity` has to be the complete masked command line, not the capped identity a
    receipt records: a real mix helper is roughly 450 characters and its output target
    sits near the end, so parsing the display-truncated string reported every mixer as
    having no port.
    """
    match = re.search(r"tcp:(\d+)", identity or "")
    return int(match.group(1)) if match else None


def watched_ports(row):
    """Every loopback mix port a live helper owns, duplicates kept."""
    assert isinstance(row, dict), \
        "mix port comparison needs a recorded watch row, not a helper PID list"
    return sorted(item["port"] for item in row["processes"] if item["port"])


def claimed_ports(row):
    """The mix port each owned mix source says it is reading."""
    assert isinstance(row, dict), \
        "mix port comparison needs a recorded watch row, not a helper PID list"
    return sorted({int(entry["mixerPort"]) for entry in row["hostClaims"]
        if isinstance(entry.get("mixerPort"), (int, float)) and int(entry["mixerPort"]) > 0})


MIXER_IDENTITY_UNAVAILABLE = {"identity": "command-line-unavailable", "tail": "", "port": None}


def mixer_identities(powershell, pids, private_values=()):
    """Name each owned FFmpeg helper by its own command line, masked and capped.

    A bare PID diff cannot say which helper a phase destroyed: run 44548882087 lost
    one of two FFmpeg mixers while the host still reported the mix as available with
    two mixers and no recorded exit code. The command line is the only side-neutral
    identity available here, so camera URLs and this run's private roots are replaced
    before anything is recorded, while each helper's own loopback mix port is kept so
    the row can be tied back to the mix source that owns it. The recorded identity is
    capped for the receipt, so the port is read from the masked line before the cap:
    the real `-f mpegts tcp://127.0.0.1:<port>?listen=1` target sits past character
    450 of a ~509-character command line and a capped string alone would report no
    mixer as owned. The tail keeps that output target visible in the receipt.
    """
    if not pids:
        return {}
    wanted = " or ".join(f"ProcessId={int(pid)}" for pid in sorted(set(pids)))
    unknown = {int(pid): dict(MIXER_IDENTITY_UNAVAILABLE) for pid in set(pids)}
    try:
        listing = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
            f"Get-CimInstance Win32_Process -Filter '{wanted}' | "
            'ForEach-Object { "$($_.ProcessId)|$($_.CommandLine)" }'],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        # Naming a helper is a diagnostic; it never replaces the ownership assertion.
        return unknown
    identities = {}
    if listing.returncode != 0:
        return unknown
    for line in listing.stdout.splitlines():
        pid_text, _, command = line.partition("|")
        if not pid_text.strip().isdigit():
            continue
        clean = sanitize_helper_command(command)
        for private_value in private_values:
            clean = clean.replace(str(private_value), "<private>")
        clean = clean.strip()
        identities[int(pid_text.strip())] = {"identity": clean[:160], "tail": clean[-80:],
            "port": helper_port(clean)}
    return identities


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
            # Test-only render probe: the host draws the preview Scene and the Program
            # channel into bounded offscreen textures and publishes per-cell content
            # digests. A frozen tile then has a named cause - the feed repeated a frame,
            # the Scene render stopped changing, or only the captured window went stale.
            environment["WEBOBS_PRODUCT_RENDER_PROBE"] = "1"
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

        def render_probe_control_file():
            """The host's render-probe window file, beside its own state observation.

            The frontend reads it only while WEBOBS_PRODUCT_RENDER_PROBE=1, and it draws
            nothing unless a window is open, so the probe cannot slow the encoder or keep
            a media source showing outside the window the harness asked for.
            """
            paths = list((profile / "native-profile").rglob("product-state.json"))
            return paths[0].parent / "product-render-probe.control" if len(paths) == 1 else None

        def render_probe_write(requested):
            control = render_probe_control_file()
            if control is None:
                return False
            tmp = control.with_name(control.name + ".tmp")
            try:
                tmp.write_text(json.dumps(requested), encoding="utf-8")
                os.replace(tmp, control)
            except OSError:
                return False
            return True

        def render_probe_window(seconds):
            return render_probe_write({"schema": 1, "scope": "synthetic-test-only",
                "untilMs": int(time.time() * 1000 + seconds * 1000)})

        def render_probe_close():
            return render_probe_write({"schema": 1, "scope": "synthetic-test-only", "untilMs": 0})

        def render_probe_summary(snapshot):
            """Compact host-side probe health for a non-pixel failure receipt.

            Full timelines stay in the capture windows; this only says whether the probe
            was allowed to draw and whether the Scene/Program render content changed.
            """
            probe = snapshot.get("renderProbe")
            if not isinstance(probe, dict):
                return {"available": False}
            def channel(items):
                items = items if isinstance(items, list) else []
                rows = [item.get("cells") for item in items if isinstance(item, dict)
                        and isinstance(item.get("cells"), list)]
                return {"samples": len(items),
                    "distinctCellsPerTile": [len({row[index] for row in rows if index < len(row)})
                                             for index in range(6)] if rows else []}
            return {"enabled": probe.get("enabled") is True,
                "windowOpen": probe.get("windowOpen") is True,
                "windowUntilMs": probe.get("windowUntilMs"),
                "preview": channel(probe.get("preview")), "program": channel(probe.get("program"))}

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
            return {"publishers": publishers, "readable": readable, "pathProgress": rtsp.path_progress()}

        class SerialWatch:
            """Sample the host's per-input frame counters inside the capture window.

            The frozen-slot receipts only had counters read before the capture and after
            the analysis, so a plateau that happened *between* them was invisible and a
            frozen tile had no cause. Polling the product's own snapshot during the
            capture separates "this media input stopped feeding frames" (a serial plateau
            inside the window) from "frames kept arriving but the item did not repaint"
            (no plateau while the pixel digests stay identical).
            """

            def __init__(self):
                self.samples = []
                # Every distinct publishedAtMs this poll actually observed: the product
                # publishes on its own heartbeat, and a reader must not mistake a publish
                # gap for an input that stopped delivering frames.
                self.publishes = []
                # Render-probe samples keyed by host wall-clock millisecond, deduplicated
                # across the repeated publishes of the same ring.
                self.render_probe = {"preview": {}, "program": {}}
                self.stop = threading.Event()
                self.started = time.monotonic()
                self.thread = threading.Thread(target=self.poll, daemon=True)

            def start(self):
                self.thread.start()

            def poll(self):
                while not self.stop.is_set():
                    snapshot = state()
                    entries = snapshot.get("videoInputs", [])
                    if isinstance(entries, list) and entries:
                        self.samples.append((int((time.monotonic() - self.started) * 1000),
                            {str(entry.get("uuid") or "")[:8]: entry.get("serial")
                             for entry in entries if isinstance(entry, dict)},
                            snapshot.get("renderFrames"),
                            [entry for entry in entries if isinstance(entry, dict)
                             and type(entry.get("serial")) is int and int(entry["serial"]) > 0]))
                        published = snapshot.get("publishedAtMs")
                        if type(published) is int and (not self.publishes or published != self.publishes[-1]):
                            self.publishes.append(published)
                        probe = snapshot.get("renderProbe")
                        if isinstance(probe, dict) and probe.get("enabled") is True:
                            for channel in ("preview", "program"):
                                for item in probe.get(channel) or []:
                                    if isinstance(item, dict) and type(item.get("atMs")) is int:
                                        self.render_probe[channel][int(item["atMs"])] = item
                    self.stop.wait(0.2)

            def report(self):
                self.stop.set()
                self.thread.join(timeout=3)
                tracked = {}
                render_stall_ms, render_from, render_before, render_after, unhealthy = 0, None, None, None, 0
                for elapsed_ms, serials, frames, live in self.samples:
                    if any(entry.get("showing") is not True or entry.get("mediaState") != 1 for entry in live):
                        unhealthy += 1
                    if type(frames) is int:
                        if render_before is None:
                            render_before, render_from = frames, elapsed_ms
                        if frames != render_after and render_from is not None:
                            stalled = elapsed_ms - render_from
                            if stalled > render_stall_ms:
                                render_stall_ms = stalled
                            render_from = elapsed_ms
                        render_after = frames
                    for uuid, serial in serials.items():
                        entry = tracked.setdefault(uuid, {"before": serial, "after": serial,
                            "maxStallMs": 0, "stallFromMs": None, "stallToMs": None})
                        if type(serial) is not int or type(entry["before"]) is not int:
                            continue
                        if serial != entry["after"] or entry["stallFromMs"] is None:
                            if entry["stallFromMs"] is not None:
                                stalled = elapsed_ms - entry["stallFromMs"]
                                if stalled > entry["maxStallMs"]:
                                    entry["maxStallMs"] = stalled
                                    entry["stallToMs"] = elapsed_ms
                            entry["stallFromMs"] = elapsed_ms
                        entry["after"] = serial
                window_ms = self.samples[-1][0] if self.samples else 0
                # Publish cadence inside the window. A plateau shorter than the publish
                # interval cannot be distinguished here, so the receipt states the
                # interval instead of implying a per-source stall.
                publish_gaps = [b - a for a, b in zip(self.publishes, self.publishes[1:])]
                inputs = []
                for uuid in sorted(tracked)[:16]:
                    entry = tracked[uuid]
                    if entry["stallFromMs"] is not None:
                        stalled = window_ms - entry["stallFromMs"]
                        if stalled > entry["maxStallMs"]:
                            entry["maxStallMs"] = stalled
                            entry["stallToMs"] = window_ms
                    # Distinct delivered-frame identities for this input inside the window.
                    # A counter can advance while the content is the same frame; only the
                    # digest separates "the feed repeats" from "the feed changes".
                    feed_hashes, feed_timestamps, frame_ages = set(), set(), []
                    for _, _, _, live in self.samples:
                        for live_entry in live:
                            if str(live_entry.get("uuid") or "")[:8] != uuid:
                                continue
                            if type(live_entry.get("frameHash")) is int and live_entry["frameHash"] >= 0:
                                feed_hashes.add(live_entry["frameHash"])
                            if type(live_entry.get("frameTs")) is int and live_entry["frameTs"] >= 0:
                                feed_timestamps.add(live_entry["frameTs"])
                            if type(live_entry.get("frameAgeMs")) is int and live_entry["frameAgeMs"] >= 0:
                                frame_ages.append(live_entry["frameAgeMs"])
                    inputs.append({"uuid": uuid, "before": entry["before"], "after": entry["after"],
                        "advanced": type(entry["before"]) is int and type(entry["after"]) is int
                                    and entry["after"] > entry["before"],
                        "maxStallMs": entry["maxStallMs"],
                        # The plateau's window, in milliseconds from window start; the
                        # two numbers are positions, not a duration.
                        "stallWindowMs": [entry["stallFromMs"], entry["stallToMs"]]
                                         if entry["maxStallMs"] >= 900 else [],
                        "distinctFeedHashes": len(feed_hashes),
                        "distinctFeedTimestamps": len(feed_timestamps),
                        "feedIdentityObserved": bool(feed_hashes or feed_timestamps),
                        "maxFrameAgeMs": max(frame_ages) if frame_ages else -1})
                rendered = 0 if render_before is None or render_after is None else max(
                    0, render_after - render_before)
                report = {"samples": len(self.samples), "windowMs": window_ms,
                    "publishes": len(self.publishes),
                    "publishIntervalMs": (max(publish_gaps) if publish_gaps else 0),
                    "renderFramesBefore": render_before, "renderFramesAfter": render_after,
                    "renderFramesPerSecond": (round(rendered * 1000 / window_ms, 1) if window_ms else 0),
                    "renderFramesMaxStallMs": render_stall_ms,
                    # Any sample where an owned media input was not showing or not in
                    # OBS's PLAYING state: a reopen/reconnect shows up here directly.
                    "inputNotPlayingSamples": unhealthy,
                    "inputs": inputs}
                # The render probe runs on the host wall clock. Align it to this window by
                # the last publish we saw, so the scene-render timeline covers exactly the
                # frames the capture process read.
                if self.render_probe["preview"] or self.render_probe["program"]:
                    end = self.publishes[-1] if self.publishes else 0
                    start = end - window_ms
                    def probe_report(channel):
                        series = sorted((ms, item) for ms, item in self.render_probe[channel].items()
                            if start <= ms <= end)
                        tiles = [len({item["cells"][index] for _, item in series
                                     if index < len(item.get("cells") or [])}) for index in range(6)]
                        return {"samples": len(series), "distinctCellsPerTile": tiles,
                            "scenes": sorted({str(item.get("scene") or "")[:32] for _, item in series})[:4],
                            "timeline": [{"atMs": ms - end, "renderFrames": item.get("renderFrames"),
                                "cells": item.get("cells")} for _, item in series[-24:]]}
                    report["renderProbe"] = {"preview": probe_report("preview"),
                        "program": probe_report("program")}
                return report

        def check_pixels(label, *, blank=False, repeat_first=False, reverse=False, expected_media=None,
                projector_orders=None, quick_order=None, program_scene=None, program_media=None,
                fixture_retry=True):
            def counted(snapshot):
                return {str(entry.get("uuid") or ""): int(entry["serial"])
                    for entry in snapshot.get("videoInputs", []) if isinstance(entry, dict)
                    and type(entry.get("serial")) is int and 0 < int(entry["serial"]) < 10 ** 15}

            def fixture_recovered(restarted):
                """Harness-side proof that the synthetic feed pushes and decodes again.

                A loopback publisher is harness state, not product state: ffmpeg can exit or
                stall while looping a synthetic file, and then every reader of that path goes
                silent through no fault of the product. The existing `video-progress` UI
                assertion asks the health label for an exact wall-only count (1..5 with
                "已收帧" equal to it), so it cannot prove recovery in a Program phase: that
                Scene adds one dedicated audio-silent variant and the label then reports six
                inputs, which made the repair path throw in run 44349201714 whether or not
                the restart worked. Recovered is the same evidence the pixel gate uses below:
                every published path pushes packets again and every counted frame counter
                advanced inside one measured 2.5 s window.
                """
                if any(publisher is None or publisher.poll() is not None
                       for publisher in rtsp.publishers):
                    return False
                if not all(entry.get("flowing") is True for entry in rtsp.path_progress()):
                    return False
                before = counted(state())
                time.sleep(2.5)
                after = counted(state())
                advanced = [uuid for uuid in before
                            if uuid in after and after[uuid] > before[uuid]]
                evidence.setdefault("fixturePublisherWatch", []).append({
                    "phase": label, "restarted": list(restarted), "countedInputs": len(after),
                    "advancedInputs": len(advanced)})
                # A locked/blank phase owns no inputs at all, so there the packet flow above
                # is the whole proof; otherwise the five wall inputs must decode again.
                needed = 0 if blank else 5
                return len(before) >= needed and len(advanced) >= needed

            # Restart dead publishers before capturing and record it.
            dead = [index for index, publisher in enumerate(rtsp.publishers)
                if publisher is None or publisher.poll() is not None]
            if dead and not blank:
                evidence.setdefault("fixturePublisherWatch", []).append({"phase": label, "dead": dead})
                for index in dead:
                    rtsp.restart_publisher(index)
                wait_for(lambda: fixture_recovered(dead),
                    "restarted loopback publisher did not resume frame progress", timeout=90)
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
            if program_scene is not None:
                # A Program apply re-creates the wall Scene and its owned items, so a
                # capture window that starts mid-swap sees a tile whose last frame is
                # simply old. rc.47 (run 44332749108), rc.48 (run 44332713711) and rc.50
                # (run 44339344891) proved the counter-only form of this wait cannot
                # decide anything: the host refreshes its per-input health only every two
                # seconds, so `stalledMs` is quantized to that tick, and a source that OBS
                # reports as PLAYING but that has not delivered a single video callback yet
                # keeps `serial` at 0 for longer than any wait. Neither is a frozen tile.
                # Measure real progress instead: two snapshots at least 2.5 s apart must
                # show a newer frame counter for every bound wall input and for every input
                # OBS reports as showing, active and PLAYING *that has already counted
                # frames*. Inputs that are still opening, or that report PLAYING without
                # ever delivering a frame, are named in the receipt instead of being
                # awaited; a tile that really never repaints still fails the pixel
                # assertion below with the in-window serial evidence attached.
                def video_entries(snapshot):
                    return [entry for entry in snapshot.get("videoInputs", []) if isinstance(entry, dict)]

                def counted_serials(snapshot):
                    # An audio-only mix source has no video callback and a source whose
                    # media has not produced a frame yet has never been incremented, so
                    # only a counter that has actually counted can be asked to advance.
                    return {str(entry.get("uuid") or ""): int(entry["serial"])
                        for entry in video_entries(snapshot)
                        if type(entry.get("serial")) is int and 0 < int(entry["serial"]) < 10 ** 15}

                def rendered_input_ids(snapshot):
                    # The captured windows are the wall preview and the Program projector,
                    # so the inputs that have to move are the wall's own bound sources plus
                    # whatever OBS reports as actively showing and PLAYING.
                    bound = {str(binding.get("sourceUuid") or "")[:8]
                        for binding in snapshot.get("bindings", []) if isinstance(binding, dict)}
                    playing = {str(entry.get("uuid") or "") for entry in video_entries(snapshot)
                        if entry.get("showing") is True and entry.get("active") is True
                        and entry.get("mediaState") == 1}
                    return bound, playing

                def describe(entry):
                    return {"uuid": str(entry.get("uuid") or ""),
                        "name": str(entry.get("name") or "")[:48],
                        "serial": entry.get("serial"), "mediaState": entry.get("mediaState"),
                        "showing": entry.get("showing"), "active": entry.get("active"),
                        "removed": entry.get("removed")}

                def fixture_fault():
                    """Harness-side fault for this window: which synthetic paths stopped pushing.

                    A loopback publisher can stall while its process is still alive, and then
                    every reader of that path — including a Program Scene's dedicated source —
                    goes silent with no product involvement. Only a path that provably stopped
                    pushing packets is repaired, so a product stall still fails the gate.
                    """
                    harness = fixture_publisher_health()
                    dead = [entry["index"] for entry in harness["publishers"]
                            if entry["state"] != "alive"]
                    unreadable = [index for index, ok in enumerate(harness["readable"]) if not ok]
                    stalled = [entry["index"] for entry in harness["pathProgress"]
                               if entry.get("flowing") is False]
                    return harness, sorted(set(dead) | set(unreadable) | set(stalled))

                def probe_on_window(role, order):
                    """One extra capture window taken with the host's render probe open.

                    Diagnostic only: it never replaces the pixel assertion. The probe draws the
                    preview Scene and the Program channel itself, so if this window moves while
                    the asserted window stayed frozen, the freeze depended on something the
                    probe changes (source show/activate state, or a graphics thread that only
                    runs while it draws). If it stays frozen too, the probe's own per-cell
                    digests say whether the Scene render changed underneath the stale capture.
                    """
                    if not render_probe_window(9.0):
                        return {"opened": False}
                    report = {"opened": True, "role": role}
                    watch = SerialWatch()
                    watch.start()
                    target = private / ("pixels-" + label + "-" + role + "-probe-on")
                    try:
                        target.mkdir()
                        process = subprocess.Popen([str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
                            "-File", str(HERE / "capture-pixels.ps1"), "-ExpectedProcessId", str(frontend_pid),
                            "-ExpectedExecutable", str(runtime / "bin/64bit/obs64.exe"),
                            "-ExpectedCreationTime", str(created), "-StateFile", str(metadata),
                            "-OutputDirectory", str(target)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", close_fds=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        try:
                            stdout, stderr = process.communicate(timeout=35)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            stdout, stderr = process.communicate()
                            raise
                        report["returnCode"] = int(process.returncode)
                        capture = pixel_windows.capture_report(
                            subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr))
                        report["captureFailed"] = capture.get("captureFailed") is True
                        if capture.get("captureFailed") is not True:
                            analysis = subprocess.run([shutil.which("node"), str(HERE / "pixel-pattern.cjs"),
                                "analyze", str(target / role), role, order, "true"], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=20)
                            moved = json.loads(analysis.stdout or "{}")
                            report["passed"] = moved.get("passed") is True
                            report["distinctTileCounts"] = moved.get("distinctTileCounts")
                            report["staleTiles"] = moved.get("staleTiles")
                        watched = watch.report()
                        report["renderFramesPerSecond"] = watched.get("renderFramesPerSecond")
                        report["renderProbe"] = {channel: {key: value for key, value in
                            (watched.get("renderProbe") or {}).get(channel, {}).items() if key != "timeline"}
                            for channel in ("preview", "program")}
                    except Exception as error:  # a diagnostic must never mask the real failure
                        report["probeWindowFailed"] = type(error).__name__
                    finally:
                        render_probe_close()
                    return report

                def measure_window(budget_seconds):
                    """Watch real per-input frame progress; return None when every input advanced."""
                    deadline = time.monotonic() + budget_seconds
                    windows, unresolved, silent_inputs = 0, None, []
                    silent_since = None
                    while time.monotonic() < deadline:
                        first = state()
                        first_serials = counted_serials(first)
                        bound_ids, playing_ids = rendered_input_ids(first)
                        expected = bound_ids | (playing_ids & set(first_serials))
                        # PLAYING with a counter that never left zero is the interesting case,
                        # so it is recorded every window; a source that only just opened is
                        # allowed because the host refreshes per-input health every 2 s.
                        silent_inputs = [describe(entry) for entry in video_entries(first)
                            if entry.get("showing") is True and entry.get("active") is True
                            and entry.get("mediaState") == 1
                            and str(entry.get("uuid") or "") not in first_serials]
                        if silent_inputs:
                            silent_since = silent_since or time.monotonic()
                        else:
                            silent_since = None
                        # Several refresh ticks of PLAYING-with-zero-callbacks is not "still
                        # opening"; it is an input the product opened and never decoded.
                        persistent_silent = silent_since is not None and \
                            time.monotonic() - silent_since >= 8.0
                        time.sleep(2.5)
                        later = state()
                        later_serials = counted_serials(later)
                        windows += 1
                        bound_later, _ = rendered_input_ids(later)
                        missing = sorted(expected - set(later_serials))
                        stagnant = [{"uuid": uuid, "before": first_serials.get(uuid),
                                     "after": later_serials.get(uuid)}
                            for uuid in sorted(expected & set(later_serials))
                            if int(later_serials[uuid]) <= int(first_serials[uuid])]
                        if len(bound_later) < 5:
                            missing.append("<fewer-than-five-wall-bindings>")
                        if not missing and not stagnant and not persistent_silent:
                            return None
                        unresolved = {"windowMs": 2500, "windows": windows,
                            "missingOrNewInputs": missing[:6], "stagnantInputs": stagnant[:6],
                            "playingWithoutFrameCount": silent_inputs[:4],
                            "persistentSilentMs": int((time.monotonic() - silent_since) * 1000)
                                if silent_since is not None else 0,
                            "countedInputs": len(later_serials),
                            "reportedInputs": len(video_entries(later)),
                            "videoInputs": [describe(entry) for entry in video_entries(later)][:16]}
                        evidence.setdefault("programPixelInputWait", []).append({
                            "phase": label, "waitedMs": int((time.monotonic() - started) * 1000),
                            "windows": windows, "watchedInputs": len(counted_serials(state())),
                            "stagnantInputs": unresolved["stagnantInputs"],
                            "playingWithoutFrameCount": silent_inputs[:4]})
                    return unresolved

                started = time.monotonic()
                unresolved, repairs = measure_window(30), []
                while unresolved is not None and len(repairs) < 2:
                    harness, faulty = fixture_fault()
                    if not faulty:
                        unresolved["fixturePublishers"] = harness["publishers"]
                        unresolved["fixtureStalledPaths"] = []
                        unresolved["fixturePathProgress"] = harness["pathProgress"][:5]
                        break
                    repairs.append({"phase": label, "paths": faulty,
                        "publishers": harness["publishers"],
                        "pathProgress": harness["pathProgress"][:5]})
                    for index in faulty:
                        rtsp.restart_publisher(index)
                    unresolved = measure_window(30)
                if repairs:
                    evidence["inputWaitFixtureRepair"] = repairs
                evidence.setdefault("programPixelInputWait", []).append({
                    "phase": label, "waitedMs": int((time.monotonic() - started) * 1000),
                    "watchedInputs": len(counted_serials(state())),
                    "fixtureRepairs": [entry["paths"] for entry in repairs]})
                if unresolved is not None:
                    evidence["inputWaitOffendingNames"] = sorted({str(item.get("name") or "")[:48]
                        for item in unresolved.get("playingWithoutFrameCount", [])
                        if str(item.get("name") or "")})[:8]
                    raise AssertionError(label + ": no watched video input delivered a newer frame inside a "
                        "measured 2500 ms window (the host refreshes its health counters "
                        "every 2 s): " + json.dumps(unresolved, sort_keys=True)[:900])
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
            serial_watch = SerialWatch()
            serial_watch.start()
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
            serials_during_capture = serial_watch.report()
            evidence.setdefault("captures", []).append({"phase": label, "serialsDuringCapture":
                serials_during_capture, **capture})
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
                        "pathProgress": harness["pathProgress"],
                        "stalledPaths": [entry["index"] for entry in harness["pathProgress"]
                                         if entry["flowing"] is False],
                        # A frozen slot is either a source that stopped delivering frames
                        # or a Scene that no longer renders the item. The product reports
                        # both, so the receipt says which one this was.
                        "videoInputs": observed.get("videoInputs", []),
                        "wallItems": int(observed.get("wallItems") or 0),
                        "programItems": int(observed.get("programItems") or 0),
                        "slots": [{"camera": str(binding.get("cameraId") or "")[:24],
                            "uuid": str(binding.get("sourceUuid") or "")[:8]}
                            for binding in observed.get("bindings", [])[:8]
                            if isinstance(binding, dict)],
                        # Whether the frozen slot's own source delivered callbacks during
                        # the capture window separates "media side stopped feeding frames"
                        # from "frames arrived but the item did not repaint"; without this
                        # a frozen slot has no cause at all.
                        "inputSerialDelta": None,
                        # Content digests from the analysis say which region stopped
                        # repainting; the in-window counters say whether its media input
                        # stopped feeding frames during exactly that window.
                        "serialsDuringCapture": serials_during_capture,
                        "distinctClientCount": result.get("distinctClientCount"),
                        "distinctTileCounts": result.get("distinctTileCounts"),
                        "staleTiles": result.get("staleTiles")}
                    later = state()
                    def serials(snapshot):
                        return {str(entry.get("uuid") or ""): entry.get("serial")
                            for entry in snapshot.get("videoInputs", []) if isinstance(entry, dict)}
                    earlier_serials, after_serials = serials(observed), serials(later)
                    evidence["pixelFailureDiagnostics"]["inputSerialDelta"] = [
                        {"uuid": uuid, "before": earlier_serials.get(uuid), "after": after_serials.get(uuid),
                         "advanced": (type(after_serials.get(uuid)) is int and type(earlier_serials.get(uuid)) is int
                                      and after_serials[uuid] > earlier_serials[uuid])}
                        for uuid in sorted(after_serials)]
                    evidence["pixelFailureDiagnostics"]["stalledMsAfterCapture"] = [
                        {"uuid": str(entry.get("uuid") or ""), "stalledMs": entry.get("stalledMs")}
                        for entry in later.get("videoInputs", []) if isinstance(entry, dict)]
                    # Which layer froze each tile. Advancing input counters only prove a
                    # frame reached the source, so three bounded measurements of the same
                    # window are compared: the feed's own delivered-frame digest, the
                    # host's Scene/Program render digests, and the captured window pixels.
                    probe = serials_during_capture.get("renderProbe") or {}
                    preview_probe = probe.get("preview") or {}
                    program_probe = probe.get("program") or {}
                    preview_tiles = preview_probe.get("distinctCellsPerTile") or []
                    program_tiles = program_probe.get("distinctCellsPerTile") or []
                    # Outside Studio mode the frontend exposes no separate preview scene,
                    # and the Program channel is what actually renders; prefer whichever
                    # channel has samples and say which one the verdict came from.
                    scene_channel = "preview" if int(preview_probe.get("samples") or 0) > 0 else "program"
                    scene_tiles = preview_tiles if scene_channel == "preview" else program_tiles
                    feed = {str(entry.get("uuid") or ""): entry
                            for entry in serials_during_capture.get("inputs", []) if isinstance(entry, dict)}
                    stale_tiles = [index for index in (result.get("staleTiles") or []) if type(index) is int]
                    slots = evidence["pixelFailureDiagnostics"]["slots"]
                    # staleTiles and the render-probe cells are both row-major grid
                    # positions, so they compare directly. Which camera sits in that
                    # position depends on this capture's order, and only that camera's
                    # feed can explain the tile.
                    if order.startswith("quick-"):
                        channels = [int(value) for value in order[len("quick-"):].split(",") if value.isdigit()]
                    else:
                        channels = {"repeat-first": [0, 0, 0, 0, 0], "reverse": [4, 3, 2, 1, 0]}.get(
                            order, [0, 1, 2, 3, 4])
                    stale_camera = {tile: channels[tile] if tile < len(channels) else tile for tile in stale_tiles}
                    def feed_content_probe(indices):
                        # Decode the fixture path itself for a bounded window. pathProgress
                        # only proves bytes flow; hashing downscaled decoded frames proves
                        # the loopback publisher emits *changing* content, which separates a
                        # repeating feed from a product-side stall.
                        out = []
                        for index in indices[:6]:
                            if index >= len(rtsp.urls):
                                continue  # fixture path index is the camera index
                            try:
                                decoded = subprocess.run([str(ffmpeg), "-rtsp_transport", "tcp", "-i",
                                    rtsp.urls[index], "-t", "4", "-an", "-vf", "scale=64:36",
                                    "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=18)
                            except (OSError, subprocess.TimeoutExpired):
                                out.append({"index": index, "probeFailed": True})
                                continue
                            chunk = 64 * 36 * 3
                            digests = {hashlib.sha256(decoded.stdout[at:at + chunk]).hexdigest()[:12]
                                for at in range(0, len(decoded.stdout) - chunk + 1, chunk)}
                            out.append({"index": index, "returnCode": int(decoded.returncode),
                                "decodedFrames": len(decoded.stdout) // chunk, "distinctFrames": len(digests)})
                        return out
                    attribution = []
                    for tile in stale_tiles:
                        camera = stale_camera[tile]
                        slot = slots[camera] if camera < len(slots) else {}
                        uuid = str(slot.get("uuid") or "")
                        feed_entry = feed.get(uuid) or {}
                        scene = scene_tiles[tile] if tile < len(scene_tiles) else None
                        program = program_tiles[tile] if tile < len(program_tiles) else None
                        distinct_feed = int(feed_entry.get("distinctFeedHashes") or 0)
                        if not feed_entry.get("feedIdentityObserved"):
                            verdict = "feed-identity-unavailable"
                        elif distinct_feed <= 1:
                            verdict = "feed-repeats-one-frame"
                        elif scene is not None and scene <= 1:
                            verdict = "scene-render-frozen-while-feed-changed"
                        elif scene is not None and scene > 1:
                            verdict = "window-capture-stale-while-scene-render-changed"
                        else:
                            verdict = "undetermined-without-render-probe-samples"
                        attribution.append({"tile": tile, "camera": camera, "order": order[:20],
                            "uuid": uuid[:8], "role": role,
                            "feedDistinctFramesInWindow": distinct_feed,
                            "feedSerialAdvanced": bool(feed_entry.get("advanced")),
                            "feedMaxFrameAgeMs": int(feed_entry.get("maxFrameAgeMs") if feed_entry else -1),
                            "sceneRenderChannel": scene_channel,
                            "sceneRenderDistinctTiles": scene, "programRenderDistinctTiles": program,
                            "verdict": verdict})
                    evidence["pixelFailureDiagnostics"]["layerAttribution"] = attribution
                    evidence["pixelFailureDiagnostics"]["feedDecodeProbe"] = feed_content_probe(
                        sorted(set(stale_camera.values())))
                    evidence["pixelFailureDiagnostics"]["renderProbeWindow"] = {
                        channel: {key: value for key, value in (probe.get(channel) or {}).items() if key != "timeline"}
                        for channel in ("preview", "program")}
                    stalled = [entry["index"] for entry in harness["pathProgress"] if entry["flowing"] is False]
                    if (dead or unreadable or stalled) and fixture_retry:
                        # The synthetic fixture itself dropped out: restart every dead publisher,
                        # prove the host resumes decoding, then re-run this exact pixel phase
                        # once. A product-side stall with a healthy fixture still fails below.
                        evidence["fixtureRestartedAfterPixelFailure"] = {"phase": label,
                            "deadPublishers": dead, "unreadablePaths": unreadable, "stalledPaths": stalled}
                        repaired = sorted(set(dead + unreadable + stalled))
                        for index in repaired:
                            rtsp.restart_publisher(index)
                        wait_for(lambda: fixture_recovered(repaired),
                            "restarted loopback fixture did not resume frame progress", timeout=90)
                        evidence["fixtureRestartResumed"] = label
                        return check_pixels(label, blank=blank, repeat_first=repeat_first, reverse=reverse,
                            expected_media=expected_media, projector_orders=projector_orders,
                            quick_order=quick_order, program_scene=program_scene,
                            program_media=program_media, fixture_retry=False)
                    # Fixture healthy and pixels still frozen: one probe-open window
                    # before failing, so the next receipt names the layer instead of
                    # guessing. Diagnostic only; the assertion below is unchanged.
                    evidence["pixelFailureDiagnostics"]["probeOnWindow"] = probe_on_window(role, order)
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

                def wait_program_mix_audible(label, timeout=60):
                    """Wait until every Program mix that should carry sound is delivering it.

                    The mixer process only binds its local endpoint after ffmpeg has opened the
                    camera input, so the media source's first open can fail and OBS reconnects a
                    second later. Starting a recording inside that lead-in encodes silence, which
                    is what the rc.42 default-bus MP4 showed. A mix whose declared inputs are all
                    muted or zero-gain is intentionally silent and is not waited on. The measured
                    wait is recorded instead of hidden.
                    """
                    started = time.monotonic()

                    def ready(observed):
                        entries = [item for item in observed if item.get("available") is True]
                        for item in entries:
                            wants_audio = any(entry.get("muted") is False and float(entry.get("gain", 0)) > 0
                                              for entry in item.get("audioInputs", []) if isinstance(entry, dict))
                            if item.get("mediaState") != 1:
                                return None
                            if wants_audio and item.get("peakDbfs", -120) <= -60:
                                return None
                        return {"sources": entries}

                    def detail():
                        return json.dumps([{key: item.get(key) for key in
                            ("sourceId", "mediaState", "peakDbfs", "mixers", "muted", "volume",
                             "processExitCode")} for item in state().get("audioSources", [])],
                            sort_keys=True)[:700]

                    result = wait_for(lambda: ready(state().get("audioSources", [])),
                        lambda: f"{label} Program mix was not delivering audio: " + detail(), timeout=timeout)
                    evidence.setdefault("programMixLeadIn", []).append({
                        "label": label, "waitedMs": int((time.monotonic() - started) * 1000),
                        "mixers": sorted(int(item.get("mixers") or 0) for item in result["sources"])})
                    checkpoint("program-mix-audible-" + label)
                    return result["sources"]

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
                wait_program_mix_audible("program-take")
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
                wait_program_mix_audible("default-bus")
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
                # Program publishing uses the same Program OBS output and owns
                # a private MediaMTX only while streaming. The host publishes
                # over loopback RTMP (the pinned Windows OBS tree has no
                # WebRTC plugin) and the relay republishes the mix. RTSP
                # playback proves the packets reached a real consumer, not just
                # an active flag.
                phase = "program-streaming"
                wait_program_mix_audible("program-streaming")
                assert ui("stream-program")
                def streaming_ready():
                    value = state().get("programOutput", {})
                    return value if (isinstance(value, dict) and value.get("streaming") is True and
                        value.get("streamConnected") is True and
                        isinstance(value.get("streamPlaybackUrl"), str)) else None
                def streaming_failure():
                    # MediaMTX and the publish output report their refusal in the
                    # host's own output state; without this the gate would only
                    # say "did not start".
                    return ("native Program publishing did not start: host="
                        + json.dumps(state().get("programOutput", {}), sort_keys=True)[:700])
                streamed = wait_for(streaming_ready, streaming_failure, timeout=40)
                playback_url = streamed["streamPlaybackUrl"]
                assert re.fullmatch(r"rtsp://127\.0\.0\.1:[0-9]{2,5}/program", playback_url), \
                    "native Program publisher exposed an unexpected playback URL"
                checkpoint("program-streaming-started")
                def readable_stream(url=None):
                    # A relay path is only readable once the publisher has delivered a
                    # keyframe, so every read of a playback URL is retried within a
                    # bounded window instead of probing once.
                    target = playback_url if url is None else url
                    probe = subprocess.run([str(runtime / "bin/ffprobe.exe"), "-v", "error",
                        "-rtsp_transport", "tcp", "-show_entries", "stream=codec_name,codec_type", "-of", "json",
                        target], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
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
                assert any(stream.get("codec_type") == "audio" and stream.get("codec_name") == "aac"
                    for stream in stream_streams), "published Program has no AAC audio"
                # An AAC stream header is not audible evidence. Decode the real
                # consumer and require both fixture pitches inside the band split.
                assert streamed.get("audioTracks") == 1, \
                    f"Program publisher encoded mask {streamed.get('audioTracks')}, expected the default bus 1"
                published_low = pixel_windows.band_rms(ffmpeg, playback_url, 0, lowpass=600)
                published_high = pixel_windows.band_rms(ffmpeg, playback_url, 0, highpass=660)
                evidence["programStreamBandRms"] = {"below600Hz": published_low,
                    "above660Hz": published_high, "audioTrackMask": streamed.get("audioTracks")}
                assert published_low > 150 and published_high > 150, \
                    "published Program audio lost one of the two fixture pitches"
                evidence["checks"].append("program-publish-decodes-both-fixture-pitches")
                # A late RTSP consumer joins inside the encoder's current GOP, so the first
                # packets can be P-slices with no reference picture: reading 20 packets
                # decoded zero frames twice (runs 44524750280 and 44534272424) with return
                # code 0, "co located POCs unavailable" / "mmco: unref short failure", while
                # OBS advanced its render counter by 60 frames, laggedFrames stayed at 8 and
                # the relay reported a connected stream. One connection is therefore read
                # across at least two publish keyframe intervals, and the receipt names when
                # the first decodable frame arrived and whether the window really timed out.
                encoder_keyint_seconds = PROGRAM_ENCODER_KEYINT_SECONDS
                video_window_seconds = PROGRAM_VIDEO_WINDOW_SECONDS
                render_before = state().get("renderFrames")
                lagged_before = state().get("laggedFrames")
                video_window = published_video_window(runtime / "bin/ffprobe.exe",
                    playback_url, video_window_seconds)
                packet_summary = published_packet_window(runtime / "bin/ffprobe.exe",
                    playback_url, video_window_seconds)
                stamps = video_window["stamps"]
                span = video_window["ptsSpanSeconds"]
                monotonic = video_window["monotonicTimestamps"]
                after = state()
                evidence["programStreamVideoProbe"] = {
                    "windowSeconds": video_window["windowSeconds"],
                    "encoderKeyintSeconds": encoder_keyint_seconds,
                    "firstDecodableFrameMs": video_window["firstDecodableFrameMs"],
                    "windowTimedOut": video_window["windowTimedOut"],
                    "elapsedMs": video_window["elapsedMs"],
                    "returnCode": video_window["returnCode"],
                    "stderrTail": video_window["stderrTail"],
                    "unparsableStamps": video_window["unparsableStamps"],
                    "frames": video_window["frames"],
                    "ptsSpanSeconds": video_window["ptsSpanSeconds"],
                    "measuredFramesPerSecond": video_window["measuredFramesPerSecond"],
                    "monotonicTimestamps": monotonic,
                    "packetProbe": packet_summary,
                    "hostRenderFramesBefore": render_before, "hostRenderFramesAfter": after.get("renderFrames"),
                    "hostLaggedFramesBefore": lagged_before, "hostLaggedFramesAfter": after.get("laggedFrames"),
                    "streamError": str((after.get("programOutput") or {}).get("streamError") or "")[:200],
                    "streamConnected": (after.get("programOutput") or {}).get("streamConnected")}
                assert len(stamps) >= 10 and monotonic and span >= float(encoder_keyint_seconds), \
                    "published Program did not deliver enough decodable video frames across " \
                    + str(video_window_seconds) + " seconds (two keyframe intervals)"
                # The relay also republishes the same path for browsers. This gate
                # does not perform a WebRTC handshake; it requires the WHEP endpoint
                # to answer at all, and records that plainly rather than claiming a
                # browser played the mix.
                whep_url = streamed.get("streamPlaybackWhep")
                assert isinstance(whep_url, str) and re.fullmatch(
                    r"http://127\.0\.0\.1:[0-9]{2,5}/program/whep", whep_url), \
                    f"Program publisher exposed an unexpected WHEP playback URL {whep_url!r}"
                assert streamed.get("streamTransport") == "rtmp", \
                    f"Program publish transport {streamed.get('streamTransport')!r}; expected rtmp"
                whep_status = None
                try:
                    with urllib.request.urlopen(whep_url, timeout=5) as response:
                        whep_status = response.status
                except urllib.error.HTTPError as error:
                    whep_status = error.code
                evidence["programWhepEndpoint"] = {"status": whep_status,
                    "note": "relay endpoint reachable; no browser WebRTC handshake is gated"}
                assert whep_status is not None, "the relay WHEP endpoint did not answer"
                evidence["checks"].append("program-publish-transport-is-rtmp-with-a-whep-endpoint")
                assert ui("stream-program")
                wait_for(lambda: state().get("programOutput", {}).get("streaming") is False and
                    state().get("programOutput", {}).get("mediaMtxRunning") is False,
                    "native Program publisher did not release MediaMTX", timeout=30)
                evidence["checks"].append("program-composite-publish-stream")
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
                    wait_program_mix_audible(label)
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
                # Each encoded bus is read inside a window where its own pitch holds the
                # same amplitude across both halves, so lead-in silence cannot hide a
                # leak or fake an absence.
                isolation_first = pixel_windows.steady_tone_window(ffmpeg, str(isolation_path), 0,
                    steady=(440,), measure=(1200,))
                isolation_second = pixel_windows.steady_tone_window(ffmpeg, str(isolation_path), 1,
                    steady=(1200,), measure=(440,))
                isolation_first_440 = isolation_first["amplitudes"]["440"]
                isolation_first_1200 = isolation_first["amplitudes"]["1200"]
                isolation_second_1200 = isolation_second["amplitudes"]["1200"]
                isolation_second_440 = isolation_second["amplitudes"]["440"]
                evidence["programBusIsolation"] = {
                    "busTwo": {"at440Hz": isolation_first_440, "at1200Hz": isolation_first_1200},
                    "busThree": {"at1200Hz": isolation_second_1200, "at440Hz": isolation_second_440},
                    "steadyWindowStarts": {"busTwo": isolation_first["start"],
                        "busThree": isolation_second["start"]}}
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
                muted_window = pixel_windows.steady_tone_window(ffmpeg, str(muted_path), 0,
                    steady=(440,), measure=(880,))
                muted_440 = muted_window["amplitudes"]["440"]
                muted_880 = muted_window["amplitudes"]["880"]
                evidence["programTrackMute"] = {"at440Hz": muted_440, "at880Hz": muted_880,
                    "audioTrackMask": muted.get("audioTracks"),
                    "steadyWindowStart": muted_window["start"],
                    "toneReadings": muted_window["toneReadings"]}
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
                # rc.59 read the reference over the first three seconds of the file. The
                # mixer was still emitting adelay/late-track silence for part of that
                # window, so every pitch was understated by its silence fraction and the
                # untouched track then looked as if it had risen by 1.7x. The amplitude is
                # taken where both pitches hold steady instead.
                reference_window = pixel_windows.steady_tone_window(
                    ffmpeg, str(gain_full_path), 0, steady=(440, 880))
                gain_full_440 = reference_window["amplitudes"]["440"]
                gain_full_880 = reference_window["amplitudes"]["880"]
                assert gain_full_440 > 200 and gain_full_880 > 200, \
                    "both tracks at gain one were not audible in the received file"
                # The identical configuration recorded again must measure the same two
                # pitches. Drift at this step is a measurement fault and gets named here,
                # before a later gain change can be mistaken for a mixer fault.
                gain_repeat = record_program_output("per-track gain reference repeat")
                repeat_window = pixel_windows.steady_tone_window(
                    ffmpeg, str(Path(gain_repeat["recordingPath"])), 0, steady=(440, 880))
                control_ratios = {"440": round(repeat_window["amplitudes"]["440"] / gain_full_440, 3),
                    "880": round(repeat_window["amplitudes"]["880"] / gain_full_880, 3)}
                # Write the measurement before judging it. rc.68 lost the numbers behind
                # this control step because the evidence was only written after the
                # assertion, so a rejected reference left nothing to read in the receipt.
                evidence["programTrackGain"] = {"gainOne": {"at440Hz": gain_full_440,
                    "at880Hz": gain_full_880}, "controlRatios": control_ratios,
                    "steadyWindowStarts": {"reference": reference_window["start"],
                        "repeat": repeat_window["start"]},
                    "toneReadings": {"reference": reference_window["toneReadings"],
                        "repeat": repeat_window["toneReadings"]}}
                assert all(0.8 <= ratio <= 1.25 for ratio in control_ratios.values()), \
                    f"the unchanged gain configuration measured differently twice: {control_ratios}"
                low_gain = alt_variant("fixture-alt-gain-low", [
                    {"track": 0, "gain": 1, "muted": False, "syncOffsetMs": 0},
                    {"track": 1, "gain": 0.2, "muted": False, "syncOffsetMs": 0}])
                apply_program_scene(low_gain, 2)
                gain_low = record_program_output("per-track gain reduced")
                gain_low_path = Path(gain_low["recordingPath"])
                reduced_window = pixel_windows.steady_tone_window(ffmpeg, str(gain_low_path), 0,
                    steady=(440,), measure=(880,))
                gain_low_440 = reduced_window["amplitudes"]["440"]
                gain_low_880 = reduced_window["amplitudes"]["880"]
                evidence["programTrackGain"].update({"gainPointTwo": {"at440Hz": gain_low_440,
                    "at880Hz": gain_low_880},
                    "steadyWindowStarts": {"reference": reference_window["start"],
                        "repeat": repeat_window["start"], "reduced": reduced_window["start"]},
                    "reducedToneReadings": reduced_window["toneReadings"]})
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
                phase = "program-publish-disconnect"
                # Publish relay loss: killing the product's own private MediaMTX child
                # must surface a concrete disconnect instead of a permanently
                # "connected" publisher, and the next start must recover. The Scene
                # audio mixers are separate owned helpers, so record them first and
                # require the same set afterwards instead of demanding no FFmpeg at all.
                def audio_mix_helper_watch(sample):
                    """Every owned FFmpeg helper, its loopback mix port and the host's claim.

                    A PID diff alone cannot say which mix lost its feeder, and a product
                    that legitimately respawns a helper would also look like a leak by PID.
                    The mix port is the stable identity: each owned mix source listens on
                    one loopback port, so the claimed ports and the live helper ports have
                    to agree. The host's own `available` and exit code then say whether the
                    product released a helper it still needs or never noticed one died.
                    The recorded row is returned, because the port comparison needs the
                    claims and the helper ports together; run 44568325933 compared the
                    returned helper PID list against those claims and died on a TypeError
                    instead of reporting a mix verdict.
                    """
                    rows = sorted(pid for pid, name in child_processes(powershell, int(state()["pid"]))
                        if name == "ffmpeg.exe")
                    identities = mixer_identities(powershell, rows, (private, runtime, profile))
                    claim = [{"sourceId": str(entry.get("sourceId") or "")[:64],
                        "mixers": entry.get("mixers"), "processExitCode": entry.get("processExitCode"),
                        "available": entry.get("available"), "active": entry.get("active"),
                        "mixerPort": entry.get("mixerPort")}
                        for entry in state().get("audioSources", []) if isinstance(entry, dict)]
                    # The loopback fixture publishers are harness state. Recording them
                    # beside the helpers lets a receipt correlate a mix feeder that died
                    # with the fixture path that fed it, instead of blaming the product.
                    fixtures = [{"index": index,
                        "state": "alive" if publisher is not None and publisher.poll() is None
                        else ("stopped" if publisher is None else "exited")}
                        for index, publisher in enumerate(rtsp.publishers)]
                    def identity_of(pid):
                        return identities.get(pid) or MIXER_IDENTITY_UNAVAILABLE
                    row = {"sample": sample, "processes": [{"pid": pid,
                        "port": identity_of(pid)["port"],
                        "identity": identity_of(pid)["identity"],
                        "tail": identity_of(pid)["tail"]}
                        for pid in rows], "hostClaims": claim, "fixturePublishers": fixtures,
                        # A short-lived AV remux is also an owned ffmpeg child. Keep it out
                        # of the mix comparison but record it so a helper count is never
                        # silently explained away.
                        "otherHelpers": [{"pid": pid,
                            "identity": identity_of(pid)["identity"][:120],
                            "tail": identity_of(pid)["tail"]}
                            for pid in rows if identity_of(pid)["port"] is None]}
                    evidence.setdefault("audioMixHelperWatch", []).append(row)
                    return row

                scene_start_watch = audio_mix_helper_watch("publish-disconnect-start")
                relay_children = [pid for pid, name in child_processes(powershell, int(state()["pid"]))
                    if name == "mediamtx.exe"]
                assert relay_children == [], "MediaMTX survived the normal publisher stop"
                assert ui("stream-program")
                recovered_stream = wait_for(streaming_ready, "Program publishing did not start for the disconnect probe",
                    timeout=40)
                relay_children = [pid for pid, name in child_processes(powershell, int(state()["pid"]))
                    if name == "mediamtx.exe"]
                remember_owned_pids(relay_children)
                assert len(relay_children) == 1, \
                    f"Program streaming owned {len(relay_children)} MediaMTX children, expected one"
                evidence["publishRelayPid"] = relay_children[0]
                terminate_process(powershell, relay_children[0])
                wait_for(lambda: state().get("programOutput", {}).get("streaming") is False and
                    str(state().get("programOutput", {}).get("streamError", "")).startswith("publish-") and
                    state().get("programOutput", {}).get("mediaMtxRunning") is False,
                    "killing the private MediaMTX relay did not surface a publish disconnect", timeout=30)
                evidence["publishDisconnectError"] = str(state().get("programOutput", {}).get("streamError"))[:120]
                disconnected_url = recovered_stream.get("streamPlaybackUrl")
                checkpoint("program-publish-disconnect-reported")
                assert ui("stream-program")
                restarted_stream = wait_for(streaming_ready,
                    "Program publishing could not start again after a relay loss", timeout=40)
                assert restarted_stream.get("streamConnected") is True, \
                    "restarted publisher never delivered frames again"
                assert restarted_stream.get("streamPlaybackUrl") != disconnected_url, \
                    "recovered publisher reused the relay endpoint of the killed process"
                replay_url = restarted_stream["streamPlaybackUrl"]
                replay_streams = []
                replay_deadline = time.monotonic() + 40
                while time.monotonic() < replay_deadline:
                    replay_streams = readable_stream(replay_url)
                    if replay_streams:
                        break
                    time.sleep(0.5)
                assert any(item.get("codec_type") == "video" for item in replay_streams), \
                    f"recovered publisher is not readable by a real consumer: {replay_streams}"
                # Recovered publishing must still deliver frames, not only a stream
                # header, so the same bounded frame window as the first publisher runs
                # against the recovered playback URL.
                # The recovered publisher is a brand-new encoder session, so this
                # consumer joins mid-GOP exactly as the first one did: the same
                # keyframe-spanning window and the same decodable-frame bar apply.
                replay_window = published_video_window(runtime / "bin/ffprobe.exe",
                    replay_url, video_window_seconds)
                evidence["publishReplayFrameCount"] = replay_window["frames"]
                evidence["publishReplayVideoProbe"] = {
                    "windowSeconds": replay_window["windowSeconds"],
                    "firstDecodableFrameMs": replay_window["firstDecodableFrameMs"],
                    "windowTimedOut": replay_window["windowTimedOut"],
                    "elapsedMs": replay_window["elapsedMs"],
                    "returnCode": replay_window["returnCode"],
                    "stderrTail": replay_window["stderrTail"],
                    "unparsableStamps": replay_window["unparsableStamps"],
                    "frames": replay_window["frames"],
                    "ptsSpanSeconds": replay_window["ptsSpanSeconds"],
                    "measuredFramesPerSecond": replay_window["measuredFramesPerSecond"],
                    "monotonicTimestamps": replay_window["monotonicTimestamps"],
                    "packetProbe": published_packet_window(runtime / "bin/ffprobe.exe",
                        replay_url, video_window_seconds)}
                assert replay_window["frames"] >= 10 \
                    and replay_window["monotonicTimestamps"] \
                    and replay_window["ptsSpanSeconds"] >= float(encoder_keyint_seconds), \
                    f"recovered publisher delivered {replay_window['frames']} decodable video " \
                    + f"frames across {video_window_seconds} seconds, expected at least 10 " \
                    + "monotonic frames spanning one keyframe interval"
                evidence["checks"].append("publish-recovery-delivers-frames-to-a-real-consumer")
                mixers_before_stop = audio_mix_helper_watch("before-program-output-stop")
                assert mixers_before_stop["processes"], \
                    "no owned FFmpeg audio mixer helper was running"
                assert ui("stream-program")
                wait_for(lambda: state().get("programOutput", {}).get("streaming") is False and
                    state().get("programOutput", {}).get("mediaMtxRunning") is False,
                    "recovered publisher did not release MediaMTX after stopping", timeout=30)
                after_stop = child_processes(powershell, int(state()["pid"]))
                leaked_relay = sorted(pid for pid, name in after_stop if name == "mediamtx.exe")
                audio_mix_helper_watch("after-program-output-stop")
                assert leaked_relay == [], \
                    f"Program output kept the private MediaMTX relay after stopping: {leaked_relay}"
                after_watch = evidence["audioMixHelperWatch"][-1]
                before_watch = evidence["audioMixHelperWatch"][-2]
                started_ports = claimed_ports(scene_start_watch)
                claimed = claimed_ports(after_watch)
                # Each owned mix source reads exactly one loopback port and each mix
                # helper owns exactly one, so the live helper ports have to equal the
                # ports the host claims. Run 44548882087 lost one PID inside this window
                # while the host claimed exactly the one mix that still had a helper:
                # that was a retiring Scene graph releasing its own feeder, not a lost
                # mixer. Convergence keeps both real failure modes named - a claimed port
                # with no live helper is a mix the user cannot hear, and an unclaimed
                # helper is a leak that outlives its mix source.
                assert len(started_ports) == len(scene_start_watch["hostClaims"]) > 0, \
                    "an owned mix source did not report its loopback mix port: " \
                    + json.dumps(scene_start_watch["hostClaims"])[:300]
                # A mix the host claims has to be fed at every sample. Extra helpers are
                # allowed only while a retiring Scene graph releases its own feeder, and
                # the convergence below has to see them go.
                for sample in (scene_start_watch, before_watch):
                    starving = sorted(set(claimed_ports(sample)) - set(watched_ports(sample)))
                    assert starving == [], \
                        f"mix ports the host claims had no live helper at " \
                        + f"{sample['sample']}: {starving} feed mix " \
                        + json.dumps([str(entry.get("sourceId") or "")[:64]
                            for entry in sample["hostClaims"]
                            if int(entry.get("mixerPort") or 0) in starving])[:240] \
                        + f"; live {watched_ports(sample)}; host claims " \
                        + json.dumps(sample["hostClaims"])[:300] \
                        + "; fixture publishers " + json.dumps(sample["fixturePublishers"])[:200]

                def current_live_ports():
                    rows = sorted(pid for pid, name in child_processes(powershell, int(state()["pid"]))
                        if name == "ffmpeg.exe")
                    identities = mixer_identities(powershell, rows, (private, runtime, profile))
                    return sorted(filter(None, (identities.get(pid, MIXER_IDENTITY_UNAVAILABLE)
                        ["port"] for pid in rows))), rows

                def mix_ports_unresolved():
                    audio_mix_helper_watch("mix-ports-still-unresolved")
                    row = evidence["audioMixHelperWatch"][-1]
                    live, claim = watched_ports(row), claimed_ports(row)
                    owner_by_port = {int(entry["mixerPort"]): str(entry.get("sourceId") or "")[:64]
                        for entry in row["hostClaims"]
                        if isinstance(entry.get("mixerPort"), (int, float)) and int(entry["mixerPort"]) > 0}
                    unserved = sorted(set(claim) - set(live))
                    starved = [entry for entry in row["hostClaims"]
                        if int(entry.get("mixerPort") or 0) in unserved]
                    return ("Program output left mix ports unresolved (live " + json.dumps(live)
                        + ", claimed " + json.dumps(claim)
                        + f"; unserved {unserved} feed mix {[owner_by_port[port] for port in unserved]}"
                        + f"; orphan helpers {sorted(set(live) - set(claim))}"
                        + f"; host still reports a live mix for {json.dumps(starved)[:240]}"
                        + f"; fixture publishers {json.dumps(row['fixturePublishers'])[:200]}"
                        + f"; other helpers {json.dumps(row['otherHelpers'])[:200]})")

                settled = [None]
                settle_started = time.monotonic()
                while time.monotonic() < settle_started + 40:
                    settled[0] = current_live_ports()
                    if settled[0][0] == claimed:
                        break
                    time.sleep(2)
                if settled[0] is None or settled[0][0] != claimed:
                    raise AssertionError(mix_ports_unresolved())
                evidence["sceneAudioMixers"] = settled[0][0]
                evidence["sceneAudioMixerPids"] = settled[0][1]
                evidence["mixerPortSettleMs"] = int((time.monotonic() - settle_started) * 1000)
                evidence["checks"].extend(["publish-relay-loss-is-reported-and-recoverable",
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
            # Graphics-thread pacing and probe window state: a "not enough frames" failure
            # has to say whether the host itself stopped rendering or only the published
            # path delivered too little.
            for key in ("renderFrames", "laggedFrames", "publishedAtMs", "videoAvailable"):
                if key in observed:
                    evidence["observedState"][key] = observed[key]
            evidence["observedState"]["renderProbe"] = render_probe_summary(observed)
            # Only fixed categories/counts from this boot's newest OBS log.
            # Never publish its contents, path, exception text or camera URL.
            # The two reconnect markers are OBS's own words for a media input that lost
            # its connection: a frozen tile with a rising "Disconnected" count is a media
            # transport stall, not a render stall, so the receipt states which one it was.
            obs_markers = ("Switched to Preview/Program mode", "Switched to regular Preview mode",
                "Failed to initialize", "Failed to create", "QWidget", "QObject", "QLayout",
                "Shutting down", "All scene data cleared", "Number of remaining allocations",
                "Disconnected. Reconnecting", "Reconnected.", "MP: Failed to open media",
                # A source can report PLAYING while its decoder never emits a frame; these
                # are media_playback's own words for that, so the receipt can separate
                # "opened but silent" from "never opened".
                "MP: Failed to open video decoder", "MP: Failed to find video codec",
                "MP: Could not initialize audio or video", "MP: av_read_frame failed",
                "MP: Failed to seek",
                # The owned video path's two bounded OBS-log markers: an async queue that
                # OBS dropped whole, and a media timestamp jump it had to re-base. Both
                # explain a tile whose counters advance but whose pixels stay stale.
                "WebOBS async video backlog", "WebOBS async timestamp jump")
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
                media_lines = []
                for line in tail.splitlines():
                    clean = re.sub(r"(?:rtsp|rtsps|udp|http|https)://\S+", "<url>", line)
                    for private_value in (str(private), str(runtime), str(profile)):
                        clean = clean.replace(private_value, "<private>")
                    clean = clean[:200]
                    if any(marker in line for marker in audio_markers):
                        diagnostic_lines.append(clean)
                    if any(marker in line for marker in ("Disconnected. Reconnecting", "Reconnected.",
                            "MP: Failed to open media", "Error opening input",
                            "WebOBS async video backlog", "WebOBS async timestamp jump")):
                        media_lines.append(clean)
                evidence["obsDiagnosticLines"] = diagnostic_lines[-12:]
                # Scene add/remove lines used to crowd the window above, so transport
                # failures get their own bounded tail instead of being filtered away.
                evidence["mediaDiagnosticLines"] = media_lines[-8:]
                # A marker count alone cannot say what failed. Keep one sanitized
                # example line per marker that actually occurred, so "Failed to
                # initialize: 1" names the source or filter behind it instead of
                # leaving the next reader to guess. URLs, private paths and the
                # absolute runtime/profile roots are replaced first.
                wanted = {marker for marker, count in evidence["currentBootObsMarkers"].items() if count}
                marker_lines = {}
                for line in tail.splitlines():
                    if len(marker_lines) == len(wanted):
                        break
                    for marker in wanted:
                        if marker in marker_lines or marker not in line:
                            continue
                        clean = re.sub(r"(?:rtsp|rtsps|udp|http|https)://\S+", "<url>", line)
                        for private_value in (str(private), str(runtime), str(profile)):
                            clean = clean.replace(private_value, "<private>")
                        marker_lines[marker] = clean[:160]
                evidence["currentBootObsMarkerLines"] = marker_lines
                # An input that OBS reports PLAYING but that never delivers a frame is only
                # explainable from the media side of the log. Keep the lines that name an
                # offending source, or that media_playback wrote about an open/read failure.
                wanted_names = [name for name in evidence.get("inputWaitOffendingNames", [])[:6] if name]
                input_lines = []
                for line in tail.splitlines():
                    clean = re.sub(r"(?:rtsp|rtsps|udp|http|https)://\S+", "<url>", line)
                    for private_value in (str(private), str(runtime), str(profile)):
                        clean = clean.replace(private_value, "<private>")
                    clean = clean[:160]
                    if any(name in line for name in wanted_names) or "MP: " in line:
                        input_lines.append(clean)
                if input_lines:
                    evidence["inputWaitLogLines"] = input_lines[-10:]
            fixture_log = private / "rtsp-test.log"
            if rtsp is not None and fixture_log.is_file() and not fixture_log.is_symlink():
                # The loopback publishers and MediaMTX are harness state. A reader that opens
                # a path but receives no packets is a fixture/transport stall, not a product
                # defect, so the sanitized tail belongs in the receipt. URLs and the run token
                # are replaced; only loopback path names remain, which are synthetic.
                with fixture_log.open("rb") as source:
                    source.seek(max(0, fixture_log.stat().st_size - 65536))
                    raw = source.read().decode("utf-8", errors="replace")
                token = ""
                if rtsp.urls:
                    tail_of_url = rtsp.urls[0].split("/8554/")[-1]
                    parts = tail_of_url.split("-")
                    token = parts[1] if len(parts) > 1 else ""
                server_lines = []
                for line in raw.splitlines():
                    clean = line.replace(token, "<token>") if token else line
                    clean = re.sub(r"(?:rtsp|rtsps|udp|http|https)://\S+", "<url>", clean)
                    for private_value in (str(private), str(runtime), str(profile)):
                        clean = clean.replace(private_value, "<private>")
                    clean = clean.strip()[:160]
                    if clean:
                        server_lines.append(clean)
                evidence["fixtureServerLogTail"] = server_lines[-10:]
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
