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
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from http.server import ThreadingHTTPServer


def clean_environment(environment):
    blocked = ("WEBOBS_", "MTX_", "GO2RTC_", "PYTHON", "QT_", "QML", "OBS_", "NODE_", "CSC_")
    secrets_and_proxies = {"GH_TOKEN", "GITHUB_TOKEN", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}
    return {key: value for key, value in environment.items()
            if not key.upper().startswith(blocked) and key.upper() not in secrets_and_proxies
            and key.upper() != "PATH"}


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


class ProductSupervisor:
    def __init__(self, runtime, root):
        self.runtime = Path(runtime).resolve(strict=True)
        self.root = Path(root).absolute()
        self.children = []
        self.stop_requested = threading.Event()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.resources = contextlib.ExitStack()
        self.origin = ""
        self.owns_profile = False
        self.authority_servers = []
        self.authority_threads = []
        self.authority_store = None

    def status(self, phase):
        value = {"schema": 1, "phase": phase, "origin": self.origin,
                 "ownerPid": os.getpid(), "services": [
                     {"name": name, "pid": process.pid, "running": process.poll() is None}
                     for name, process in self.children]}
        if self.authority_store is not None:
            value["services"].append({"name": "accounts-and-registry", "pid": os.getpid(),
                                       "running": all(thread.is_alive() for thread in self.authority_threads)})
        target = self.root / "run/native-status.json"
        temporary = target.with_suffix(".new")
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(value, output)
        temporary.replace(target)

    def prepare(self):
        manifest = self.runtime / "webobs-native-prototype.json"
        value = json.loads(manifest.read_text(encoding="utf-8"))
        if (value.get("obsCommit") != "fb4d98bf88fae5fc85cb11fc57f7c5e309282194"
                or value.get("productIntegration") is not True or value.get("publicationForbidden") is not True):
            raise ValueError("this supervisor requires the internal integrated product build")
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
        for name in ("config", "logs", "native-profile/obs-studio"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        ini = self.root / "native-profile/obs-studio/user.ini"
        if not ini.exists():
            with ini.open("x", encoding="utf-8") as output:
                output.write("[General]\nFirstRun=true\n[BasicWindow]\nSysTrayEnabled=false\n")
        protect(self.root / "config", self.runtime)
        protect(self.root / "native-profile", self.runtime)
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
            "WEBOBS_NATIVE_HOST_TOKEN": secrets.token_hex(32),
            "WEBOBS_WEBRTC_ENABLED": "true", "WEBOBS_COMPOSITE_ENABLED": "false",
            "WEBOBS_NVR_ENABLED": "false", "WEBOBS_GO2RTC_ENABLED": "false",
            "WEBOBS_CAMERA_BACKGROUND_PROBES": "false", "WEBOBS_CAMERA_BACKGROUND_EVENTS": "false",
            "WEBOBS_WHIP_URL": "http://127.0.0.1:9/native-unused/whip",
            "WEBOBS_NODE_ROLE": "standalone",
        })
        if os.environ.get("WEBOBS_PRODUCT_ALLOW_TEST_ENDPOINTS") == "true":
            self.environment["WEBOBS_CAMERA_ALLOW_TEST_ENDPOINTS"] = "true"
        return True

    def port(self):
        lease = self.resources.enter_context(socket.socket())
        lease.bind(("127.0.0.1", 0))
        return lease, lease.getsockname()[1]

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

    def run(self):
        try:
            if not self.prepare():
                return 73
            leases = {name: self.port() for name in ("camera", "cluster", "control")}
            camera_port = leases["camera"][1]
            cluster_port = leases["cluster"][1]
            control_port = leases["control"][1]
            self.environment.update(WEBOBS_CAMERA_INTERNAL_PORT=str(camera_port),
                WEBOBS_CLUSTER_INTERNAL_PORT=str(cluster_port), WEBOBS_HTTP_PORT=str(control_port))
            self.origin = f"http://127.0.0.1:{control_port}"
            self.environment["WEBOBS_CONTROL_ALLOWED_ORIGINS"] = self.origin
            self.start_authority(leases)
            self.start("control", [str(self.runtime / "bin/webobsd.exe")],
                       health=self.origin + "/api/v1/health", lease=leases["control"][0])
            frontend_environment = clean_environment(os.environ)
            frontend_environment.update(PATH=self.environment["PATH"],
                WEBOBS_NATIVE_CONTROL_ORIGIN=self.origin,
                WEBOBS_NATIVE_HOST_TOKEN=self.environment["WEBOBS_NATIVE_HOST_TOKEN"],
                WEBOBS_NATIVE_PROFILE_ROOT=str(self.root / "native-profile"))
            frontend = self.start("frontend", [str(self.runtime / "bin/64bit/obs64.exe"),
                "--portable", "--disable-updater"], environment=frontend_environment)
            self.status("running")
            while frontend.poll() is None and not self.stop_requested.wait(0.2):
                if (any(process.poll() is not None for name, process in self.children if name != "frontend") or
                        any(not thread.is_alive() for thread in self.authority_threads)):
                    raise RuntimeError("a required product service exited")
            return frontend.returncode or 0
        except Exception:
            if self.owns_profile and (self.root / "logs").is_dir():
                with (self.root / "logs/native-startup.log").open("a", encoding="utf-8") as output:
                    traceback.print_exc(file=output)
            raise
        finally:
            self.stop()


def main():
    runtime = Path(__file__).resolve().parents[2]
    root = Path(os.environ["LOCALAPPDATA"]) / "WebOBS/NativeIntegration"
    # Internal builds accept a separately owned test profile. R6 freezes the
    # production data/upgrade location after migration qualification.
    if os.environ.get("WEBOBS_PRODUCT_TEST_ROOT"):
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
