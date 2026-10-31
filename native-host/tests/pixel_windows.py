#!/usr/bin/env python3
"""Synthetic final HWND pixels, not a startup/media-health/camera qualification.

A NEW non-redistributable PixelTest portable is mandatory. The only control is a
one-boot request plus five ordered acknowledgements below its fixed private
config directory. This runner never loads an existing scene or camera profile.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import socket
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "native-host/scripts"))
from prepare import OBS_COMMIT, obtain
from smoke_windows import fingerprint

PHASES = ("known-colors", "five-codecs", "studio-preview-no-take", "explicit-take", "program-reopened", "rtsp-loopback",
          "rtsp-recovered", "program-fullscreen")
ENV_OVERRIDES = ("OBS_PLUGINS_PATH", "OBS_PLUGINS_DATA_PATH", "OBS_CONFIG_PATH", "QT_PLUGIN_PATH",
                 "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH", "WEBOBS_NATIVE_SMOKE_TOKEN", "WEBOBS_NATIVE_PIXEL_TOKEN")


def read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Missing/unsafe/oversized finite test metadata")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Finite test metadata must be an object")
    return value


def write_new(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2)
        output.write("\n")


def validate_build(runtime: Path) -> dict:
    if runtime.is_symlink():
        raise ValueError("Pixel runtime must not be a symlink")
    marker = read_json(runtime / "webobs-native-pixel-test-build.json")
    manifest = read_json(runtime / "webobs-native-prototype.json")
    if (marker.get("pixelTestBuild") is not True or marker.get("redistributable") is not False or
            marker.get("publicationForbidden") is not True or manifest.get("obsCommit") != OBS_COMMIT or
            manifest.get("defaultProduct") is not False or manifest.get("obsVersion") != "32.1.2"):
        raise ValueError("PixelTest native build identity/non-publication marker mismatch")
    return manifest


def mark_build(runtime: Path) -> None:
    """Called once by the dedicated builder, before creating any test config."""
    manifest = validate_build(runtime)
    if (runtime / "config").exists() or "pixelTestBuild" in manifest:
        raise ValueError("Mark only a new staged test runtime, never an existing profile")
    manifest.update(pixelTestBuild=True, redistributable=False, publicationForbidden=True,
                    qualification="TEST BUILD ONLY: synthetic visible-window pixels; never redistribute or publish")
    # Existing manifest was read above. Atomic replacement is confined to the
    # freshly staged runtime supplied explicitly to this test-build command.
    target = runtime / "webobs-native-prototype.json"
    temporary = target.with_suffix(".pixel-test-new.json")
    write_new(temporary, manifest)
    temporary.replace(target)


def locked_ffmpeg(private: Path, offline: bool) -> tuple[Path, Path]:
    lock = read_json(ROOT / "desktop/dependencies.lock.json")
    artifacts = [a for a in lock["artifacts"] if a.get("id") == "ffmpeg"]
    if len(artifacts) != 1 or lock.get("obsCommit") != OBS_COMMIT:
        raise ValueError("Exactly one existing desktop-locked FFmpeg artifact is required")
    artifact = artifacts[0]
    if (not artifact["url"].startswith("https://github.com/BtbN/FFmpeg-Builds/releases/download/") or
            len(artifact["sha256"]) != 64):
        raise ValueError("Unapproved locked FFmpeg archive")
    archive = obtain(artifact, ROOT / "desktop/.cache", offline)
    tools = private / "fixture-tools"
    tools.mkdir()
    with zipfile.ZipFile(archive) as source:
        entries = [e for e in source.infolist() if e.filename.endswith("/bin/ffmpeg.exe")]
        if len(entries) != 1:
            raise ValueError("Locked FFmpeg archive has ambiguous binaries")
        prefix = str(PurePosixPath(entries[0].filename).parent) + "/"
        size = 0
        for entry in source.infolist():
            if not entry.filename.startswith(prefix) or entry.is_dir():
                continue
            relative = PurePosixPath(entry.filename[len(prefix):])
            if len(relative.parts) != 1 or relative.name in (".", "..") or ":" in relative.name or "\\" in relative.name:
                raise ValueError("Unsafe locked FFmpeg binary archive entry")
            if relative.suffix.lower() not in (".exe", ".dll"):
                continue
            size += entry.file_size
            if size > 1024 * 1024 * 1024 or entry.file_size > 512 * 1024 * 1024:
                raise ValueError("Oversized locked FFmpeg binary archive")
            with source.open(entry) as input_file, (tools / relative.name).open("xb") as output_file:
                shutil.copyfileobj(input_file, output_file)
    return tools / "ffmpeg.exe", tools / "ffprobe.exe"


def locked_mediamtx(private: Path, offline: bool) -> Path:
    lock = read_json(ROOT / "desktop/dependencies.lock.json")
    artifacts = [a for a in lock["artifacts"] if a.get("id") == "mediamtx"]
    if len(artifacts) != 1 or lock.get("obsCommit") != OBS_COMMIT:
        raise ValueError("Exactly one existing desktop-locked MediaMTX artifact is required")
    artifact = artifacts[0]
    if (not artifact["url"].startswith("https://github.com/bluenviron/mediamtx/releases/download/") or
            len(artifact["sha256"]) != 64):
        raise ValueError("Unapproved locked MediaMTX archive")
    archive = obtain(artifact, ROOT / "desktop/.cache", offline)
    tools = private / "fixture-tools"
    tools.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        entries = [e for e in source.infolist() if not e.is_dir() and e.filename.lower().endswith("mediamtx.exe")]
        if len(entries) != 1 or "/" in entries[0].filename:
            raise ValueError("Locked MediaMTX archive has ambiguous binary")
        target = tools / "mediamtx.exe"
        with source.open(entries[0]) as input_file, target.open("xb") as output_file:
            shutil.copyfileobj(input_file, output_file)
    return target


class LoopbackRtsp:
    """Five loopback RTSP publishers behind a fixed local MediaMTX instance.

    Only synthetic fixtures are published on 127.0.0.1; no real-camera,
    hardware-decode, camera-URL or OBS-parity qualification is claimed.
    """

    def __init__(self, private: Path, ffmpeg: Path, ffprobe: Path, fixtures: list[dict], token: str, offline: bool):
        self.private = private
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.fixtures = fixtures
        self.fixture_paths = [private / f"fixture-{index + 1}.mkv" for index in range(5)]
        self.urls: list[str] = []
        self.publishers: list[subprocess.Popen | None] = []
        self.server: subprocess.Popen | None = None
        self.log = (private / "rtsp-test.log").open("xb")
        try:
            mediamtx = locked_mediamtx(private, offline)
            eol = chr(10)
            config = private / "mediamtx.yml"
            config.write_text(eol.join(["logLevel: warn", "rtspAddress: 127.0.0.1:8554", "paths:", "  all_others:"]) + eol,
                              encoding="utf-8")
            self.server = subprocess.Popen([str(mediamtx), str(config)], cwd=private, stdin=subprocess.DEVNULL,
                                           stdout=self.log, stderr=subprocess.STDOUT)
            self._wait_port(time.monotonic() + 20)
            for index in range(5):
                self.urls.append(f"rtsp://127.0.0.1:8554/hybrid-{token}-{index + 1}")
                self._start_publisher(index)
            self._wait_streams(fixtures, ffprobe, time.monotonic() + 40)
        except Exception:
            self.stop()
            raise

    def _wait_port(self, deadline: float) -> None:
        while time.monotonic() < deadline:
            if self.server is not None and self.server.poll() is not None:
                raise RuntimeError("Loopback RTSP server exited before listening")
            try:
                with socket.create_connection(("127.0.0.1", 8554), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("Loopback RTSP server did not listen")

    def _wait_streams(self, fixtures: list[dict], ffprobe: Path, deadline: float) -> None:
        pending = set(range(5))
        while pending and time.monotonic() < deadline:
            for index in sorted(pending):
                publisher = self.publishers[index]
                if publisher.poll() is not None:
                    raise RuntimeError("Loopback RTSP publisher exited")
                try:
                    probe = subprocess.run(
                        [str(ffprobe), "-v", "error", "-rtsp_transport", "tcp", "-select_streams", "v:0",
                         "-show_entries", "stream=codec_name,width,height", "-of", "json", self.urls[index]],
                        capture_output=True, text=True, timeout=8)
                except subprocess.TimeoutExpired:
                    continue
                if probe.returncode != 0:
                    continue
                try:
                    streams = json.loads(probe.stdout)["streams"]
                except (ValueError, KeyError):
                    continue
                fixture = fixtures[index]
                if streams == [{"codec_name": fixture["codec"], "width": 320, "height": 180}]:
                    pending.discard(index)
            if pending:
                time.sleep(0.5)
        if pending:
            raise RuntimeError("Loopback RTSP streams did not become readable")

    def _publisher_command(self, index: int) -> list[str]:
        return [str(self.ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-re", "-stream_loop", "-1",
                "-i", str(self.fixture_paths[index]), "-c", "copy", "-f", "rtsp", "-rtsp_transport", "tcp",
                self.urls[index]]

    def _start_publisher(self, index: int) -> None:
        while len(self.publishers) <= index:
            self.publishers.append(None)
        self.publishers[index] = subprocess.Popen(self._publisher_command(index), cwd=self.private,
                                                  stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT)

    def interrupt_publisher(self, index: int) -> None:
        publisher = self.publishers[index]
        if publisher is not None and publisher.poll() is None:
            publisher.terminate()
            try:
                publisher.wait(timeout=10)
            except subprocess.TimeoutExpired:
                publisher.kill()
                publisher.wait(timeout=5)
        self.publishers[index] = None

    def restart_publisher(self, index: int) -> None:
        self._start_publisher(index)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            publisher = self.publishers[index]
            if publisher is None or publisher.poll() is not None:
                raise RuntimeError("Loopback RTSP publisher exited after restart")
            try:
                probe = subprocess.run(
                    [str(self.ffprobe), "-v", "error", "-rtsp_transport", "tcp", "-select_streams", "v:0",
                     "-show_entries", "stream=codec_name,width,height", "-of", "json", self.urls[index]],
                    capture_output=True, text=True, timeout=8)
            except subprocess.TimeoutExpired:
                continue
            if probe.returncode == 0:
                try:
                    streams = json.loads(probe.stdout)["streams"]
                except (ValueError, KeyError):
                    streams = []
                if streams == [{"codec_name": self.fixtures[index]["codec"], "width": 320, "height": 180}]:
                    return
            time.sleep(0.5)
        raise RuntimeError("Loopback RTSP stream did not return after restart")

    def stop(self) -> None:
        for publisher in self.publishers:
            if publisher is not None and publisher.poll() is None:
                publisher.terminate()
                try:
                    publisher.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    publisher.kill()
                    publisher.wait(timeout=5)
        self.publishers = []
        if self.server is not None and self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=5)
        self.server = None
        if not self.log.closed:
            self.log.close()


def make_fixtures(private: Path, ffmpeg: Path, ffprobe: Path, node: str) -> list[dict]:
    """All encoders exit here, BEFORE OBS launches; no dummy recording/output."""
    fixtures = []
    for channel in range(5):
        raw, video = private / f"fixture-{channel + 1}.rgb", private / f"fixture-{channel + 1}.mkv"
        subprocess.run([node, str(HERE / "pixel-pattern.cjs"), "fixture", str(channel), str(raw)], check=True, capture_output=True, timeout=30)
        # Two of the five independent fixtures are H.264 so the local decode
        # path is not only HEVC; both codecs stay 320x180/10fps/B0 lossy yuv420p.
        codec = "h264" if channel >= 3 else "hevc"
        if codec == "h264":
            video_args = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                          "-x264-params", "keyint=10:min-keyint=10:scenecut=0:bframes=0:log-level=error"]
        else:
            video_args = ["-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                          "-x265-params", "pools=1:frame-threads=1:keyint=10:min-keyint=10:scenecut=0:bframes=0:log-level=error"]
        command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-f", "rawvideo",
                   "-pixel_format", "rgb24", "-video_size", "320x180", "-framerate", "10", "-i", str(raw),
                   "-an", *video_args, "-f", "matroska", str(video)]
        subprocess.run(command, check=True, capture_output=True, timeout=90)
        probe = subprocess.run([str(ffprobe), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,width,height",
                                "-of", "json", str(video)], check=True, capture_output=True, text=True, timeout=20)
        streams = json.loads(probe.stdout)["streams"]
        if streams != [{"codec_name": codec, "width": 320, "height": 180}]:
            raise AssertionError(f"Local fixture is not independently encoded 320x180 {codec}")
        fixtures.append({"channel": channel + 1, "codec": codec, "width": 320, "height": 180,
                         "sha256": hashlib.sha256(video.read_bytes()).hexdigest()})
        # Raw targets are exact files just created by this function under the
        # caller's new fixed private directory, never a computed user path.
        if raw.resolve().parent != private.resolve() or raw.name != f"fixture-{channel + 1}.rgb":
            raise AssertionError("Raw synthetic fixture cleanup path escaped")
        raw.unlink()
    if len({fixture["sha256"] for fixture in fixtures}) != 5:
        raise AssertionError("Five independent fixture files are required")
    return fixtures


def creation_time(process: subprocess.Popen) -> str:
    from ctypes import wintypes
    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(FileTime)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    created, exited, kernel_time, user_time = FileTime(), FileTime(), FileTime(), FileTime()
    if not kernel.GetProcessTimes(int(process._handle), ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel_time), ctypes.byref(user_time)):
        raise ctypes.WinError(ctypes.get_last_error())
    return str((created.high << 32) | created.low)


def validate_state(state: dict, seq: int, token: str, pid: int) -> None:
    if (state.get("schema") != 1 or state.get("seq") != seq or state.get("phase") != PHASES[seq - 1] or
            state.get("token") != token or state.get("pid") != str(pid) or state.get("scope") != "synthetic-test-only" or
            state.get("canvasWidth") != 960 or state.get("canvasHeight") != 540 or state.get("pixelQualified") is not False):
        raise AssertionError("Finite native phase/process/synthetic identity mismatch")
    for key in ("activeOutputs", "activeEncoders"):
        if state.get(key) != 0:
            raise AssertionError("An OBS output/encoder was active during the pixel test")
    if seq >= 2 and state.get("wallReuseVerified") is not True:
        raise AssertionError("native payload wall reuse was not verified")
    if seq >= 6 and state.get("productBootstrapVerified") is not True:
        raise AssertionError("product camera bootstrap path was not verified")
    if state.get("rawVideoActive") is not False or state.get("sameInputPointersAndSettings") is not True:
        raise AssertionError("Unexpected raw consumer or input mutation")
    expected_ffmpeg = 0 if seq == 1 else 10 if seq >= 6 else 5
    if state.get("globalFfmpegInputsIncludingPrivate") != expected_ffmpeg:
        raise AssertionError("Duplicate/missing global Media Source (including private Studio inputs)")
    if state.get("studio") is not (3 <= seq <= 5) or (4 <= seq <= 5 and state.get("transitionStopped") is not True):
        raise AssertionError("Studio/TAKE state mismatch")
    windows = state.get("windows", [])
    if seq == 8:
        expected_roles = {"main-preview", "program-fullscreen"}
    elif seq >= 6:
        expected_roles = {"main-preview"}
    else:
        expected_roles = {"main-preview", "program-projector"}
    if len(windows) != len(expected_roles) or {w.get("role") for w in windows} != expected_roles:
        raise AssertionError("Only exact real main Preview and native Program clients are accepted")
    for window in windows:
        expected_class = "OBSBasicPreview" if window["role"] == "main-preview" else "OBSProjector"
        if window.get("qtClass") != expected_class:
            raise AssertionError("Qt native widget identity mismatch")
    if state.get("programGeneration") != (2 if seq >= 5 else 1):
        raise AssertionError("Program projector close/reopen generation mismatch")
    if seq > 1:
        sources = state.get("sources", [])
        if len(sources) != 5 or len({s.get("uuid") for s in sources}) != 5:
            raise AssertionError("Five distinct retained source UUIDs are required")


# The public receipt deliberately carries no PowerShell exception text, paths,
# process identity, token or HWND. Even valid JSON from the private subprocess is
# projected onto this finite schema, never copied into the artifact verbatim.
CAPTURE_ROLES = ("main-preview", "program-projector", "program-fullscreen")
CAPTURE_CODES = {
    "input": {"input-validation", "windows-required", "output-directory", "state-size", "state-identity", "state-roles", "window-state", "native-arguments"},
    "assembly-load": {"reference-assemblies"}, "compile": {"csharp-compilation"},
    "role-directory": {"role-directory"}, "identity": {"process-inspection", "process-identity", "window-identity"},
    "dpi": {"dpi-awareness"}, "expose": {"interactive-screen", "main-preview-expose", "program-projector-expose",
                                        "fullscreen-projector-expose"},
    "visibility": {"client-hidden"}, "geometry": {"client-geometry", "client-bounds"},
    "occlusion": {"client-obscured"}, "dwm": {"composition-sync"}, "copy": {"screen-copy"},
    "write": {"bitmap-write"}, "subprocess": {"timeout", "launch-failed", "invalid-report", "no-report"},
}


def _integer(value, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _safe_diagnostic(value: dict) -> dict:
    if not isinstance(value, dict) or value.get("code") not in CAPTURE_CODES.get(value.get("stage"), set()):
        raise ValueError("Unexpected capture diagnostic classification")
    result = {"stage": value["stage"], "code": value["code"]}
    for name, low, high in (("sampleIndex", -1, 7), ("completedSamples", 0, 8), ("nativeError", -(2**31), 2**31-1)):
        number = value.get(name, low if name == "sampleIndex" else 0)
        if not _integer(number, low, high):
            raise ValueError("Unexpected capture diagnostic progress")
        result[name] = number
    codes = value.get("compilerCodes", [])
    if not isinstance(codes, list) or len(codes) > 8 or any(not isinstance(code, str) or not re.fullmatch(r"CS[0-9]{4}", code) for code in codes):
        raise ValueError("Unexpected capture compiler diagnostic")
    result["compilerCodes"] = sorted(set(codes))
    return result


def capture_failure(code: str, *, exit_code: int | None = None, stderr: str = "") -> dict:
    diagnostic = _safe_diagnostic({"stage": "subprocess", "code": code,
                                   "compilerCodes": sorted(set(re.findall(r"\bCS[0-9]{4}\b", stderr[:65536])))[:8]})
    result = {"schema": 1, "captureFailed": True, "diagnostic": diagnostic, "captures": []}
    if _integer(exit_code, -(2**31), 2**32-1):
        result["processExitCode"] = exit_code
    return result


def capture_report(completed: subprocess.CompletedProcess) -> dict:
    """Fail closed and retain bounded categories, including failure before BMP 0."""
    try:
        if len(completed.stdout) > 32768:
            raise ValueError("Oversized capture report")
        value = json.loads(completed.stdout)
        if not isinstance(value, dict) or value.get("schema") != 1 or type(value.get("captureFailed")) is not bool:
            raise ValueError("Invalid capture report")
        captures = value.get("captures")
        if not isinstance(captures, list) or len(captures) > 2:
            raise ValueError("Unexpected capture roles")
        result = {"schema": 1, "captureFailed": value["captureFailed"], "captures": []}
        seen = set()
        for role in captures:
            if not isinstance(role, dict) or role.get("role") not in CAPTURE_ROLES or role["role"] in seen:
                raise ValueError("Unexpected capture role")
            seen.add(role["role"])
            if type(role.get("captureFailed")) is not bool or not _integer(role.get("sampleCount"), 0, 8):
                raise ValueError("Invalid capture sample progress")
            count, elapsed = role["sampleCount"], role.get("sampleElapsedMs")
            if not isinstance(elapsed, list) or len(elapsed) != count or any(not _integer(ms, 0, 45000) for ms in elapsed) or elapsed != sorted(elapsed):
                raise ValueError("Invalid capture sample timing")
            if not role["captureFailed"] and count != 8:
                raise ValueError("Incomplete role cannot pass capture")
            safe = {"role": role["role"], "captureFailed": role["captureFailed"], "sampleCount": count, "sampleElapsedMs": elapsed}
            if role["captureFailed"]:
                safe["diagnostic"] = _safe_diagnostic(role.get("diagnostic"))
            result["captures"].append(safe)
        if "diagnostic" in value:
            result["diagnostic"] = _safe_diagnostic(value["diagnostic"])
        if value["captureFailed"]:
            if completed.returncode == 0 or not ("diagnostic" in result or any(role["captureFailed"] for role in result["captures"])):
                raise ValueError("Inconsistent failed capture report")
        elif completed.returncode != 0 or not seen or not seen <= set(CAPTURE_ROLES) or any(role["captureFailed"] for role in result["captures"]):
            raise ValueError("Inconsistent passing capture report")
        result["processExitCode"] = completed.returncode
        return result
    except (ValueError, TypeError, AttributeError):
        # Parser/parameter/host failures can happen before our PS try/catch. Keep
        # only a numeric compiler code, never raw stdout/stderr or ErrorRecord.
        return capture_failure("invalid-report" if completed.stdout.strip() else "no-report",
                               exit_code=completed.returncode, stderr=completed.stderr)


def run_capture(command: list[str], timeout: float) -> dict:
    try:
        return capture_report(subprocess.run(command, capture_output=True, text=True, timeout=timeout))
    except subprocess.TimeoutExpired:
        return capture_failure("timeout")
    except OSError:
        return capture_failure("launch-failed")


def wait_state(private: Path, seq: int, process: subprocess.Popen, deadline: float) -> dict:
    target = private / f"phase-{seq:02}.json"
    while time.monotonic() < deadline:
        if (private / "failed.json").exists():
            failure = read_json(private / "failed.json")
            raise RuntimeError("Native finite harness failed: " + str(failure.get("error", "unknown"))[:200])
        if target.exists():
            return read_json(target)
        if process.poll() is not None:
            raise RuntimeError("Owned OBS exited before the next finite phase")
        time.sleep(0.1)
    raise TimeoutError("Owned native pixel test deadline exceeded")


def run(runtime: Path, result: Path, ffmpeg_override: Path | None, offline: bool) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("Actual HWND/DWM final pixels require Windows x64")
    manifest = validate_build(runtime)
    if manifest.get("pixelTestBuild") is not True or manifest.get("redistributable") is not False:
        raise ValueError("Use the explicit marked PixelTest build, never the ordinary prototype")
    if (runtime / "config").exists() or result.exists():
        raise ValueError("Use a NEW disposable runtime and result; preserve all existing profiles")
    pwsh, node = shutil.which("pwsh"), shutil.which("node")
    if not pwsh or not node:
        raise RuntimeError("PowerShell 7.2+ and Node are required test tools")
    executable = runtime / "bin/64bit/obs64.exe"
    if not executable.is_file() or executable.is_symlink() or not (runtime / "portable_mode.txt").is_file():
        raise ValueError("Incomplete separate portable OBS test runtime")
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise ValueError("APPDATA is required for external profile isolation verification")
    external = Path(appdata) / "obs-studio"
    before = fingerprint(external)
    private = runtime / "config/obs-studio/native-pixel-test"
    private.mkdir(parents=True)
    (private.parent / "user.ini").write_text("[General]\nFirstRun=true\n[BasicWindow]\nSysTrayEnabled=false\nSceneDuplicationMode=true\nSwapScenesMode=true\nEditPropertiesMode=false\nPreviewProgramMode=false\n", encoding="utf-8")
    token = secrets.token_hex(16)
    summary = {"schema": 1, "status": "failed", "syntheticOnly": True, "obsCommit": OBS_COMMIT,
               "realCameraQualified": False, "rtspQualified": False, "performanceP2Qualified": False,
               "productMigrationQualified": False, "mediaHardwareQualified": False,
               "publicationForbidden": True, "phases": []}
    process = None
    rtsp = None
    error = None
    try:
        ffmpeg, ffprobe = ((ffmpeg_override, ffmpeg_override.with_name("ffprobe.exe")) if ffmpeg_override else locked_ffmpeg(private, offline))
        (private / "fixture-tools").mkdir(exist_ok=True)
        fixtures = make_fixtures(private, ffmpeg, ffprobe, node)
        summary["fixtures"] = fixtures
        summary["fixtureEncodingStoppedBeforeObs"] = True
        rtsp = LoopbackRtsp(private, ffmpeg, ffprobe, fixtures, token, offline)
        summary["rtspSources"] = 5
        write_new(private / "request.json", {"schema": 1, "token": token, "rtsp": rtsp.urls})
        env = os.environ.copy()
        for key in ENV_OVERRIDES:
            env.pop(key, None)
        env["WEBOBS_NATIVE_PIXEL_TOKEN"] = token
        with (private / "private-process.log").open("xb") as log:
            process = subprocess.Popen([str(executable), "--portable", "--disable-updater"], cwd=executable.parent,
                                       env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            created = creation_time(process)
            deadline = time.monotonic() + 260
            original_sources = None
            with tempfile.TemporaryDirectory(prefix="webobs-synthetic-client-") as temporary:
                captures = Path(temporary)
                for seq in range(1, 9):
                    state = wait_state(private, seq, process, deadline)
                    validate_state(state, seq, token, process.pid)
                    if 2 <= seq <= 5:
                        if original_sources is None:
                            original_sources = state["sources"]
                        elif state["sources"] != original_sources:
                            raise AssertionError("Retained UUID/settings identities changed across Studio/TAKE/reopen")
                    phase_capture = captures / f"phase-{seq:02}"
                    phase_capture.mkdir()
                    command = [pwsh, "-NoProfile", "-File", str(HERE / "capture-pixels.ps1"),
                               "-ExpectedProcessId", str(process.pid), "-ExpectedExecutable", str(executable),
                               "-ExpectedCreationTime", created, "-StateFile", str(private / f"phase-{seq:02}.json"),
                               "-OutputDirectory", str(phase_capture)]
                    timing = run_capture(command, timeout=min(45, max(1, int(deadline-time.monotonic()))))
                    phase = {"seq": seq, "phase": PHASES[seq - 1], "capture": timing, "roles": [],
                             "globalFfmpegInputsIncludingPrivate": state["globalFfmpegInputsIncludingPrivate"],
                             "activeOutputs": state["activeOutputs"], "activeEncoders": state["activeEncoders"],
                             "inputUUIDsAndSettingsUnchanged": True, "programGeneration": state["programGeneration"]}
                    # Analyze every one of the eight files, including earlier bad
                    # samples and missing captures; never retry away a black frame.
                    for window in state["windows"]:
                        role = window["role"]
                        reverse = (seq == 3 and role == "main-preview") or (seq in (4, 5) and role == "program-projector")
                        analysis = subprocess.run([node, str(HERE / "pixel-pattern.cjs"), "analyze", str(phase_capture / role), role,
                                                   "reverse" if reverse else "forward", "false" if seq == 1 else "true"],
                                                  capture_output=True, text=True, check=True, timeout=20)
                        phase["roles"].append({"role": role, **json.loads(analysis.stdout)})
                    phase["passed"] = not timing["captureFailed"] and all(role["passed"] for role in phase["roles"])
                    summary["phases"].append(phase)
                    write_new(private / f"ack-{seq:02}.json", {"schema": 1, "seq": seq, "token": token})
                    if seq == 6:
                        # Only our own synthetic publisher: interrupt one stream,
                        # keep the source, then let OBS reconnect.
                        rtsp.interrupt_publisher(0)
                        time.sleep(20)
                        rtsp.restart_publisher(0)
                process.wait(timeout=max(1, min(30, int(deadline-time.monotonic()))))
                if process.returncode != 0 or read_json(private / "complete.json").get("phases") != 8:
                    raise RuntimeError("Native frontend normal close/finite completion failed")
                summary["normalExit"] = True
                summary["loopbackRtspPhaseQualified"] = bool(len(summary["phases"]) >= 6 and summary["phases"][5]["passed"])
                summary["rtspRecoveryPhaseQualified"] = bool(len(summary["phases"]) >= 7 and summary["phases"][6]["passed"])
                summary["programFullscreenPhaseQualified"] = bool(len(summary["phases"]) >= 8 and summary["phases"][7]["passed"])
            summary["status"] = "passed" if all(phase["passed"] for phase in summary["phases"]) else "failed"
            summary["syntheticFinalWindowPixelsQualified"] = summary["status"] == "passed"
    except Exception as failure:
        # Do not print subprocess stderr, source settings, paths or private logs.
        # Fixed harness exceptions contain no camera names/URLs/desktop pixels.
        error = failure
        summary["errorType"] = type(failure).__name__
        try:
            failed = private / "failed.json"
            if failed.exists():
                summary["harnessFailure"] = str(read_json(failed).get("error", ""))[:300]
        except Exception:
            pass
    finally:
        if process is not None and process.poll() is None:
            process.kill()  # Only this Popen-owned, new disposable obs64 instance.
            process.wait(timeout=15)
            summary["deadlineOrFailureOwnedProcessKilled"] = True
        if rtsp is not None:
            rtsp.stop()
            summary["loopbackRtspStopped"] = True
        unchanged = fingerprint(external) == before
        summary["externalObsProfileUnchanged"] = unchanged
        if not unchanged:
            summary["status"] = "failed"
            summary["isolationFailed"] = True
        summary["syntheticFinalWindowPixelsQualified"] = summary["status"] == "passed" and unchanged
        write_new(result, summary)
    print(json.dumps(summary, indent=2))
    if error or summary["status"] != "passed":
        raise RuntimeError("Synthetic native final-window pixel gate failed; inspect the small receipt and only this disposable runtime privately") from None
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--ffmpeg", type=Path, help="Explicit test-tool override; otherwise use the existing SHA-256 desktop lock")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--mark-build", action="store_true", help="Mark a fresh staged PixelTest runtime non-redistributable; does not run OBS")
    args = parser.parse_args()
    if args.mark_build:
        mark_build(args.runtime.resolve())
    elif args.result:
        run(args.runtime.resolve(), args.result.resolve(), args.ffmpeg.resolve() if args.ffmpeg else None, args.offline)
    else:
        parser.error("--result is required unless --mark-build is used")
