#!/usr/bin/env python3
"""Installed-runtime recovery of a restore killed between its two directory swaps.

The packaged backup service swaps ``config`` and ``native-profile`` as one pair
and journals that swap. This gate runs the real restore from the installed
runtime, terminates the restore process after the configuration half landed and
before the OBS profile half lands, then starts the installed product and requires
the pair to converge, to stay retryable, and to keep the previous data. A
configuration-only archive from an older release must keep the existing native
profile. No real camera, migration or full-product qualification is claimed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from product_windows import alive, read_json, wait_for

CONFIG_MARKER = "windows-restore-marker.txt"
NATIVE_MARKER = "obs-studio/windows-restore-marker.txt"
CHILD = """
import importlib.util, json, os, pathlib, sys, time
runtime, profile, archive, key, sentinel, mode = map(pathlib.Path, sys.argv[1:7])
os.environ["WEBOBS_LIBSODIUM_LIBRARY"] = str(runtime / "bin/libsodium.dll")
sys.path.insert(0, str(runtime / "services"))
spec = importlib.util.spec_from_file_location("packaged_backup_restore",
    runtime / "services/backup/encrypted_backup.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
sodium = module.SodiumStream()
config_root = profile / "config"
original = os.replace
if str(mode) == "interrupt":
    def guarded(source, destination):
        result = original(source, destination)
        if pathlib.Path(destination) == config_root:
            sentinel.write_text("config-landed", encoding="utf-8")
            # Bounded window so the parent can terminate this process reliably
            # between the two swaps; the termination itself is real.
            time.sleep(30)
        return result
    os.replace = guarded
native = None if str(mode) == "config-only" else profile / "native-profile"
try:
    module.restore(config_root, archive, key, sodium, True, native_profile=native)
except BaseException as error:
    sys.stderr.write(f"{type(error).__name__}: {str(error)[:200]}\\n")
    raise
"""


def load(module_name, path):
    specification = importlib.util.spec_from_file_location(module_name, path)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def child_processes(powershell, pid):
    listing = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
        f"Get-CimInstance Win32_Process -Filter 'ParentProcessID={int(pid)}' | "
        'ForEach-Object { "$($_.ProcessId)|$($_.Name)" }'],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
    assert listing.returncode == 0, f"could not enumerate product children: {listing.stderr[:200]}"
    children = []
    for line in listing.stdout.splitlines():
        pid_text, _, name = line.partition("|")
        if pid_text.strip().isdigit():
            children.append((int(pid_text), name.strip().lower()))
    return children


def run_restore(runtime_python, runtime, profile, archive, key, sentinel, mode, private):
    script = private / f"restore-{mode}.py"
    script.write_text(CHILD, encoding="utf-8")
    log = (private / f"restore-{mode}.log").open("w", encoding="utf-8")
    process = subprocess.Popen([str(runtime_python), "-B", str(script), str(runtime), str(profile),
        str(archive), str(key), str(sentinel), mode], stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL)
    return process, log


def exercise(runtime, profile_parent, report):
    powershell = shutil.which("pwsh")
    assert powershell, "test-side PowerShell 7 required"
    runtime_python = runtime / "python/python.exe"
    backup_service = runtime / "services/backup/encrypted_backup.py"
    supervisor_service = runtime / "services/product/supervisor.py"
    entry = runtime / "bin/webobs-wall.exe"
    sodium_library = runtime / "bin/libsodium.dll"
    for required in (runtime_python, backup_service, supervisor_service, entry, sodium_library):
        assert required.is_file(), f"installed runtime is missing {required.name}"
    os.environ["WEBOBS_LIBSODIUM_LIBRARY"] = str(sodium_library)
    backup = load("installed_backup_restore", backup_service)
    sodium = backup.SodiumStream()
    evidence = {"schema": 1, "kind": "native-backup-restore-recovery", "passed": False, "checks": [],
        "installedProductQualified": False, "mediaQualified": False, "hardwareDecodeVerified": False,
        "fullFeatureMigrationQualified": False}
    def marker_value(path):
        return path.read_text(encoding="utf-8").strip() if path.is_file() else None
    def set_marker(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n", encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="WebOBS 恢复一致性-") as temporary:
        private = Path(temporary)
        profile = profile_parent / "restore-profile"
        config, native = profile / "config", profile / "native-profile"
        config.mkdir(parents=True, exist_ok=True)
        (native / "obs-studio").mkdir(parents=True, exist_ok=True)
        set_marker(config / CONFIG_MARKER, "backup")
        set_marker(native / NATIVE_MARKER, "backup")
        (config / "workspace-fixture.json").write_text(json.dumps({"schema": 1, "cameras": []}),
            encoding="utf-8")
        key_file = private / "backup.key"
        key_file.write_bytes(secrets.token_bytes(32))
        backups = profile / "backups"
        archive = backup.create(config, backups, key_file, sodium, native_profile=native)
        pair_archive_sha = backup.file_sha256(archive)
        set_marker(config / CONFIG_MARKER, "live")
        set_marker(native / NATIVE_MARKER, "live")

        phase = "interrupted-swap"
        sentinel = private / "swap-sentinel.txt"
        restore_process, log = run_restore(runtime_python, runtime, profile, archive, key_file,
            sentinel, "interrupt", private)
        wait_for(lambda: sentinel.is_file(), "restore did not land the configuration half", timeout=40)
        journal = profile / backup.JOURNAL_NAME
        assert journal.is_file(), "the restore journal did not survive the swap window"
        payload = json.loads(journal.read_text(encoding="utf-8"))
        assert payload.get("state") == "prepared", "journal is not the prepared swap state"
        staged = Path(payload["nativeActivated"])
        assert staged.is_dir(), "the pending OBS profile half was not staged"
        assert not (native / NATIVE_MARKER).is_file(), "the OBS profile half already landed; not a mid-swap kill"
        restore_process.kill()
        restore_process.wait(timeout=30)
        log.close()
        assert restore_process.returncode != 0, "terminated restore reported success"
        evidence["interruptedRestoreExitCode"] = restore_process.returncode
        evidence["journalState"] = payload.get("state")
        evidence["checks"].append("restore-process-terminated-between-the-two-swaps")

        phase = "first-installed-start"
        os.environ["WEBOBS_PRODUCT_TEST_ROOT"] = str(profile)
        supervisor = load("installed_supervisor_recovery", supervisor_service)
        owner = supervisor.ProductSupervisor(runtime, profile)
        try:
            assert owner.prepare() is True, "installed product start refused to take the data root"
        finally:
            owner.stop()
        assert not journal.exists(), "installed startup left the restore journal behind"
        assert not staged.exists(), "installed startup never landed the pending OBS profile"
        assert not (profile / "run/restore-recovery.json").exists(), \
            "installed startup recorded a recovery failure"
        assert marker_value(config / CONFIG_MARKER) == "backup", \
            "configuration did not reach the restored pair"
        assert marker_value(native / NATIVE_MARKER) == "backup", \
            "the OBS profile did not move with the restored configuration"
        rollback = Path(payload["configRollback"])
        rollback_native = Path(payload["nativeRollback"])
        assert marker_value(rollback / CONFIG_MARKER) == "live" \
            and marker_value(rollback_native / NATIVE_MARKER) == "live", \
            "startup deleted the previous pair instead of keeping it retryable"
        evidence["retainedRollbackPair"] = {"config": marker_value(rollback / CONFIG_MARKER),
            "nativeProfile": marker_value(rollback_native / NATIVE_MARKER)}
        evidence["checks"].append("first-installed-start-converges-the-pair-and-keeps-previous-data")

        phase = "retry-full-restore"
        set_marker(config / CONFIG_MARKER, "live-again")
        set_marker(native / NATIVE_MARKER, "live-again")
        retry_process, retry_log = run_restore(runtime_python, runtime, profile, archive, key_file,
            private / "unused-sentinel.txt", "complete", private)
        assert retry_process.wait(timeout=180) == 0, "retrying the restore after the interrupted one failed"
        retry_log.close()
        assert not journal.exists(), "retrying the restore left a journal behind"
        assert marker_value(config / CONFIG_MARKER) == "backup" \
            and marker_value(native / NATIVE_MARKER) == "backup", \
            "retry did not restore both halves of the pair"
        evidence["checks"].append("interrupted-restore-is-retryable-with-the-same-archive")
        assert backup.file_sha256(archive) == pair_archive_sha, "archive bytes changed after recovery"

        phase = "legacy-config-only-archive"
        legacy_archive = backup.create(config, backups, key_file, sodium)
        set_marker(config / CONFIG_MARKER, "legacy-live")
        set_marker(native / NATIVE_MARKER, "kept-native")
        legacy_process, legacy_log = run_restore(runtime_python, runtime, profile, archive, key_file,
            private / "unused-legacy-sentinel.txt", "config-only", private)
        assert legacy_process.wait(timeout=180) == 0, "a configuration-only archive could not be restored"
        legacy_log.close()
        assert marker_value(config / CONFIG_MARKER) == "backup", \
            "configuration-only restore did not restore the configuration"
        assert marker_value(native / NATIVE_MARKER) == "kept-native", \
            "configuration-only restore replaced the existing OBS profile"
        assert not journal.exists(), "configuration-only restore left a journal behind"
        evidence["legacyArchiveKeptNativeProfile"] = marker_value(native / NATIVE_MARKER)
        evidence["checks"].append("configuration-only-archive-keeps-the-existing-native-profile")

        phase = "installed-entry-after-recovery"
        status_path = profile / "run/native-status.json"
        def status():
            return read_json(status_path) if status_path.is_file() else {}
        previous_boot = status().get("bootId")
        environment = dict(os.environ)
        environment["WEBOBS_PRODUCT_TEST_ROOT"] = str(profile)
        launched = subprocess.Popen([str(entry)], env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def running():
            assert launched.poll() is None, "installed entry exited after a recovered restore"
            value = status()
            return value if value.get("phase") == "running" and isinstance(value.get("bootId"), str) \
                and re.fullmatch(r"[a-f0-9]{32}", value["bootId"]) and value["bootId"] != previous_boot else None
        value = wait_for(running, "installed entry did not start after the recovered pair", timeout=75)
        owned = [value["ownerPid"], *[service["pid"] for service in value.get("services", [])]]
        assert marker_value(config / CONFIG_MARKER) == "backup" \
            and marker_value(native / NATIVE_MARKER) == "backup", \
            "the running installed product did not read the recovered pair"
        assert not journal.exists(), "running product recreated the restore journal"
        launched.kill()
        launched.wait(timeout=30)
        wait_for(lambda: not any(alive(pid) for pid in owned),
            "product processes survived the gate close", timeout=30)
        survivors = [name for pid, name in child_processes(powershell, os.getpid())
            if name in ("obs64.exe", "webobsd.exe", "webobs-wall.exe")]
        assert survivors == [], f"product processes survived: {survivors}"
        evidence["checks"].append("installed-entry-starts-on-the-recovered-pair")
        evidence["passed"] = True
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(f"PASS installed restore-pair recovery: {len(evidence['checks'])} checks")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--profile-parent", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    exercise(arguments.runtime.absolute(), arguments.profile_parent.absolute(),
        arguments.report.absolute())


if __name__ == "__main__":
    main()
