#!/usr/bin/env python3
"""Installed-state gate for the shipped old-data import path (V51-014).

Runs against an installed complete Windows product runtime. One disposable profile
is filled through the real installed entry (owner account, Camera Registry row,
event, NVR policy) and is then treated as an old installation. The import is
performed by the importer *shipped inside the installer*, invoked with the runtime's
own embedded Python, exactly like MIGRATE-LEGACY.cmd does. A second installed start
on the imported profile must accept the old credentials, keep the old devices,
events and recording policy, decrypt the old DPAPI backup key and refuse both a new
first account and a second import.

Honest boundary: this qualifies the config/database import path. The user's own
profile, recordings/archives outside config, and the Electron-era scene/studio
documents are not claimed here, so ``fullFeatureMigrationQualified`` stays false.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from window_close import close_closable_windows

REPO = HERE.parents[1]
RUNTIME_SCRIPTS = REPO / "native-host/scripts"
# Durable user data only: run state, logs, crash dumps, generated backups and SQLite
# sidecars change while the product runs and must not look like migration damage.
VOLATILE_PREFIXES = ("run/", "backups/", "logs/", "crashes/", "recordings/")
VOLATILE_NAMES = (".sentinel",)


def read_json(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 262144:
        raise ValueError("missing or invalid private state")
    return json.loads(path.read_text(encoding="utf-8"))


def wait_for(predicate, message, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.2)
    raise AssertionError(message)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def durable_digests(profile: Path) -> dict:
    """Every durable file under one product profile, keyed by a forward-slash path."""
    state = {}
    for item in profile.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        relative = item.relative_to(profile).as_posix()
        if relative.startswith(VOLATILE_PREFIXES) or any(part in VOLATILE_NAMES
                                                        for part in relative.split("/")):
            continue
        if relative.endswith(("-wal", "-shm")):
            continue
        state[relative] = sha256(item)
    return state


def dpapi_protect(data: bytes) -> bytes:
    """Encrypt like Electron safeStorage does, so the shipped decrypt path is tested."""
    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(data))(*data)
    incoming = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(incoming), None, None, None,
            None, 0, ctypes.byref(outgoing)):
        raise ValueError("Windows refused to protect the synthetic backup key")
    try:
        return bytes(bytearray(outgoing.pbData[:outgoing.cbData]))
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)


class Client:
    """One loopback session against the installed product entry.

    Every request carries the product's own Origin: a state-changing request
    without it is not a request a browser or the product UI can actually make, and
    the control server rejects a mismatching one.
    """

    def __init__(self, port, origin):
        self.port = int(port)
        assert isinstance(origin, str) and origin, "the product origin is required"
        self.origin = origin
        self.cookie = ""

    def request(self, path, body=None, *, cookie=None, origin=None, method=None):
        headers = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json",
                   "Origin": self.origin if origin is None else origin}
        session = self.cookie if cookie is None else cookie
        if session:
            headers["Cookie"] = session
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        if method is None:
            method = "POST" if payload is not None else "GET"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            text = response.read(65536).decode("utf-8", "replace")
            issued = response.getheader("Set-Cookie", "")
        finally:
            connection.close()
        if issued.startswith("webobs_session="):
            self.cookie = issued.split(";", 1)[0]
        return response.status, text


def runtime_processes(runtime: Path, powershell) -> set:
    """PIDs whose executable lives inside this installed runtime, so the gate can prove cleanup."""
    script = ("Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and "
              f"$_.ExecutablePath.StartsWith('{runtime}') }} | ForEach-Object {{ $_.ProcessId }}")
    result = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if result.returncode != 0:
        raise ValueError("could not enumerate the runtime's processes")
    return {int(line) for line in result.stdout.split() if line.strip().isdigit()}


def exercise(runtime, report):
    if os.name != "nt":
        raise ValueError("the old-data import gate requires the actual Windows product runtime")
    manifest = read_json(runtime / "webobs-native-prototype.json")
    if manifest.get("productIntegration") is not True:
        raise ValueError("internal integrated product build required")
    components_path = runtime / "product-components.json"
    # The component receipt lists every staged file with a digest, so it is far larger
    # than the private state files; it is still read-only here and bounded.
    if not components_path.is_file() or components_path.is_symlink() or \
            components_path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("installed component receipt is missing or oversized")
    components = json.loads(components_path.read_text(encoding="utf-8"))
    if components.get("completeStaging") is not True:
        raise ValueError("the old-data import gate needs the staged business services")
    importer = runtime / "services/product/migrate_legacy.py"
    shipped_entry = runtime / "MIGRATE-LEGACY.cmd"
    entry = runtime / "bin/webobs-wall.exe"
    embedded = runtime / "python/python.exe"
    powershell = shutil.which("pwsh")
    if not powershell:
        raise ValueError("test-side PowerShell 7 required")
    if not (importer.is_file() and shipped_entry.is_file() and entry.is_file() and embedded.is_file()):
        raise ValueError("the installed runtime is missing the shipped import entry")

    evidence = {"schema": 1, "kind": "native-legacy-config-import",
        "version": manifest.get("version"), "sourceRevision": components.get("sourceRevision"),
        "passed": False, "checks": [],
        "lastCheckpoint": "prepare", "legacyConfigImportQualified": False,
        "fullFeatureMigrationQualified": False, "physicalLegacyProfileQualified": False,
        "packagedImporterSha256": sha256(importer), "importedFiles": 0,
        "backupKeyMigrated": False, "migratedCameras": 0, "migratedEvents": 0,
        "skipReason": ""}

    # The shipped importer must be the audited source, not a drifted copy.
    evidence["lastCheckpoint"] = "shipped-entry-bound-to-source"
    assert evidence["packagedImporterSha256"] == sha256(RUNTIME_SCRIPTS / "migrate_legacy.py"), \
        "the installed importer is not byte-identical to the audited migration script"
    entry_text = shipped_entry.read_text(encoding="utf-8", errors="replace")
    assert "%LOCALAPPDATA%\\WebOBS\\Native\\config" in entry_text, \
        "MIGRATE-LEGACY.cmd does not target the product's own data root"
    assert "--confirm-stopped" in entry_text and "--include-backup-key" in entry_text, \
        "MIGRATE-LEGACY.cmd lost the stopped-confirmation or the backup-key step"
    evidence["checks"].append("shipped-import-entry-is-the-audited-script")

    account = {"username": "legacy-owner", "password": secrets.token_urlsafe(22)}
    backup_key = secrets.token_hex(32)
    camera_id = "legacy-camera"
    process = None
    frontend_pid = 0
    baseline = runtime_processes(runtime, powershell)
    seen = set()

    def launch(profile: Path):
        nonlocal process, seen, frontend_pid
        environment = dict(os.environ)
        environment["WEBOBS_PRODUCT_TEST_ROOT"] = str(profile)
        # The old camera endpoint is a closed loopback port: creation must succeed and
        # background probes must fail fast instead of hanging on a routable address.
        environment["WEBOBS_PRODUCT_ALLOW_TEST_ENDPOINTS"] = "true"
        process = subprocess.Popen([str(entry)], env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def ready():
            assert process.poll() is None, "native product entry exited during startup"
            value = read_json(profile / "run/native-status.json") \
                if (profile / "run/native-status.json").is_file() else {}
            return value if value.get("phase") == "running" else None
        status = wait_for(ready, "the installed entry did not start its services")
        frontend = next((item for item in status.get("services", [])
                         if item.get("name") == "frontend" and isinstance(item.get("pid"), int)), None)
        assert frontend is not None, "the installed entry did not report its frontend process"
        frontend_pid = int(frontend["pid"])
        seen |= runtime_processes(runtime, powershell) - baseline
        return status

    def stop(profile: Path):
        nonlocal process, frontend_pid
        if process is None:
            return
        # Terminating the launcher would close its kill-on-close Job and take the
        # supervisor down with it, so its ordered shutdown - and the phase
        # "stopped" receipt it writes - would never happen. Closing the product
        # window is what the supervisor's own stop does and what a user does.
        assert frontend_pid, "the installed entry did not report a frontend process"
        if not close_closable_windows([frontend_pid]):
            process.kill()
            process.wait(timeout=20)
            process = None
            raise AssertionError("the installed entry exposed no closable product window")
        try:
            process.wait(timeout=90)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)
            process = None
            raise AssertionError("closing the product window did not shut the installed entry down")
        process = None
        frontend_pid = 0
        def stopped():
            value = read_json(profile / "run/native-status.json") \
                if (profile / "run/native-status.json").is_file() else {}
            return True if value.get("phase") == "stopped" else None
        wait_for(stopped, "the installed entry did not report a normal stop", timeout=40)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if not (runtime_processes(runtime, powershell) & seen):
                return
            time.sleep(.5)
        raise AssertionError("processes started from this runtime survived the product exit")

    def run_importer(source_profile: Path, destination_profile: Path):
        return subprocess.run([str(embedded), "-B", str(importer), "--source",
            str(source_profile / "config"), "--destination", str(destination_profile / "config"),
            "--confirm-stopped", "--include-backup-key"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180)

    with tempfile.TemporaryDirectory(prefix="WebOBS 旧数据导入-") as temporary:
        root = Path(temporary)
        legacy = root / "legacy-install"
        imported = root / "imported-install"
        legacy.mkdir()
        try:
            evidence["lastCheckpoint"] = "legacy-install-filled"
            status = launch(legacy)
            origin = status["origin"]
            port = int(origin.rsplit(":", 1)[1])
            client = Client(port, origin)
            code, body = client.request("/api/v1/auth/setup", origin=origin)
            assert code == 200 and json.loads(body).get("registrationOpen") is True, \
                f"a fresh install did not open first-account setup: {code} {body[:160]}"
            code, _ = client.request("/api/v1/auth/setup", account, origin=origin)
            assert code == 201, f"the old installation could not create its owner: {code}"
            code, _ = client.request("/api/v1/auth/login", account, origin=origin)
            assert code == 200 and client.cookie, f"the old owner could not sign in: {code}"
            legacy_cookie = client.cookie
            evidence["checks"].append("legacy-install-account-created-by-the-installed-entry")

            endpoint = f"rtsp://127.0.0.1:{10000 + secrets.randbelow(20000)}/legacy"
            code, camera = client.request("/api/v1/cameras", {
                "id": camera_id, "name": "Legacy camera", "address": endpoint, "adapter": "rtsp",
                "hardwareDecode": "off", "profiles": [{"id": "main", "name": "Main", "role": "main",
                    "endpoint": endpoint, "transportMode": "rtsp-tcp", "videoCodec": "h264",
                    "width": 640, "height": 360, "fps": 15, "audioCodec": ""}]}, cookie=client.cookie)
            assert code == 201, f"the old installation could not save a camera: {code} {camera[:160]}"
            code, stored = client.request("/api/v1/events", {
                "cameraId": camera_id, "type": "manual-marker", "source": "manual",
                "topic": "legacy.qa", "severity": "info", "occurredAt": int(time.time() * 1000),
                "properties": {"durationMs": 0}, "dedupeKey": "legacy-import-event"},
                cookie=client.cookie)
            assert code == 201, f"the old installation could not store an event: {code}"
            event_id = json.loads(stored).get("id")
            assert event_id, "the stored legacy event did not report its identity"
            nvr_configuration = {"schemaVersion": 1, "segmentSeconds": 30, "maxAgeHours": 24,
                "maxBytes": 0, "minFreeBytes": 0, "cameras": [{
                    "id": "legacy-policy", "name": "Legacy policy", "policy": "event",
                    "cameraId": camera_id, "mainProfileId": "main", "stream": "main",
                    "mode": "copy", "transport": "tcp", "segmentSeconds": 30, "maxAgeHours": 24,
                    "maxBytes": 0, "preEventSeconds": 0, "schedule": []}]}
            code, _ = client.request("/api/v1/nvr/config", nvr_configuration, cookie=client.cookie,
                method="PUT")
            assert code == 200, f"the old installation could not persist its recording policy: {code}"
            evidence["lastCheckpoint"] = "legacy-install-stopped"
            stop(legacy)
            assert (legacy / "config/nvr.json").is_file(), \
                "the installed NVR service did not persist nvr.json, so there is nothing to migrate"
            key_path = legacy / "backup-key.dpapi"
            key_path.write_bytes(dpapi_protect(backup_key.encode("ascii")))
            before = durable_digests(legacy)
            evidence["legacyFiles"] = len(before)
            evidence["checks"].append("legacy-install-camera-event-and-nvr-policy-persisted")

            evidence["lastCheckpoint"] = "import-by-shipped-script"
            first = run_importer(legacy, imported)
            assert first.returncode == 0, f"the shipped importer failed: {first.stdout[:200]}{first.stderr[:200]}"
            receipt = json.loads(first.stdout)
            after_import = durable_digests(imported)
            assert receipt.get("status") == "migrated" and receipt.get("sourcePreserved") is True, \
                "the shipped importer did not report a preserved-source migration"
            assert receipt.get("backupKeyMigrated") is True, \
                "the old DPAPI backup key was not decrypted into the new profile"
            evidence["importedFiles"] = int(receipt.get("files") or 0)
            assert (imported / "config/backup.key").read_bytes() == backup_key.encode("ascii"), \
                "the migrated backup key is not the plaintext old key"
            evidence["backupKeyMigrated"] = True
            assert (imported / "config/nvr.json").is_file(), "the recording policy was not imported"
            evidence["checks"].append("shipped-importer-copied-databases-settings-and-backup-key")

            evidence["lastCheckpoint"] = "second-import-refused"
            second = run_importer(legacy, imported)
            assert second.returncode != 0, "a second import was allowed over an existing profile"
            assert durable_digests(imported) == after_import, \
                "the refused import changed the imported profile"
            evidence["checks"].append("import-into-an-existing-profile-is-refused-without-writes")
            assert durable_digests(legacy) == before, "the import changed the old installation"
            evidence["checks"].append("old-installation-files-are-byte-identical-after-import")

            evidence["lastCheckpoint"] = "imported-install-started"
            status = launch(imported)
            origin = status["origin"]
            client = Client(int(origin.rsplit(":", 1)[1]), origin)
            code, body = client.request("/api/v1/auth/setup", origin=origin)
            assert code == 200 and json.loads(body).get("registrationOpen") is False, \
                "an imported account store still opened a new first account"
            code, _ = client.request("/api/v1/auth/setup",
                {"username": "intruder", "password": secrets.token_urlsafe(20)}, origin=origin)
            assert code == 409, f"a stranger claimed the imported account store: {code}"
            code, _ = client.request("/api/v1/auth/login", account, origin=origin)
            assert code == 200 and client.cookie, \
                "the old credentials could not sign in on the imported profile"
            code, session = client.request("/api/v1/auth/session", cookie=client.cookie, origin=origin)
            assert code == 200 and account["username"] in session, \
                "the imported session is not the old owner"
            evidence["checks"].append("old-account-signs-in-and-registration-stays-closed")

            code, value = client.request("/api/v1/cameras", cookie=client.cookie)
            assert code == 200, f"imported camera catalog unavailable: {code}"
            cameras = json.loads(value).get("cameras", [])
            migrated = next((item for item in cameras if item.get("id") == camera_id), None)
            assert migrated is not None, f"the old camera row did not survive the import: {len(cameras)} cameras"
            assert migrated.get("adapter") == "rtsp" and migrated.get("address") == endpoint, \
                "the imported camera lost its adapter or endpoint"
            assert len(migrated.get("profiles", [])) == 1 and \
                migrated["profiles"][0].get("endpoint") == endpoint, \
                "the imported camera lost its stream profile"
            evidence["migratedCameras"] = len(cameras)
            code, value = client.request("/api/v1/events?limit=50", cookie=client.cookie)
            assert code == 200, f"imported event service unavailable: {code}"
            events = json.loads(value).get("events", [])
            assert any(item.get("id") == event_id for item in events), \
                "the old event did not survive the import"
            evidence["migratedEvents"] = len(events)
            code, value = client.request("/api/v1/nvr/config", cookie=client.cookie)
            assert code == 200, f"imported NVR configuration unavailable: {code}"
            policies = json.loads(value).get("cameras", [])
            assert any(item.get("id") == "legacy-policy" and item.get("cameraId") == camera_id
                       for item in policies), "the old recording policy was not accepted after import"
            evidence["checks"].append("imported-camera-events-and-recording-policy-are-readable")

            stale = Client(int(origin.rsplit(":", 1)[1]), origin)
            stale.cookie = legacy_cookie
            code, _ = stale.request("/api/v1/auth/session", origin=origin)
            assert code == 401, "an old session cookie was accepted on the imported profile"
            evidence["checks"].append("old-session-cookies-are-not-migrated")
            stop(imported)

            evidence["lastCheckpoint"] = "cleanup"
            leftovers = runtime_processes(runtime, powershell) & seen
            assert not leftovers, f"runtime processes survived the gate: {sorted(leftovers)}"
            evidence["checks"].append("no-runtime-process-survives-after-the-import-cycle")
            evidence["legacyConfigImportQualified"] = True
            evidence["passed"] = True
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"PASS installed old-data import: {len(evidence['checks'])} checks, "
                  f"{evidence['importedFiles']} files")
            return 0
        finally:
            if process is not None:
                try:
                    process.kill()
                except OSError:
                    pass
            report.parent.mkdir(parents=True, exist_ok=True)
            if not report.is_file():
                report.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        return exercise(arguments.runtime.resolve(), arguments.report.resolve())
    except (AssertionError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f"old-data import gate failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
