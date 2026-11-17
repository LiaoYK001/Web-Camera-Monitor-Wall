"""Exercise the installed native updater with a private loopback feed and NSIS.

Only the disposable installation/profile explicitly supplied by the parent gate
may be changed. No public feed, user profile or published installer is modified.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import closing
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import threading


def exercise(runtime: Path, installer: Path, profile: Path, installed: Path, report: Path):
    if os.name != "nt":
        raise ValueError("actual update gate requires Windows")
    if not installed.is_dir() or not profile.is_dir():
        raise ValueError("explicit disposable installed runtime and profile required")
    for path in (runtime, installer, profile, installed, report):
        if path.is_symlink():
            raise ValueError("linked update fixture")
    current = json.loads((installed / "webobs-native-prototype.json").read_text())["version"]
    components = json.loads((runtime / "product-components.json").read_text())
    updater_path = installed / "services/product/native_updater.py"
    spec = importlib.util.spec_from_file_location("installed_updater", updater_path)
    updater = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updater)
    version = installer.name.removeprefix("WebOBS-Wall-").removesuffix("-windows-x64-SETUP.exe")
    digest = hashlib.sha512()
    with installer.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    encoded = base64.b64encode(digest.digest()).decode("ascii")
    feed = (f"version: {version}\nfiles:\n  - url: {installer.name}\n"
            f"    sha512: {encoded}\n    size: {installer.stat().st_size}\n")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/latest.yml":
                data = feed.encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif self.path == "/" + installer.name:
                self.send_response(200)
                self.send_header("Content-Length", str(installer.stat().st_size))
                self.end_headers()
                with installer.open("rb") as source:
                    for block in iter(lambda: source.read(1 << 20), b""):
                        self.wfile.write(block)
            else:
                self.send_error(404)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    evidence = {"schema": 1, "kind": "installed-native-updater",
                "sourceRevision": components["sourceRevision"], "version": current,
                "upgradeVersion": version, "passed": False, "loopbackFeedOnly": True,
                "sameSourceQualificationFixture": True}
    try:
        with tempfile.TemporaryDirectory(prefix="WebOBS update fixture-") as private:
            output = Path(private) / "download"
            manifest = updater.check(f"http://127.0.0.1:{server.server_port}/latest.yml",
                                     current, allow_loopback=True)
            assert manifest["status"] == "available"
            receipt = updater.download(manifest, output, allow_loopback=True)
            cached = output / receipt["installer"]
            with cached.open("r+b") as target:
                first = target.read(1)
                target.seek(0)
                target.write(bytes([first[0] ^ 0xFF]))
            try:
                updater.install(manifest, output, installed, profile, confirm=True,
                                allow_loopback=True)
            except updater.UpdateError:
                pass
            else:
                raise AssertionError("installed updater accepted changed cache bytes")
            evidence["changedCacheRejected"] = True
            assert json.loads((installed / "webobs-native-prototype.json").read_text())["version"] == current
            with cached.open("r+b") as target:
                target.write(first)
            before = set((profile / "backups").rglob("*"))
            maintenance_path = Path(private) / "maintenance.path"
            prepared = subprocess.run([str(installed / "python/python.exe"), "-B", str(updater_path),
                "prepare-maintenance", "--runtime", str(installed), "--data-root", str(profile),
                "--output", str(maintenance_path)], capture_output=True, text=True, timeout=90)
            assert prepared.returncode == 0, "installed maintenance bootstrap failed"
            capsule = Path(maintenance_path.read_text(encoding="utf-8"))
            assert not capsule.is_relative_to(installed), "updater still runs inside the overwritten installation"
            update_manifest = Path(private) / "update.json"
            update_manifest.write_text(json.dumps(manifest), encoding="utf-8")
            executed = subprocess.run([str(capsule / "python/python.exe"), "-B",
                str(capsule / "services/product/native_updater.py"), "install",
                "--manifest", str(update_manifest), "--output", str(output),
                "--install-dir", str(installed), "--current-runtime", str(installed / "webobs-native-prototype.json"),
                "--data-root", str(profile), "--confirm", "--allow-insecure-loopback-test"],
                capture_output=True, text=True, timeout=1800)
            assert executed.returncode == 0, "independent installed updater failed"
            outcome = json.loads(executed.stdout)
            assert outcome["status"] == "installed"
            updater.cleanup_maintenance(profile)
            assert not capsule.exists(), "completed maintenance runtime did not clean up"
            evidence.update(independentMaintenanceRuntime=True, maintenanceCleaned=True,
                            maintenanceRuntimeBytes=json.loads(prepared.stdout)["copiedBytes"])
            assert any(p.is_file() for p in set((profile / "backups").rglob("*")) - before), \
                "installed updater did not produce an encrypted pre-update backup"
            archives = [p for p in set((profile / "backups").rglob("*.wobk")) - before if p.is_file()]
            assert len(archives) == 1, "pre-update encrypted backup is ambiguous"
            # Restore into a separate disposable target using the same original
            # key. Never replace the retained profile used by the install gate.
            restored_root = Path(private) / "restore-probe"
            (restored_root / "run").mkdir(parents=True)
            shutil.copy2(profile / "run/backup.key", restored_root / "run/backup.key")
            (restored_root / "config").mkdir()
            (restored_root / "config/stale-marker.json").write_text("{}")
            restored = updater.restore_backup(archives[0], restored_root, confirm=True)
            assert restored["configurationRestored"] is True
            assert not (restored_root / "config/stale-marker.json").exists()
            def database_fingerprint(path):
                with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
                    assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                    version = database.execute("PRAGMA user_version").fetchone()
                    # SQLite backup may rewrite page headers; compare schema
                    # and rows, never expose account/secret contents in reports.
                    return version, hashlib.sha256("\n".join(database.iterdump()).encode()).digest()
            for name in ("cluster.sqlite3", "cameras.db"):
                assert database_fingerprint(restored_root / "config" / name) == \
                    database_fingerprint(profile / "config" / name), \
                    "restored account/camera database differs from retained data"
            assert json.loads((installed / "webobs-native-prototype.json").read_text())["version"] == version
            assert json.loads((installed / "product-components.json").read_text())["version"] == version
            evidence.update(downloadVerified=True, backupCreated=True, actualNsisExecuted=True,
                            actualRuntimeVersionChanged=True, encryptedRestoreVerified=True, passed=True)
    finally:
        server.shutdown()
        server.server_close()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runtime", "installer", "profile", "installed", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    exercise(args.runtime.resolve(), args.installer.resolve(), args.profile.resolve(),
             args.installed.resolve(), args.report.resolve())
