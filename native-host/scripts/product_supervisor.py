"""Own the account/control services and single OBS product host.

Packaged at runtime/services/product/supervisor.py. The native launcher assigns
this process to its kill-on-close Windows Job before Python can spawn children.
"""
from __future__ import annotations

import contextlib
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import tempfile
import time
import traceback
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def clean_environment(environment):
    blocked = ("WEBOBS_", "MTX_", "GO2RTC_", "PYTHON", "QT_", "QML", "OBS_", "NODE_", "CSC_")
    secrets_and_proxies = {"GH_TOKEN", "GITHUB_TOKEN", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}
    return {key: value for key, value in environment.items()
            if not key.upper().startswith(blocked) and key.upper() not in secrets_and_proxies
            and key.upper() != "PATH"}


def unique_configuration(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("native network configuration contains duplicate fields")
        value[key] = item
    return value


def delivery_profile(manifest):
    # Embedded Python intentionally omits the script directory from sys.path.
    specification = importlib.util.spec_from_file_location("native_release_policy", Path(__file__).with_name("release_policy.py"))
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module.delivery(manifest)


def protect(root, runtime):
    for path in (root, *root.parents):
        if path.is_symlink():
            raise ValueError("product data root must not contain links")
    path = runtime / "services/desktop-tools/private_directory.py"
    specification = importlib.util.spec_from_file_location("native_product_private_directory", path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    module.protect(root)


class AuthorityServer(ThreadingHTTPServer):
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(12)
        return connection, address


def lan_contract():
    """Load the LAN entry contract that ships beside the supervisor."""
    for name in ("lan.py", "product_lan.py"):
        path = Path(__file__).with_name(name)
        if path.is_file() and not path.is_symlink():
            specification = importlib.util.spec_from_file_location("native_product_lan", path)
            module = importlib.util.module_from_spec(specification)
            specification.loader.exec_module(module)
            return module
    raise ValueError("the LAN entry contract must ship beside the supervisor")


class LanControlServer(ThreadingHTTPServer):
    """Loopback-only LAN switch for the native product window.

    The single product host owns the user-facing controls; the switch persists
    the setting and the main supervisor loop re-applies it, because the control
    server reads its allowed origins when it starts.
    """
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, supervisor):
        super().__init__(("127.0.0.1", 0), LanControlHandler)
        self.supervisor = supervisor

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address


class LanControlHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: LanControlServer

    def _reply(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        supplied = self.headers.get("X-WebOBS-Native-Token", "")
        expected = self.server.supervisor.token
        return bool(expected) and secrets.compare_digest(supplied, expected)

    def do_GET(self):  # noqa: N802 - http.server naming
        if self.path != "/lan":
            return self._reply(404, {"error": "not-found"})
        if not self._authorized():
            return self._reply(401, {"error": "unauthorized"})
        return self._reply(200, self.server.supervisor.lan_status())

    def do_POST(self):  # noqa: N802 - http.server naming
        if self.path != "/lan":
            return self._reply(404, {"error": "not-found"})
        if not self._authorized():
            return self._reply(401, {"error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._reply(400, {"error": "bad-request"})
        if length <= 0 or length > 4096:
            return self._reply(400, {"error": "bad-request"})
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return self._reply(400, {"error": "bad-request"})
        if not isinstance(body, dict) or set(body) != {"enabled", "port"}:
            return self._reply(400, {"error": "bad-request"})
        try:
            result = self.server.supervisor.request_lan(body["enabled"], body["port"])
        except ValueError:
            return self._reply(400, {"error": "invalid-setting"})
        return self._reply(200, result)

    def log_message(self, *_args):
        # The private supervisor log already carries lifecycle events; a LAN
        # switch request carries no useful access line and must not echo tokens.
        return


class ProductSupervisor:
    def __init__(self, runtime, root):
        self.runtime = Path(runtime).resolve(strict=True)
        self.root = Path(root).absolute()
        self.children = []
        self.stop_requested = threading.Event()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.resources = contextlib.ExitStack()
        self.origin = ""
        self.boot_id = secrets.token_hex(16)
        self.failure_reason = ""
        self.owns_profile = False
        self.authority_servers = []
        self.authority_threads = []
        self.authority_store = None
        self.lan = lan_contract()
        self.lan_value = self.lan.plan({"enabled": False, "port": self.lan.DEFAULT_PORT}, [], 0, self.root)
        self.lan_server = None
        self.lan_thread = None
        self.token = ""
        self.phase = "startup"
        self.status_lock = threading.Lock()
        self.lan_lock = threading.Lock()
        self.lan_dirty = threading.Event()
        self.lan_process = None
        self.lan_lease = None
        self.lan_config = None
        self.lan_control_port = 0
        self.token = secrets.token_hex(32)
        self.complete = False
        self.recordings = None
        self.backup_key = None

    def status(self, phase):
        self.phase = phase
        value = {"schema": 1, "phase": phase, "origin": self.origin, "bootId": self.boot_id,
                 "failureReason": self.failure_reason,
                 "ownerPid": os.getpid(), "services": [
                     {"name": name, "pid": process.pid, "running": (code := process.poll()) is None,
                      "exitCode": code}
                     for name, process in self.children],
                 "lan": self.lan_status(),
                 "lanSwitchPort": self.lan_server.server_port if self.lan_server else 0}
        if self.authority_store is not None:
            value["services"].append({"name": "accounts-and-registry", "pid": os.getpid(),
                                       "running": all(thread.is_alive() for thread in self.authority_threads)})
        target = self.root / "run/native-status.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".new")
        # A LAN toggle is answered on the switch thread while the supervisor loop
        # keeps publishing phases, so the publish must stay serialized.
        with self.status_lock:
            with temporary.open("w", encoding="utf-8") as output:
                json.dump(value, output)
            temporary.replace(target)

    def recover_interrupted_restore(self):
        """Converge a half restore while still holding the exclusive data lock.

        A restore swaps ``config`` and ``native-profile`` as one pair. If that
        process was killed between the two swaps, this ordinary product start is
        the first place that can finish or undo the pair, so it must run before
        any directory is created and before the configuration or OBS profile is
        read; otherwise the control server and OBS would start on mismatched
        halves. Previous data is never deleted here, and an unreadable journal
        fails closed with a bounded reason instead of silently continuing.
        """
        backup = self.runtime / "services/backup/encrypted_backup.py"
        if not backup.is_file() or backup.is_symlink():
            return None
        specification = importlib.util.spec_from_file_location("interrupted_restore_recovery", backup)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        journal = self.root / module.JOURNAL_NAME
        marker = self.root / "run/restore-recovery.json"
        try:
            outcome = module.recover_interrupted(journal)
        except Exception as error:
            reason = str(error)[:200]
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({"schema": 1, "state": "unresolved", "reason": reason},
                indent=2) + "\n", encoding="utf-8")
            raise ValueError(f"interrupted restore needs repair: run the product backup "
                f"recover action before starting ({reason})") from error
        if outcome:
            marker.unlink(missing_ok=True)
            print(f"converged the interrupted restore as {outcome}", flush=True)
        return outcome

    def prepare(self):
        manifest = self.runtime / "webobs-native-prototype.json"
        value = json.loads(manifest.read_text(encoding="utf-8"))
        self.preview = delivery_profile(value) == "native-monitor-preview"
        self.version = value["version"]
        if (value.get("obsCommit") != "fb4d98bf88fae5fc85cb11fc57f7c5e309282194"
                or value.get("productIntegration") is not True):
            raise ValueError("this supervisor requires the internal integrated product build")
        complete_markers = ("services/events/event_service.py", "services/nvr/nvr_service.py",
                            "services/v2/client_control_service.py", "bin/go2rtc.exe",
                            "bin/node.exe", "bin/webobs-online-source.exe")
        self.complete = all((self.runtime / marker).is_file() for marker in complete_markers)
        for directory in (self.root, self.root / "run"):
            for path in (directory, *directory.parents):
                if path.is_symlink() or (path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
                    raise ValueError("product data root must not contain links")
            directory.mkdir(parents=True, exist_ok=True)
        owner = self.resources.enter_context((self.root / "run/native-owner.lock").open("a+b"))
        owner.seek(0)
        if owner.read(1) == b"":
            owner.write(b"\0")
            owner.flush()
        owner.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(owner.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        self.owns_profile = True
        protect(self.root, self.runtime)
        self.recover_interrupted_restore()
        directories = ["config", "logs", "native-profile/obs-studio"]
        if self.complete:
            directories += ["recordings", "backups", "snapshots", "config/go2rtc", "config/keys",
                            "config/node", "config/secrets", "config/notification-secrets",
                            "config/camera-secrets", "run"]
        for name in directories:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        pending_update = self.root / "run/pending-update.json"
        if pending_update.is_file() and not pending_update.is_symlink() and pending_update.stat().st_size <= 65536:
            try:
                update = json.loads(pending_update.read_text(encoding="utf-8"))
                if isinstance(update, dict) and update.get("to") == self.version:
                    (self.root / "run/installed-version.json").write_text(json.dumps({
                        "schema": 1, "version": self.version, "previous": update.get("from"),
                        "installerSha512": update.get("sha512")}, indent=2) + "\n", encoding="utf-8")
                    pending_update.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass
        ini = self.root / "native-profile/obs-studio/user.ini"
        if not ini.exists():
            with ini.open("x", encoding="utf-8") as output:
                output.write("[General]\nFirstRun=true\n[BasicWindow]\nSysTrayEnabled=false\n")
        protect(self.root / "config", self.runtime)
        protect(self.root / "native-profile", self.runtime)
        if self.complete:
            updater_path = self.runtime / "services/product/native_updater.py"
            if updater_path.is_file() and not updater_path.is_symlink():
                specification = importlib.util.spec_from_file_location("native_maintenance_cleanup", updater_path)
                updater_module = importlib.util.module_from_spec(specification)
                specification.loader.exec_module(updater_module)
                updater_module.cleanup_maintenance(self.root)
            for name in ("recordings", "backups"):
                protect(self.root / name, self.runtime)
            key_path = self.root / "run/backup.key"
            migrated_key = self.root / "config/backup.key"
            if not key_path.exists() and migrated_key.is_file() and not migrated_key.is_symlink():
                shutil.copy2(migrated_key, key_path)
            if not key_path.exists():
                with key_path.open("xb") as output:
                    output.write(secrets.token_bytes(32))
                    output.flush()
                    os.fsync(output.fileno())
            if key_path.is_symlink() or key_path.stat().st_size != 32:
                raise ValueError("product backup key must be a private 32-byte file")
            if os.name != "nt":
                key_path.chmod(0o600)
        self.environment = clean_environment(os.environ)
        system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        self.environment["PATH"] = os.pathsep.join(map(str, (
            self.runtime / "bin", self.runtime / "bin/64bit", system)))
        config = self.root / "config"
        self.environment.update({
            "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "WEBOBS_OWNER_STDIN": "true",
            "WEBOBS_DESKTOP_OWNER_PID": str(os.getppid()),
            "WEBOBS_LISTEN_ADDRESS": "127.0.0.1", "WEBOBS_ALLOW_INSECURE_REMOTE": "false",
            "WEBOBS_COMPAT_BASIC_AUTH": "false", "WEBOBS_SESSION_COOKIE_SECURE": "false",
            "WEBOBS_SESSION_DATABASE": str(config / "auth-sessions.db"),
            "WEBOBS_CLUSTER_DATABASE": str(config / "cluster.sqlite3"),
            "WEBOBS_CAMERA_DATABASE": str(config / "cameras.db"),
            "WEBOBS_CAMERA_SECRET_ROOT": str(config / "camera-secrets"),
            "WEBOBS_CAMERA_SECRET_WRITE_ROOT": str(config / "camera-secrets"),
            "WEBOBS_SCENE_FILE": str(config / "scene.json"), "WEBOBS_STUDIO_FILE": str(config / "studio.json"),
            "WEBOBS_WEB_ROOT": str(self.runtime / "web"),
            "WEBOBS_OBS_PREFIX": str(self.runtime),
            "WEBOBS_LIBSODIUM_LIBRARY": str(self.runtime / "bin/libsodium.dll"),
            "WEBOBS_CLUSTER_INTERNAL_TOKEN": secrets.token_hex(32),
            "WEBOBS_NATIVE_HOST_TOKEN": self.token,
            "WEBOBS_NATIVE_PREVIEW": "true" if self.preview else "false",
            "WEBOBS_NATIVE_BOOT_ID": self.boot_id,
            "WEBOBS_WEBRTC_ENABLED": "true", "WEBOBS_COMPOSITE_ENABLED": "false",
            "WEBOBS_NVR_ENABLED": "false", "WEBOBS_GO2RTC_ENABLED": "false",
            "WEBOBS_CAMERA_BACKGROUND_PROBES": "false", "WEBOBS_CAMERA_BACKGROUND_EVENTS": "false",
            "WEBOBS_WHIP_URL": "http://127.0.0.1:9/native-unused/whip",
            "WEBOBS_NODE_ROLE": "standalone",
        })
        if self.complete:
            migration = config / "native-migration.json"
            migrated_recording = None
            if migration.is_file() and not migration.is_symlink() and migration.stat().st_size <= 65536:
                try:
                    value = json.loads(migration.read_text(encoding="utf-8"))
                    candidate = value.get("recordingsPath") if isinstance(value, dict) else None
                    if isinstance(candidate, str) and candidate and Path(candidate).is_absolute():
                        migrated_recording = Path(candidate)
                except (OSError, ValueError):
                    migrated_recording = None
            if os.environ.get("WEBOBS_PRODUCT_TEST_ROOT"):
                self.recordings = self.root / "recordings"
            else:
                self.recordings = migrated_recording or (
                    Path(os.environ.get("USERPROFILE", str(self.root))) / "Videos" / "WebOBS")
            self.recordings.mkdir(parents=True, exist_ok=True)
            self.program_recordings = self.recordings / "program"
            self.program_recordings.mkdir(parents=True, exist_ok=True)
            detector_model = self.runtime / "web/models/ssd_mobilenet_v1_12.onnx"
            self.environment.update({
                "WEBOBS_EVENT_DATABASE": str(config / "events.db"),
                "WEBOBS_V2_DATABASE": str(config / "v2-clients.db"),
                "WEBOBS_V2_SHARED_SCENES": str(config / "shared-scenes-v2.json"),
                "WEBOBS_V2_SIGNING_KEY": str(config / "keys/client-grant-signing.key"),
                "WEBOBS_SECRETS_ROOT": str(config / "secrets"),
                "WEBOBS_NOTIFICATION_SECRET_ROOT": str(config / "notification-secrets"),
                "WEBOBS_V2_INTERNAL_TOKEN": secrets.token_hex(32),
                "WEBOBS_NVR_CONFIG": str(config / "nvr.json"),
                "WEBOBS_NVR_STORAGE": str(self.recordings),
                "WEBOBS_NVR_DATABASE": str(self.recordings / "catalog.sqlite3"),
                "WEBOBS_NVR_CATALOG": str(self.recordings / "catalog.sqlite3"),
                "WEBOBS_NVR_VOLUMES_ROOT": str(self.recordings / "volumes"),
                "WEBOBS_NVR_STORAGE_ROOT": str(self.recordings),
                "WEBOBS_ARCHIVE_CONFIG": str(config / "archive.json"),
                "WEBOBS_ARCHIVE_QUEUE": str(config / "archive-queue.sqlite3"),
                "WEBOBS_ARCHIVE_PYTHON_MODULE": str(self.runtime / "services/archive/s3_archive.py"),
                "WEBOBS_BACKUP_CONFIG_ROOT": str(config),
                "WEBOBS_BACKUP_NATIVE_PROFILE": str(self.root / "native-profile"),
                "WEBOBS_BACKUP_ROOT": str(self.root / "backups"),
                "WEBOBS_BACKUP_KEY_FILE": str(self.root / "run/backup.key"),
                "WEBOBS_BACKUP_S3_CONFIG": str(config / "archive.json"),
                "WEBOBS_RESTORE_CONFIRM": "replace-config",
                "WEBOBS_GO2RTC_CONFIG": str(config / "go2rtc/go2rtc.yaml"),
                "WEBOBS_GO2RTC_TEMPLATE": str(self.runtime / "etc/go2rtc.yaml"),
                "WEBOBS_GO2RTC_WEB_ROOT": str(self.runtime / "go2rtc-www"),
                "WEBOBS_GO2RTC_WEBRTC_BIND": "127.0.0.1",
                "WEBOBS_ONLINE_SOURCES_ENABLED": "true",
                "WEBOBS_FFMPEG_PATH": str(self.runtime / "bin/ffmpeg.exe"),
                "WEBOBS_FFPROBE_PATH": str(self.runtime / "bin/ffprobe.exe"),
                "WEBOBS_NODE_PATH": str(self.runtime / "bin/node.exe"),
                "WEBOBS_TRANSCODER_PATH": str(self.runtime / "bin/webobs-transcoder.exe"),
                "WEBOBS_DETECTOR_PYTHON_MODULE": str(self.runtime / "services/analytics/detector_worker.py"),
                "WEBOBS_CAMERA_BACKGROUND_PROBES": "true",
                "WEBOBS_NVR_ENABLED": "true", "WEBOBS_GO2RTC_ENABLED": "true",
                # Direct-only stays authoritative in webobsd: composite_enabled
                # would switch the control server into the full OBS engine path
                # (obs_startup, x264/WHIP outputs) and it exits during native
                # startup. The native host owns Program recording/WHIP with a
                # private MediaMTX on demand, so the core keeps advertising
                # composite as disabled until its proxy can read that real state.
                "WEBOBS_COMPOSITE_ENABLED": "false",
            })
            if detector_model.is_file():
                self.environment["WEBOBS_DETECTOR_MODEL"] = str(detector_model)
            if (self.runtime / "bin/go2rtc.exe").is_file():
                self.environment["WEBOBS_GO2RTC_BINARY"] = str(self.runtime / "bin/go2rtc.exe")
        if os.environ.get("WEBOBS_PRODUCT_ALLOW_TEST_ENDPOINTS") == "true":
            self.environment["WEBOBS_CAMERA_ALLOW_TEST_ENDPOINTS"] = "true"
        return True

    def port(self, preferred=0):
        lease = self.resources.enter_context(socket.socket())
        # POSIX permits ordinary restart over old TIME_WAIT connections. Never
        # use Windows SO_REUSEADDR to force a bind over an existing listener.
        if os.name == "nt":
            lease.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            lease.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        lease.bind(("127.0.0.1", preferred))
        return lease, lease.getsockname()[1]

    def control_port(self):
        path = self.root / "config/native-network.json"
        if path.is_symlink() or (path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("native network configuration must not be a link")
        if path.exists():
            if not path.is_file() or path.stat().st_size > 4096:
                raise ValueError("native network configuration is invalid")
            value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_configuration)
            if (not isinstance(value, dict) or set(value) != {"schema", "controlPort"} or
                    type(value["schema"]) is not int or value["schema"] != 1 or
                    type(value["controlPort"]) is not int or not 1024 <= value["controlPort"] <= 65535):
                raise ValueError("native network configuration is invalid")
            try:
                return self.port(value["controlPort"])
            except OSError:
                self.failure_reason = "saved-control-port-unavailable"
                raise RuntimeError("saved control port is unavailable") from None
        lease, port = self.port()
        # Commit once before exposing the first browser origin. Later launches
        # preserve these bytes; startup failure must never select a new origin.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="native-network-",
                                             suffix=".new", dir=path.parent, delete=False) as output:
                temporary = Path(output.name)
                json.dump({"schema": 1, "controlPort": port}, output)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(path)
            if os.name != "nt":
                descriptor = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return lease, port

    def start(self, name, command, *, environment=None, health="", lease=None):
        if lease is not None:
            lease.close()
        log = self.resources.enter_context((self.root / f"logs/native-{name}.log").open("ab"))
        process = subprocess.Popen(command, cwd=self.runtime / "bin/64bit",
            env=environment or self.environment, stdin=subprocess.PIPE, stdout=log, stderr=log,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
        self.children.append((name, process))
        if health:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline and not self.stop_requested.is_set():
                if process.poll() is not None:
                    raise RuntimeError(f"{name} exited during startup")
                try:
                    with self.opener.open(health, timeout=1) as response:
                        if response.status == 200:
                            response.read(65536)
                            return process
                except OSError:
                    pass
                self.stop_requested.wait(0.1)
            raise RuntimeError(f"{name} health deadline exceeded")
        return process

    def start_authority(self, leases):
        # The existing account and Registry handlers share this owned Python
        # runtime. They retain their own ports, stores and locking contracts.
        os.environ.clear()
        os.environ.update(self.environment)
        log = self.resources.enter_context((self.root / "logs/native-authority.log").open("a", encoding="utf-8"))
        self.resources.enter_context(contextlib.redirect_stderr(log))
        self.resources.enter_context(contextlib.redirect_stdout(log))
        sys.path.insert(0, str(self.runtime / "services"))
        from camera import camera_registry
        from cluster import cluster_service
        camera_registry.initialize()
        cluster_service.INTERNAL_TOKEN = self.environment["WEBOBS_CLUSTER_INTERNAL_TOKEN"]
        self.authority_store = cluster_service.ClusterStore(
            Path(self.environment["WEBOBS_CLUSTER_DATABASE"]), cluster_service.PasswordHasher(),
            camera_registry_path=Path(self.environment["WEBOBS_CAMERA_DATABASE"]))
        cluster_service.STORE = self.authority_store
        for name, handler in (("camera", camera_registry.Handler), ("cluster", cluster_service.Handler)):
            lease, port = leases[name]
            server = AuthorityServer(("127.0.0.1", port), handler, bind_and_activate=False)
            server.socket.close()
            server.socket = lease
            server.server_name = "127.0.0.1"
            server.server_port = port
            server.server_activate()
            self.authority_servers.append(server)
            thread = threading.Thread(target=server.serve_forever, name=f"product-{name}", daemon=True)
            thread.start()
            self.authority_threads.append(thread)

    def close_frontend(self):
        process = next((process for name, process in self.children if name == "frontend"), None)
        if process is None or process.poll() is not None:
            return
        if os.name == "nt":
            from ctypes import wintypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

            def close_window(window, _):
                owner = wintypes.DWORD()
                user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
                if owner.value == process.pid:
                    user32.PostMessageW(window, 0x0010, 0, 0)
                return True

            user32.EnumWindows(callback_type(close_window), 0)
        else:
            process.send_signal(signal.SIGTERM)

    def stop(self):
        self.stop_requested.set()
        try:
            self.stop_lan()
            self.close_frontend()
            deadline = time.monotonic() + 25
            for name, process in reversed(self.children):
                if process.poll() is not None:
                    continue
                if name != "frontend":
                    try:
                        process.stdin.write(b"shutdown\n")
                        process.stdin.flush()
                    except OSError:
                        pass
                try:
                    process.wait(timeout=max(0.1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            for server in self.authority_servers:
                server.shutdown()
                server.server_close()
            if self.authority_store is not None:
                self.authority_store.close()
                self.authority_store = None
            if self.owns_profile and (self.root / "run").is_dir():
                self.status("stopped")
        finally:
            self.owns_profile = False
            self.resources.close()

    def lan_status(self):
        """Bounded view of the entry for the native window and the status file."""
        with self.lan_lock:
            value = self.lan_value
        receipt = self.lan.status(value)
        receipt["running"] = bool(self.lan_process and self.lan_process.poll() is None)
        receipt["pendingRestart"] = self.lan_dirty.is_set()
        receipt["switchPort"] = self.lan_server.server_port if self.lan_server else 0
        return receipt

    def request_lan(self, enabled, port):
        """Persist the switch; the entry applies on the next product start.

        ``webobsd`` reads its allowed origins when it starts, so toggling the
        entry must not silently reopen a listener inside a live session. The
        setting survives restarts, and the receipt tells the window whether a
        restart is still required.
        """
        with self.lan_lock:
            self.lan.write_setting(self.root, enabled, port)
            setting = self.lan.read_setting(self.root)
            addresses = self.lan.discover_addresses() if setting["enabled"] else []
            self.lan_value = self.lan.plan(setting, addresses, self.lan_control_port, self.root)
            self.lan_dirty.set()
        # The status file is what the installed gates and the support bundle
        # observe, so a toggle must publish the same receipt the switch returns.
        self.status(self.phase)
        return self.lan_status()

    def reserve_lan_port(self, address, port):
        lease = self.resources.enter_context(socket.socket())
        if os.name == "nt":
            lease.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            lease.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        lease.bind((address, port))
        return lease

    def prepare_lan(self, control_port):
        """Read the persisted switch and give the control server its LAN origins.

        Only private IPv4 addresses are published, the HTTPS listener belongs to
        Caddy, and the reverse proxy dial target stays loopback. A malformed
        setting or a busy LAN port fails closed: the product never falls back to
        serving an enabled LAN entry over plain HTTP.
        """
        self.lan_control_port = control_port
        setting = self.lan.read_setting(self.root)
        addresses = self.lan.discover_addresses() if setting["enabled"] else []
        value = self.lan.plan(setting, addresses, control_port, self.root)
        with self.lan_lock:
            self.lan_value = value
        self.environment["WEBOBS_CONTROL_ALLOWED_ORIGINS"] = ",".join(
            self.lan.control_origins(self.origin, value))
        if not value["urls"]:
            return
        # Reserve the HTTPS port before widening any origin or WebRTC bind. A busy
        # port stops this entry only: local loopback monitoring is what users already
        # depend on, so a conflicting port must not refuse every product launch. The
        # receipt keeps enabled=true with a bounded reason and no URL, and nothing is
        # exposed beyond loopback while the entry is refused.
        try:
            self.lan_lease = self.reserve_lan_port(value["serving"][0], value["port"])
        except OSError:
            value = dict(value, serving=[], urls=[], certificate="", configuration=None,
                         firewallCommands=[], reason="lan-port-unavailable")
            with self.lan_lock:
                self.lan_value = value
            self.environment["WEBOBS_CONTROL_ALLOWED_ORIGINS"] = ",".join(
                self.lan.control_origins(self.origin, value))
            print("LAN sharing is enabled but the HTTPS port is already in use; "
                  "the entry stays closed and local monitoring continues", flush=True)
            return
        self.environment["WEBOBS_PWA_MEDIA_ALLOWED_ORIGINS"] = ",".join(self.lan.media_origins(value))
        # Composite playback from another machine needs candidates a remote
        # browser can reach; Direct RTSP monitoring keeps its loopback-only binds.
        self.environment["WEBOBS_GO2RTC_WEBRTC_BIND"] = "0.0.0.0"
        self.environment["WEBOBS_GO2RTC_WEBRTC_HOSTS"] = ",".join(value["serving"])
        self.lan_config = self.root / "run/lan-caddy.json"
        self.lan_config.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="lan-caddy-",
                    suffix=".new", dir=self.lan_config.parent, delete=False) as output:
                temporary = Path(output.name)
                json.dump(value["configuration"], output)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(self.lan_config)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def start_lan(self):
        """Start the HTTPS reverse proxy and prove a local client can connect.

        The proxy is not part of the required-service set: a Caddy failure stops
        the LAN entry with a bounded reason instead of tearing down local
        monitoring that users already rely on.
        """
        with self.lan_lock:
            value = self.lan_value
        if not value["urls"]:
            return
        caddy = self.runtime / "bin/caddy.exe"
        if not caddy.is_file() or caddy.is_symlink():
            self.failure_reason = "lan-runtime-missing"
            print("LAN sharing is enabled but this runtime has no Caddy component", flush=True)
            return
        if self.lan_lease is not None:
            self.lan_lease.close()
            self.lan_lease = None
        log = self.resources.enter_context((self.root / "logs/native-lan.log").open("ab"))
        process = subprocess.Popen([str(caddy), "run", "--config", str(self.lan_config)],
            cwd=str(self.runtime / "bin"), env=self.environment, stdin=subprocess.DEVNULL,
            stdout=log, stderr=log,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
        self.lan_process = process
        deadline = time.monotonic() + 15
        reachable = False
        while time.monotonic() < deadline and not self.stop_requested.is_set():
            if process.poll() is not None:
                break
            try:
                with socket.create_connection((value["serving"][0], value["port"]), timeout=2):
                    reachable = True
                    break
            except OSError:
                self.stop_requested.wait(0.2)
        if not reachable:
            self.stop_lan()
            self.failure_reason = "lan-proxy-unreachable"
            print("the LAN HTTPS entry did not become reachable", flush=True)

    def stop_lan(self):
        process, self.lan_process = self.lan_process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def start_lan_switch(self):
        """Loopback-only switch the native window drives with the host token."""
        self.lan_server = self.resources.enter_context(LanControlServer(self))
        self.lan_thread = threading.Thread(target=self.lan_server.serve_forever,
            name="product-lan-switch", daemon=True)
        self.lan_thread.start()

    def start_python(self, name, relative, health, args=()):
        script = self.runtime / "services" / relative
        if not script.is_file():
            raise RuntimeError(f"missing product service: {name}")
        return self.start(name, [sys.executable, "-B", str(script), *args], health=health)

    def run(self):
        try:
            if not self.prepare():
                return 73
            # Reserve the persistent origin first, before opening any authority
            # listener. Registry/account ports remain private per-boot details.
            leases = {"control": self.control_port()}
            leases.update({name: self.port() for name in ("camera", "cluster")})
            extra = ("events", "nvr", "clients", "go2rtcApi", "go2rtcRtsp", "go2rtcWebrtc") if self.complete else ()
            leases.update({name: self.port() for name in extra})
            camera_port = leases["camera"][1]
            cluster_port = leases["cluster"][1]
            control_port = leases["control"][1]
            self.environment.update(WEBOBS_CAMERA_INTERNAL_PORT=str(camera_port),
                WEBOBS_CLUSTER_INTERNAL_PORT=str(cluster_port), WEBOBS_HTTP_PORT=str(control_port))
            if self.complete:
                self.environment.update(
                    WEBOBS_EVENTS_INTERNAL_PORT=str(leases["events"][1]),
                    WEBOBS_NVR_INTERNAL_PORT=str(leases["nvr"][1]),
                    WEBOBS_V2_INTERNAL_PORT=str(leases["clients"][1]),
                    WEBOBS_GO2RTC_API_PORT=str(leases["go2rtcApi"][1]),
                    WEBOBS_GO2RTC_RTSP_PORT=str(leases["go2rtcRtsp"][1]),
                    WEBOBS_GO2RTC_WEBRTC_PORT=str(leases["go2rtcWebrtc"][1]))
            self.origin = f"http://127.0.0.1:{control_port}"
            self.environment["WEBOBS_CONTROL_ALLOWED_ORIGINS"] = self.origin
            self.prepare_lan(control_port)
            self.start_authority(leases)
            if self.complete:
                for name in extra:
                    leases[name][0].close()
                self.start_python("events", "events/event_service.py",
                                  f"http://127.0.0.1:{leases['events'][1]}/health")
                self.start_python("nvr", "nvr/nvr_service.py",
                                  f"http://127.0.0.1:{leases['nvr'][1]}/health")
                self.start_python("clients", "v2/client_control_service.py",
                                  f"http://127.0.0.1:{leases['clients'][1]}/health")
                self.start_python("go2rtc", "go2rtc/runtime.py",
                                  f"http://127.0.0.1:{leases['go2rtcApi'][1]}/api/v1/go2rtc/api")
                if (self.root / "config/archive.json").is_file():
                    self.start_python("archive", "archive/s3_archive.py", "")
                self.start_python("backup", "backup/encrypted_backup.py", "", ["schedule"])
            self.start("control", [str(self.runtime / "bin/webobsd.exe")],
                       health=self.origin + "/api/v1/health", lease=leases["control"][0])
            self.start_lan()
            self.start_lan_switch()
            frontend_environment = clean_environment(os.environ)
            frontend_environment.update(PATH=self.environment["PATH"],
                WEBOBS_NATIVE_CONTROL_ORIGIN=self.origin,
                WEBOBS_NATIVE_HOST_TOKEN=self.environment["WEBOBS_NATIVE_HOST_TOKEN"],
                WEBOBS_NATIVE_BOOT_ID=self.boot_id,
                WEBOBS_NATIVE_PRODUCT_VERSION=self.version,
                WEBOBS_NATIVE_PREVIEW="true" if self.preview else "false",
                WEBOBS_NATIVE_PROFILE_ROOT=str(self.root / "native-profile"),
                WEBOBS_NATIVE_LAN_SWITCH=(f"http://127.0.0.1:{self.lan_server.server_port}/lan"
                    if self.lan_server else ""))
            if self.complete and getattr(self, "program_recordings", None) is not None:
                frontend_environment["WEBOBS_PROGRAM_RECORDINGS"] = str(self.program_recordings)
                frontend_environment["WEBOBS_SUPPORT_BUNDLE_ROOT"] = str(self.root / "support")
                (self.root / "support").mkdir(parents=True, exist_ok=True)
            frontend = self.start("frontend", [str(self.runtime / "bin/64bit/obs64.exe"),
                "--portable", "--disable-updater"], environment=frontend_environment)
            self.status("running")
            while frontend.poll() is None and not self.stop_requested.wait(0.2):
                if (any(process.poll() is not None for name, process in self.children if name != "frontend") or
                        any(not thread.is_alive() for thread in self.authority_threads)):
                    raise RuntimeError("a required product service exited")
            if frontend.returncode:
                self.failure_reason = "frontend-exited"
            return frontend.returncode or 0
        except Exception:
            if not self.failure_reason:
                self.failure_reason = "startup-or-service-error"
            if self.owns_profile and (self.root / "logs").is_dir():
                with (self.root / "logs/native-startup.log").open("a", encoding="utf-8") as output:
                    traceback.print_exc(file=output)
            raise
        finally:
            self.stop()


def main():
    runtime = Path(__file__).resolve().parents[2]
    manifest = json.loads((runtime / "webobs-native-prototype.json").read_text(encoding="utf-8"))
    complete = all((runtime / marker).is_file() for marker in (
        "services/events/event_service.py", "services/nvr/nvr_service.py",
        "services/v2/client_control_service.py", "bin/go2rtc.exe",
        "bin/node.exe", "bin/webobs-online-source.exe"))
    profile = ("Native" if complete else
               "NativePreview" if delivery_profile(manifest) == "native-monitor-preview" else "NativeIntegration")
    root = Path(os.environ["LOCALAPPDATA"]) / "WebOBS" / profile
    # Internal builds accept a separately owned test profile. R6 freezes the
    # production data/upgrade location after migration qualification.
    if profile != "NativePreview" and os.environ.get("WEBOBS_PRODUCT_TEST_ROOT"):
        root = Path(os.environ["WEBOBS_PRODUCT_TEST_ROOT"])
    supervisor = ProductSupervisor(runtime, root)
    for selected in (signal.SIGINT, signal.SIGTERM):
        signal.signal(selected, lambda *_: supervisor.stop_requested.set())
    try:
        return supervisor.run()
    except Exception:
        # Child diagnostics already live inside the protected profile. No
        # exception, camera URL, token or private path is sent to public stdout.
        if sys.stderr is not None:
            print("WebOBS Wall startup failed. Inspect the private native component logs.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
