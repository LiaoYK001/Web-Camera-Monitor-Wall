#!/usr/bin/env python3
"""Real packaged supervisor/account/Registry/core lifecycle, frontend fixture only.

Linux development check: this does not qualify Qt startup, media or Windows Job
ownership. The disposable layout uses the same fixed packaged service paths.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def wait_for(predicate, message, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.1)
    raise AssertionError(message)


def exercise(binary, sodium):
    if os.name == "nt":
        raise RuntimeError("this frontend-fixture test is Linux-only; use the actual Windows entry gate")
    with tempfile.TemporaryDirectory(prefix="webobs-supervisor-") as temporary:
        private = Path(temporary)
        runtime, profile = private / "runtime", private / "private-profile"
        for directory in ("bin/64bit", "services/product", "services/desktop-tools"):
            (runtime / directory).mkdir(parents=True)
        for name in ("camera", "cluster"):
            target = runtime / "services" / name
            target.mkdir()
            for source in (ROOT / name).glob("*.py"):
                shutil.copy2(source, target / source.name)
        shutil.copy2(ROOT / "runtime_support.py", runtime / "services/runtime_support.py")
        shutil.copy2(ROOT / "desktop/python/private_directory.py", runtime / "services/desktop-tools/private_directory.py")
        supervisor = runtime / "services/product/supervisor.py"
        shutil.copy2(ROOT / "native-host/scripts/product_supervisor.py", supervisor)
        shutil.copy2(binary, runtime / "bin/webobsd.exe")
        shutil.copy2(sodium, runtime / "bin/libsodium.dll")
        (runtime / "webobs-native-prototype.json").write_text(json.dumps({
            "obsCommit": "fb4d98bf88fae5fc85cb11fc57f7c5e309282194",
            "productIntegration": True, "publicationForbidden": True}), encoding="utf-8")
        frontend = runtime / "bin/64bit/obs64.exe"
        frontend.write_text(f"#!{sys.executable}\nimport signal,time\n"
            "stopped=False\ndef stop(*_):\n global stopped\n stopped=True\n"
            "signal.signal(signal.SIGTERM,stop)\n"
            "while not stopped: time.sleep(.05)\n", encoding="utf-8")
        frontend.chmod(0o700)
        environment = {key: value for key, value in os.environ.items() if not key.startswith("WEBOBS_")}
        environment.update(LOCALAPPDATA=str(private), WEBOBS_PRODUCT_TEST_ROOT=str(profile))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        processes = []
        status_path = profile / "run/native-status.json"

        def current():
            try:
                return json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}

        def start():
            process = subprocess.Popen([sys.executable, "-B", str(supervisor)], env=environment,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(process)
            def ready():
                assert process.poll() is None, "actual supervisor exited before readiness"
                state = current()
                return state if state.get("ownerPid") == process.pid and state.get("phase") == "running" else None
            return process, wait_for(ready, "supervisor readiness timed out")

        def request(origin, path, body=None, cookie=""):
            data = None if body is None else json.dumps(body).encode()
            headers = {"Origin": origin, "Content-Type": "application/json"}
            if cookie:
                headers["Cookie"] = cookie
            message = urllib.request.Request(origin + path, data=data, headers=headers)
            try:
                reply = opener.open(message, timeout=12)
            except urllib.error.HTTPError as error:
                reply = error
            with reply:
                return reply.status, reply.headers.get("Set-Cookie", ""), json.loads(reply.read())

        def assert_closed(origin):
            try:
                opener.open(origin + "/api/v1/health", timeout=1).close()
            except OSError:
                return True
            return False

        try:
            process, state = start()
            assert sorted(service["name"] for service in state["services"]) == ["accounts-and-registry", "control", "frontend"]
            assert next(service for service in state["services"] if service["name"] == "accounts-and-registry")["pid"] == process.pid
            origin = state["origin"]
            assert request(origin, "/api/v1/auth/setup")[2]["registrationOpen"]
            account = {"username": "lifecycle-owner", "password": secrets.token_urlsafe(24)}
            assert request(origin, "/api/v1/auth/setup", account)[0] == 201
            code, issued, _ = request(origin, "/api/v1/auth/login", account)
            assert code == 200 and issued
            cookie = issued.split(";", 1)[0]
            code, _, diagnostics = request(origin, "/api/v1/system/processes", cookie=cookie)
            assert code == 200 and diagnostics["engineActive"] is False
            assert diagnostics["compositePublisherActive"] is False, "control service started a second media engine"
            duplicate = subprocess.run([sys.executable, "-B", str(supervisor)], env=environment,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            assert duplicate.returncode == 73, "duplicate entry acquired the private profile"
            assert current()["phase"] == "running" and current()["ownerPid"] == process.pid
            frontend_pid = next(service["pid"] for service in state["services"] if service["name"] == "frontend")
            os.kill(frontend_pid, signal.SIGTERM)
            assert process.wait(timeout=30) == 0, "normal frontend close did not complete orderly shutdown"
            assert current()["phase"] == "stopped"
            wait_for(lambda: assert_closed(origin), "control listener survived normal close", timeout=5)
            # Restart uses the same real account store; no reset or re-registration.
            process, state = start()
            assert request(state["origin"], "/api/v1/auth/setup")[2]["registrationOpen"] is False
            assert request(state["origin"], "/api/v1/auth/login", account)[0] == 200
            core_pid = next(service["pid"] for service in state["services"] if service["name"] == "control")
            frontend_pid = next(service["pid"] for service in state["services"] if service["name"] == "frontend")
            os.kill(core_pid, signal.SIGKILL)
            assert process.wait(timeout=30) != 0, "required service crash was reported as success"
            try:
                os.kill(frontend_pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError("frontend fixture survived required-service failure")
            assert current()["phase"] == "stopped"
            print("PASS actual supervisor, embedded authority, registration/login, duplicate entry, persistence and service-failure cleanup (frontend fixture; no media qualification)")
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--sodium", type=Path, required=True)
    arguments = parser.parse_args()
    exercise(arguments.binary.resolve(strict=True), arguments.sodium.resolve(strict=True))
