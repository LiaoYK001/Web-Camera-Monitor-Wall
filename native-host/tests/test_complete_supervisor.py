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
        finally:
            supervisor.stop()
            if previous is None:
                os.environ.pop("WEBOBS_PRODUCT_TEST_ROOT", None)
            else:
                os.environ["WEBOBS_PRODUCT_TEST_ROOT"] = previous
        print("PASS complete supervisor paths, services, backup key and on-demand Program output policy")


if __name__ == "__main__":
    exercise()
