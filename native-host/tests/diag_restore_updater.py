"""Temporary diagnostic: run the installed updater backup/restore path."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback


runtime = Path(sys.argv[1]).resolve(strict=True)
profile = Path(sys.argv[2]).resolve(strict=True)
target = Path(sys.argv[3]).resolve()
spec = importlib.util.spec_from_file_location(
    "diagnostic_installed_updater", runtime / "services/product/native_updater.py")
assert spec and spec.loader
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)
try:
    updater.backup_config(profile / "config", profile, runtime_root=runtime)
    archives = sorted((profile / "backups").glob("*.wobk"), key=lambda path: path.stat().st_mtime,
                      reverse=True)
    assert archives, "backup archive missing"
    (target / "run").mkdir(parents=True, exist_ok=True)
    (target / "config").mkdir()
    (target / "config/stale-marker.json").write_text("{}", encoding="utf-8")
    shutil.copy2(profile / "run/backup.key", target / "run/backup.key")
    result = updater.restore_backup(archives[0], target, confirm=True, runtime_root=runtime)
    print(json.dumps(result))
except Exception:
    replay = subprocess.run([
        str(runtime / "python/python.exe"), "-B", str(runtime / "services/backup/encrypted_backup.py"),
        "restore", str(archives[0].resolve()), "--config-root", str((target / "config").resolve()),
        "--key-file", str((target / "run/backup.key").resolve())],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "WEBOBS_RESTORE_CONFIRM": "replace-config",
             "WEBOBS_LIBSODIUM_LIBRARY": str(runtime / "bin/libsodium.dll")})
    print("replay exit", replay.returncode)
    print(replay.stderr[-4096:])
    traceback.print_exc()
    raise
