#!/usr/bin/env python3
"""Native updater contracts: GitHub feed parsing, size/SHA-512 and no silent install."""
from __future__ import annotations

import base64
import contextlib
import hashlib
import http.server
import importlib.util
import json
import io
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load():
    specification = importlib.util.spec_from_file_location(
        "native_updater", ROOT / "native-host/scripts/native_updater.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def serve(directory: Path):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def exercise():
    updater = load()
    assert updater.is_newer("5.0.0", "5.0.1")
    assert updater.is_newer("5.0.0-rc.1", "5.0.0")
    assert not updater.is_newer("5.0.1", "5.0.0")
    assert updater.is_newer("5.1.0-rc.9", "5.1.0-rc.10")
    assert not updater.is_newer("5.1.0-rc.10", "5.1.0-rc.9")
    assert updater.is_newer("5.1.0-alpha.9", "5.1.0-alpha.beta")
    assert updater.is_newer("5.1.0-rc", "5.1.0-rc.1")
    assert not updater.is_newer("5.1.0+build.1", "5.1.0+build.2")
    updater.allowed("https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/latest/download/latest.yml",
                    allow_loopback=False)
    for invalid in ("5.01.0", "5.1.0-rc.01", "5.1.0-rc..1", "../../setup"):
        try:
            updater.version_key(invalid)
        except updater.UpdateError:
            pass
        else:
            raise AssertionError("invalid update version was accepted")
    installer = b"MZ" + b"synthetic-installer" * 1000
    with tempfile.TemporaryDirectory(prefix="webobs-updater-") as temporary:
        base = Path(temporary)
        feed_dir = base / "feed"
        feed_dir.mkdir()
        (feed_dir / "WebOBS-Wall-5.0.1-windows-x64.exe").write_bytes(installer)
        digest = base64.b64encode(hashlib.sha512(installer).digest()).decode()
        (feed_dir / "latest.yml").write_text(
            "version: 5.0.1\nfiles:\n  - url: WebOBS-Wall-5.0.1-windows-x64.exe\n"
            f"    sha512: {digest}\n    size: {len(installer)}\npath: WebOBS-Wall-5.0.1-windows-x64.exe\n",
            encoding="utf-8")
        server, origin = serve(feed_dir)
        try:
            result = updater.check(origin + "/latest.yml", "5.0.0", allow_loopback=True)
            assert result["status"] == "available" and result["version"] == "5.0.1"
            assert result["size"] == len(installer)
            output = base / "updates"
            receipt = updater.download(result, output, allow_loopback=True)
            assert receipt["verified"] is True and (output / receipt["installer"]).read_bytes() == installer
            assert receipt["sha512"] == digest
            cached = output / receipt["installer"]
            # A previously verified receipt must not authorize changed bytes.
            for corruption in (b"MZ-corrupt", b"X" * len(installer), installer + b"extra"):
                cached.write_bytes(corruption)
                with patch.object(updater, "stop_required"), \
                        patch.object(updater, "backup_config") as backup, \
                        patch.object(updater.subprocess, "run") as execute:
                    try:
                        updater.install(result, output, None, base / "data", confirm=True)
                    except updater.UpdateError:
                        pass
                    else:
                        raise AssertionError("updater accepted a corrupted cached installer")
                    assert not execute.called and not backup.called
            cached.write_bytes(installer)
            # Changes during a slow backup must also fail before execution.
            with patch.object(updater, "stop_required"), \
                    patch.object(updater, "backup_config", side_effect=lambda *args, **kwargs:
                                 cached.write_bytes(b"X" * len(installer))), \
                    patch.object(updater.subprocess, "run") as execute:
                try:
                    updater.install(result, output, None, base / "data", confirm=True)
                except updater.UpdateError:
                    pass
                else:
                    raise AssertionError("installer changed during backup was executed")
                assert not execute.called
                assert not (base / "data/run/pending-update.json").exists()
            cached.write_bytes(installer)
            with patch.object(updater, "stop_required"), \
                    patch.object(updater, "backup_config"), \
                    patch.object(updater.subprocess, "run") as execute:
                installed = updater.install(result, output, None, base / "data", confirm=True)
                assert installed["status"] == "installed" and execute.call_count == 1
            for refused in (dict(result, status="current"), dict(result, current="5.0.2")):
                with patch.object(updater.subprocess, "run") as execute:
                    try:
                        updater.install(refused, output, None, base / "data", confirm=True)
                    except updater.UpdateError:
                        pass
                    else:
                        raise AssertionError("same/older unavailable update was executed")
                    assert not execute.called
            config = base / "without-backup/config"
            config.mkdir(parents=True)
            (config / "scene.json").write_text("{}", encoding="utf-8")
            try:
                updater.backup_config(config, config.parent)
            except updater.UpdateError:
                pass
            else:
                raise AssertionError("missing backup material silently allowed an update")
            bad = dict(result, sha512="A" * 100)
            bad_output = base / "bad"
            try:
                updater.download(bad, bad_output, allow_loopback=True)
            except updater.UpdateError:
                pass
            else:
                raise AssertionError("updater accepted an installer with a wrong SHA-512")
            assert not (bad_output / "WebOBS-Wall-5.0.1-windows-x64.exe").exists()
            try:
                updater.install(result, output, None, base / "data", confirm=False, allow_loopback=True)
            except updater.UpdateError:
                pass
            else:
                raise AssertionError("updater installed without explicit confirmation")
            try:
                updater.check(origin + "/latest.yml", "5.0.1", allow_loopback=True)
            except updater.UpdateError:
                pass
            current = updater.check(origin + "/latest.yml", "5.0.2", allow_loopback=True)
            assert current["status"] == "current"
            identity = base / "用户 O'Neil runtime.json"
            identity.write_text(json.dumps({"productIntegration": True, "version": "5.0.1"}))
            assert updater.main(["check", "--feed", origin + "/latest.yml",
                "--current-runtime", str(identity), "--output", str(base / "up-to-date.json"),
                "--allow-insecure-loopback-test", "--exit-code"]) == 2
            assert json.loads((base / "up-to-date.json").read_text())["status"] == "current"
            identity.write_text(json.dumps({"productIntegration": True, "version": "5.0.2"}))
            manifest_path = base / "outdated-check.json"
            manifest_path.write_text(json.dumps(result))
            with patch.object(updater.subprocess, "run") as execute, contextlib.redirect_stderr(io.StringIO()):
                assert updater.main(["install", "--manifest", str(manifest_path),
                    "--output", str(output), "--data-root", str(base / "data"),
                    "--current-runtime", str(identity), "--confirm"]) == 1
                assert not execute.called
            feed_path = feed_dir / "latest.yml"
            stable_feed = feed_path.read_text()
            feed_path.write_text(stable_feed.replace("version: 5.0.1", "version: 5.1.0-rc.1"))
            try:
                updater.check(origin + "/latest.yml", "5.0.0", allow_loopback=True)
            except updater.UpdateError:
                pass
            else:
                raise AssertionError("stable check accepted a prerelease update feed")
            feed_path.write_text(stable_feed)
            for confirmation in (False, True):
                with patch.object(updater.subprocess, "run") as execute, \
                        patch.object(updater, "stop_required", side_effect=updater.UpdateError("product running")):
                    try:
                        updater.restore_backup(base / "unused.wobk", base / "data", confirm=confirmation)
                    except updater.UpdateError:
                        pass
                    else:
                        raise AssertionError("restore ignored confirmation or running product")
                    assert not execute.called
            try:
                updater.check("https://example.invalid/latest.yml", "5.0.0")
            except updater.UpdateError:
                pass
            else:
                raise AssertionError("updater accepted an unapproved update origin")
        finally:
            server.shutdown()
            server.server_close()
        print("PASS native updater feed, version, size/SHA-512, origin and explicit-confirmation contracts")


def exercise_maintenance():
    updater = load()
    with tempfile.TemporaryDirectory(prefix="webobs-maintenance-") as temporary:
        root = Path(temporary)
        runtime = root / "用户 O'Neil install"
        for name in ("python/python.exe", "python/python312.dll", "python/python312.zip",
                     "services/product/native_updater.py", "services/backup/encrypted_backup.py",
                     "services/runtime_support.py", "bin/libsodium.dll", "CHECK-UPDATES.cmd",
                     "python/Lib/site-packages/unneeded-fixture.py"):
            p = runtime / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"inert, never executed")
        profile = root / "profile"
        path_file = root / "maintenance.path"
        receipt = updater.prepare_maintenance(runtime, profile, path_file)
        capsule = Path(path_file.read_text(encoding="utf-8"))
        assert receipt["outsideInstalledRuntime"] is True and not capsule.is_relative_to(runtime)
        assert (capsule / "python/python.exe").read_bytes() == b"inert, never executed"
        assert not (capsule / "python/Lib").exists()
        assert (capsule / ".webobs-maintenance-origin").read_text(encoding="utf-8") == str(runtime.resolve())
        updater.cleanup_maintenance(profile)
        assert capsule.exists(), "unfinished recovery tool was removed"
        with patch.object(updater.sys, "executable", str(capsule / "python/python.exe")):
            updater.finish_maintenance()
        updater.cleanup_maintenance(profile)
        assert not capsule.exists()
        assert (runtime / "python/python.exe").is_file()
        print("PASS external maintenance runtime excludes optional packages and cleans only completed capsules")


def exercise_restore_environment():
    updater = load()
    with tempfile.TemporaryDirectory(prefix="webobs-restore-env-") as temporary:
        root = Path(temporary)
        runtime = root / "runtime"
        for name in ("python/python.exe", "bin/libsodium.dll", "services/backup/encrypted_backup.py"):
            path = runtime / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"inert")
        data = root / "profile"
        (data / "run").mkdir(parents=True)
        (data / "run/backup.key").write_bytes(b"k" * 32)
        archive = root / "fixture.wobk"
        archive.write_bytes(b"archive")
        with patch.object(updater, "stop_required"), patch.object(updater.subprocess, "run") as execute:
            execute.return_value.returncode = 0
            execute.return_value.stderr = ""
            result = updater.restore_backup(archive, data, confirm=True, runtime_root=runtime)
            assert result["configurationRestored"] is True
            environment = execute.call_args.kwargs["env"]
            backup_root = Path(environment["WEBOBS_BACKUP_ROOT"])
            assert backup_root.is_absolute() and backup_root == (data / "backups").resolve()
            assert Path(environment["WEBOBS_LIBSODIUM_LIBRARY"]).is_absolute()
    print("PASS restore supplies an absolute backup root to the packaged CLI")


if __name__ == "__main__":
    exercise()
    exercise_maintenance()
    exercise_restore_environment()
