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
elif str(mode) == "interrupt-native":
    write_journal = module._write_journal
    def guarded_journal(path, value):
        write_journal(path, value)
        if value.get("nativeRollback") is None:
            return
        # The previous OBS profile has moved aside and the journal now records
        # both previous halves, while neither live path stands and the
        # configuration half has not landed yet: this is the other half of the
        # swap window. The sentinel must follow the fsync'ed journal write -
        # pausing inside os.replace stopped the child before nativeRollback was
        # persisted, so rc.72's kill lost the native reference instead of
        # proving the product's prepared-state recovery.
        sentinel.write_text("native-recorded", encoding="utf-8")
        time.sleep(30)
    module._write_journal = guarded_journal
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
        try:
            wait_for(lambda: sentinel.is_file(), "restore did not land the configuration half", timeout=40)
            journal = profile / backup.JOURNAL_NAME
            assert journal.is_file(), "the restore journal did not survive the swap window"
            payload = json.loads(journal.read_text(encoding="utf-8"))
            assert payload.get("state") == "prepared", "journal is not the prepared swap state"
            staged = Path(payload["nativeActivated"])
            assert staged.is_dir(), "the pending OBS profile half was not staged"
            assert not (native / NATIVE_MARKER).is_file(), "the OBS profile half already landed; not a mid-swap kill"
        finally:
            # rc.72 proved that an assertion failing while the sleeping child still
            # holds its log turns cleanup into WinError 32 and hides the real reason.
            restore_process.kill()
            restore_process.wait(timeout=30)
            log.close()
        assert restore_process.returncode != 0, "terminated restore reported success"
        evidence["interruptedRestoreExitCode"] = restore_process.returncode
        evidence["journalState"] = payload.get("state")
        evidence["checks"].append("restore-process-terminated-between-the-two-swaps")

        phase = "first-installed-start"
        # This is the user's scenario: a killed restore leaves the pair split, and the
        # next Start-Menu launch is the first thing that can converge it. Launch the real
        # installed entry (not a dedicated command) so the ordering is proved through the
        # product's own start path: exclusive data lock, journal convergence, and only then
        # directory creation plus reading the configuration and the OBS profile.
        status_path = profile / "run/native-status.json"

        def status():
            return read_json(status_path) if status_path.is_file() else {}

        environment = dict(os.environ)
        environment["WEBOBS_PRODUCT_TEST_ROOT"] = str(profile)
        # native-status.json reaches ``phase=running`` the moment the supervisor has
        # spawned the frontend (product_supervisor.py publishes right after the Popen);
        # the host writes product-state.json only once libobs has loaded the product
        # module and bound its session, carrying this boot's pid and bootId. The two
        # writes are deliberately asynchronous, so both waits share the 120 s launch
        # budget computed before the entry starts: the observation is awaited, never
        # sampled at the instant the status file flipped.
        launch_deadline = time.monotonic() + 120
        launch_started = time.monotonic()
        launched = subprocess.Popen([str(entry)], env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def remaining():
            return max(0.1, launch_deadline - time.monotonic())
        def first_running():
            assert launched.poll() is None, \
                f"the installed entry refused to start over the interrupted restore ({launched.returncode})"
            value = status()
            return value if value.get("phase") == "running" and isinstance(value.get("bootId"), str) \
                and re.fullmatch(r"[a-f0-9]{32}", value["bootId"]) else None
        started = None
        owned = []
        try:
            started = wait_for(first_running,
                "the installed entry did not converge the interrupted restore and start", timeout=remaining())
            assert not journal.exists(), "the installed entry left the interrupted restore journal behind"
            assert not staged.exists(), "the installed entry never landed the pending OBS profile half"
            assert not (profile / "run/restore-recovery.json").exists(), \
                "the installed entry recorded a bounded recovery failure instead of converging"
            assert marker_value(config / CONFIG_MARKER) == "backup", \
                "the installed entry started without the restored configuration"
            assert marker_value(native / NATIVE_MARKER) == "backup", \
                "the installed entry started on a mismatched OBS profile half"
            # rc.71 sampled this at the tick the status file flipped and saw zero files.
            # Wait for exactly one readable observation that belongs to this boot, and
            # record which outcome the wait saw: zero, several, unreadable or stale boot.
            frontend_pid = next((service["pid"] for service in started.get("services", [])
                if service.get("name") == "frontend"), 0)
            assert frontend_pid, "native-status.json did not report the frontend child of this boot"
            def one_host_state():
                paths = list((profile / "native-profile").rglob("product-state.json"))
                if len(paths) != 1:
                    evidence["lastStateObservation"] = {"code": "state-file-count", "files": len(paths)}
                    return None
                try:
                    value = read_json(paths[0])
                except (OSError, ValueError):
                    evidence["lastStateObservation"] = {"code": "state-file-unreadable"}
                    return None
                if value.get("pid") != str(frontend_pid) or value.get("bootId") != started["bootId"]:
                    evidence["lastStateObservation"] = {"code": "state-from-other-boot",
                        "pidMatched": value.get("pid") == str(frontend_pid),
                        "bootIdMatched": value.get("bootId") == started["bootId"]}
                    return None
                evidence["lastStateObservation"] = {"code": "state-published", "phase": value.get("phase")}
                return value
            host_state = wait_for(one_host_state, lambda:
                "the running host did not publish one product state for this boot: "
                + json.dumps(evidence.get("lastStateObservation") or {}), timeout=remaining())
            rollback = Path(payload["configRollback"])
            rollback_native = Path(payload["nativeRollback"])
            assert marker_value(rollback / CONFIG_MARKER) == "live" \
                and marker_value(rollback_native / NATIVE_MARKER) == "live", \
                "the installed entry deleted the previous pair instead of keeping it retryable"
            evidence["retainedRollbackPair"] = {"config": marker_value(rollback / CONFIG_MARKER),
                "nativeProfile": marker_value(rollback_native / NATIVE_MARKER)}
            owned = [started["ownerPid"], *[service["pid"] for service in started.get("services", [])]]
            evidence["firstInstalledStart"] = {"bootId": started["bootId"], "phase": started["phase"],
                "hostStatePhase": host_state.get("phase"),
                "hostStateMsAfterLaunch": int((time.monotonic() - launch_started) * 1000),
                "services": sorted(service["name"] for service in started.get("services", []))}
            evidence["checks"].append("first-installed-start-converges-the-pair-and-keeps-previous-data")
        finally:
            launched.kill()
            launched.wait(timeout=30)
        if owned:
            wait_for(lambda: not any(alive(pid) for pid in owned),
                "the interrupted-restore first start left its own product processes alive", timeout=30)
        listing = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
            "Get-Process | ForEach-Object { $_.ProcessName }"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=25)
        survivors = {name.strip().lower() for name in listing.stdout.splitlines()} & {
            "webobs-wall", "webobsd", "obs64", "caddy", "mediamtx", "go2rtc"}
        assert survivors == set(), f"product processes survived the first-start check: {sorted(survivors)}"
        evidence["checks"].append("first-installed-start-leaves-no-product-process-behind")

        phase = "interrupted-native-swap"
        # The other half of the swap window: the previous OBS profile has already
        # moved aside while the configuration half has not landed. Recovering only
        # the configuration would start the product on a missing profile and leave
        # the previous profile parked with nothing to claim it.
        set_marker(config / CONFIG_MARKER, "live-before-native-swap")
        set_marker(native / NATIVE_MARKER, "live-before-native-swap")
        native_sentinel = private / "native-swap-sentinel.txt"
        native_process, native_log = run_restore(runtime_python, runtime, profile, archive, key_file,
            native_sentinel, "interrupt-native", private)
        try:
            wait_for(lambda: native_sentinel.is_file(), "restore did not swap the OBS profile half out",
                timeout=40)
            assert journal.is_file(), "the restore journal did not survive the native swap window"
            native_payload = json.loads(journal.read_text(encoding="utf-8"))
            assert native_payload.get("configRollback") and native_payload.get("nativeRollback"), \
                "journal does not record both previous halves"
            assert not config.exists() and not native.exists(), \
                "one half was still live while the journal claims both were swapped out"
        finally:
            native_process.kill()
            native_process.wait(timeout=30)
            native_log.close()
        assert native_process.returncode != 0, "terminated native-swap restore reported success"
        evidence["nativeSwapExitCode"] = native_process.returncode
        evidence["checks"].append("restore-process-terminated-after-the-native-swap")

        phase = "second-installed-start"
        environment = dict(os.environ)
        environment["WEBOBS_PRODUCT_TEST_ROOT"] = str(profile)
        launched = subprocess.Popen([str(entry)], env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def native_rolled_back():
            assert launched.poll() is None, \
                f"the installed entry refused to start over a native-half swap ({launched.returncode})"
            value = status()
            return value if value.get("phase") == "running" and isinstance(value.get("bootId"), str) \
                and re.fullmatch(r"[a-f0-9]{32}", value["bootId"]) else None
        owned = []
        try:
            started = wait_for(native_rolled_back,
                "the installed entry did not return both halves of the previous pair", timeout=120)
            assert not journal.exists(), "the installed entry left the native-swap journal behind"
            assert marker_value(config / CONFIG_MARKER) == "live-before-native-swap", \
                "the installed entry did not restore the previous configuration half"
            assert marker_value(native / NATIVE_MARKER) == "live-before-native-swap", \
                "the installed entry left the previous OBS profile parked"
            assert not any(list(profile.glob(".webobs-restore-*"))
                + list(profile.glob(".webobs-native-restore-*"))), \
                "the archive staging survived the native-swap rollback"
            parked_native = Path(native_payload["nativeRollback"])
            assert not parked_native.exists(), \
                "the previous OBS profile stayed parked instead of becoming live again"
            owned = [started["ownerPid"], *[service["pid"] for service in started.get("services", [])]]
            evidence["checks"].append("native-swap-interruption-returns-the-previous-pair")
        finally:
            launched.kill()
            launched.wait(timeout=30)
        wait_for(lambda: not any(alive(pid) for pid in owned),
            "product processes survived the native-swap rollback start", timeout=30)
        evidence["checks"].append("native-swap-rollback-start-leaves-no-product-process-behind")

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
        # A paired archive must never be half-restored. The packaged service refuses it
        # when the caller does not name the OBS profile, so both halves stay as they are.
        refused, refused_log = run_restore(runtime_python, runtime, profile, archive, key_file,
            private / "unused-paired-sentinel.txt", "config-only", private)
        assert refused.wait(timeout=120) != 0, \
            "a paired archive was half-restored without naming the OBS profile"
        refused_log.close()
        assert marker_value(config / CONFIG_MARKER) == "legacy-live" \
            and marker_value(native / NATIVE_MARKER) == "kept-native", \
            "the refused paired restore still changed one half of the pair"
        assert not journal.exists(), "the refused paired restore left a journal behind"
        assert not any(list(profile.glob(".webobs-restore-*")) + list(profile.glob(".webobs-native-restore-*"))
            + list(profile.glob(".webobs-decrypt-*"))), "the refused paired restore leaked staging directories"
        evidence["checks"].append("paired-archive-refuses-a-half-restore")

        legacy_process, legacy_log = run_restore(runtime_python, runtime, profile, legacy_archive, key_file,
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
