#!/usr/bin/env python3
"""Complete product staging/supervisor contracts without starting media services."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def exercise():
    with tempfile.TemporaryDirectory(prefix="webobs-complete-supervisor-") as temporary:
        private = Path(temporary)
        runtime = private / "runtime"
        root = private / "profile"
        for marker in ("services/events/event_service.py", "services/nvr/nvr_service.py",
                       "services/v2/client_control_service.py", "bin/go2rtc.exe",
                       "bin/node.exe", "bin/webobs-online-source.exe",
                       "services/desktop-tools/private_directory.py"):
            path = runtime / marker
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fixture\n", encoding="utf-8")
        (runtime / "webobs-native-prototype.json").write_text(json.dumps({
            "obsCommit": "fb4d98bf88fae5fc85cb11fc57f7c5e309282194",
            "version": "5.0.0-dev.fixture", "productIntegration": True,
            "publicationForbidden": True}), encoding="utf-8")
        shutil.copy2(ROOT / "desktop/python/private_directory.py",
                     runtime / "services/desktop-tools/private_directory.py")
        # The packaged backup service is what startup loads to converge a
        # restore that was killed between its two directory swaps.
        backup_service = runtime / "services/backup/encrypted_backup.py"
        backup_service.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "runtime_support.py", runtime / "services/runtime_support.py")
        shutil.copy2(ROOT / "backup/encrypted_backup.py", backup_service)
        supervisor_module = load("complete_product_supervisor",
                                 ROOT / "native-host/scripts/product_supervisor.py")
        previous = os.environ.get("WEBOBS_PRODUCT_TEST_ROOT")
        os.environ["WEBOBS_PRODUCT_TEST_ROOT"] = str(root)
        supervisor = supervisor_module.ProductSupervisor(runtime, root)
        try:
            assert supervisor.prepare() is True
            assert supervisor.complete is True
            for name in ("config", "recordings", "recordings/program", "backups", "snapshots", "config/go2rtc",
                         "config/keys", "config/node"):
                assert (root / name).is_dir(), f"complete profile missing {name}"
            key = root / "run/backup.key"
            assert key.is_file() and not key.is_symlink() and key.stat().st_size == 32
            environment = supervisor.environment
            assert environment["WEBOBS_NVR_ENABLED"] == "true"
            assert environment["WEBOBS_GO2RTC_ENABLED"] == "true"
            # webobsd must remain Direct-only: composite_enabled flips the control
            # server into OBS composition and it fails to start on the native
            # runtime. Program recording/publishing belong to the native host instead.
            assert environment["WEBOBS_COMPOSITE_ENABLED"] == "false"
            assert Path(environment["WEBOBS_FFMPEG_PATH"]).name == "ffmpeg.exe"
            assert Path(environment["WEBOBS_FFMPEG_PATH"]).parent.name == "bin"
            assert Path(environment["WEBOBS_FFPROBE_PATH"]).name == "ffprobe.exe"
            assert Path(environment["WEBOBS_NODE_PATH"]).name == "node.exe"
            assert environment["WEBOBS_NVR_STORAGE"] == str(root / "recordings")
            assert environment["WEBOBS_BACKUP_KEY_FILE"] == str(key)
            assert environment["WEBOBS_GO2RTC_CONFIG"] == str(root / "config/go2rtc/go2rtc.yaml")
            assert "WEBOBS_EVENTS_INTERNAL_PORT" not in environment, "per-boot ports must not leak from prepare"
            # A restore killed between its two directory swaps leaves the restored
            # configuration landed while the restored OBS profile is still staged.
            # The next ordinary start must finish that pair while holding the data
            # lock, before any product directory or profile file is created, and it
            # must keep the previous pair instead of deleting it.
            supervisor.stop()
            previous_config = root / ".webobs-rollback-previous"
            previous_native = root / ".webobs-native-rollback-previous"
            previous_config.mkdir()
            previous_native.mkdir()
            (previous_config / "keep.json").write_text("previous", encoding="utf-8")
            (previous_native / "obs-studio/user.ini").parent.mkdir()
            (previous_native / "obs-studio/user.ini").write_text("[Previous]\n", encoding="utf-8")
            # The first prepare() created the live directories; a killed restore
            # has already replaced the configuration half and moved the live OBS
            # profile into the rollback path above.
            landed_config = root / "config"
            shutil.rmtree(landed_config)
            landed_config.mkdir()
            (landed_config / "restored.json").write_text("restored", encoding="utf-8")
            shutil.rmtree(root / "native-profile")
            staged_native = root / ".webobs-native-restore-staged"
            staged_native.mkdir()
            (staged_native / "obs-studio/user.ini").parent.mkdir()
            (staged_native / "obs-studio/user.ini").write_text("[Restored]\n", encoding="utf-8")
            (root / ".webobs-restore-journal.json").write_text(json.dumps({
                "schema": 1, "state": "prepared", "createdAt": "20261118T000000Z",
                "archive": str(root / "backups/snapshot.tar"), "archiveSha256": "0" * 64,
                "configRoot": str(root / "config"),
                "configActivated": str(root / ".webobs-restore-landed"),
                "configRollback": str(previous_config), "nativeProfile": str(root / "native-profile"),
                "nativeActivated": str(staged_native), "nativeRollback": str(previous_native)},
                sort_keys=True), encoding="utf-8")
            second = supervisor_module.ProductSupervisor(runtime, root)
            try:
                assert second.prepare() is True, "product start refused an interrupted restore"
                assert not (root / ".webobs-restore-journal.json").exists(), \
                    "startup left the restore journal behind"
                assert not staged_native.exists(), "the pending OBS profile was never landed"
                assert (root / "config/restored.json").read_text(encoding="utf-8") == "restored", \
                    "the restored configuration pair changed"
                assert (root / "native-profile/obs-studio/user.ini").read_text(
                    encoding="utf-8") == "[Restored]\n", \
                    "the OBS profile did not move with the restored configuration"
                assert (previous_config / "keep.json").read_text(encoding="utf-8") == "previous" \
                    and (previous_native / "obs-studio/user.ini").is_file(), \
                    "startup deleted the previous configuration and profile pair"
                assert not (root / "run/restore-recovery.json").exists(), \
                    "a converged restore left a failure marker behind"
            finally:
                second.stop()
        finally:
            supervisor.stop()
            if previous is None:
                os.environ.pop("WEBOBS_PRODUCT_TEST_ROOT", None)
            else:
                os.environ["WEBOBS_PRODUCT_TEST_ROOT"] = previous
        print("PASS complete supervisor paths, services, backup key and on-demand Program output policy")


if __name__ == "__main__":
    exercise()
