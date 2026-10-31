#!/usr/bin/env python3
"""Actual Windows Qt/plugin/portable startup smoke; never camera qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys


def fingerprint(root: Path) -> dict:
    """Private before/after comparison, never print paths or file contents."""
    if not root.exists():
        return {}
    if root.is_symlink():
        raise ValueError("Refuse an external OBS profile symlink")
    state = {}
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("Refuse symlinks in the external OBS profile")
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if len(state) >= 10000 or total > 64 * 1024 * 1024:
            raise ValueError("External OBS profile too large for bounded isolation smoke; use a dedicated Windows test account")
        state[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return state


def run(runtime: Path, result: Path) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("The Qt startup smoke requires actual Windows x64")
    if (runtime / "config").exists() or result.exists():
        raise ValueError("Use a NEW disposable runtime and result path; never overwrite private configuration")
    pwsh = shutil.which("pwsh")
    if not pwsh:
        raise RuntimeError("PowerShell 7.2+ is required")
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is required for private before/after isolation verification")
    external = Path(appdata) / "obs-studio"
    before = fingerprint(external)
    token = secrets.token_hex(16)
    environment = os.environ.copy()
    # The real launcher must remove these, including Qt's plugin override.
    for name in ("OBS_PLUGINS_PATH", "OBS_PLUGINS_DATA_PATH", "OBS_CONFIG_PATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        environment[name] = str(runtime / "deliberately-nonexistent-external-override")
    process = subprocess.run([pwsh, "-NoProfile", "-File", str(runtime / "launch-native.ps1"),
                              "-AllowPrototype", "-SmokeToken", token, "-TimeoutSeconds", "90"],
                             cwd=runtime.parent, env=environment, check=False)
    if fingerprint(external) != before:
        raise AssertionError("External OBS profile changed during native portable smoke; do not publish private files")
    if process.returncode:
        raise RuntimeError(f"Native startup/normal close failed with exit code {process.returncode}")
    profile = (runtime / "config/obs-studio").resolve()
    receipt = json.loads((profile / "native-smoke.json").read_text(encoding="utf-8"))
    if receipt.get("token") != token or receipt.get("obsVersion") != "32.1.2" or receipt.get("qtPlatform") != "windows":
        raise AssertionError("Native plugin identity/token mismatch")
    if Path(receipt["profile"]).resolve() != profile or Path(receipt["moduleConfig"]).resolve() != profile / "plugin_config/webobs-native-host":
        raise AssertionError("OBS reported a non-portable plugin configuration path")
    for flag in ("dockLoaded", "mediaSourceRegistered", "finishedLoading"):
        if receipt.get(flag) is not True:
            raise AssertionError(f"Native startup receipt missing {flag}")
    if receipt.get("mediaQualified") is not False:
        raise AssertionError("A startup smoke cannot qualify media")
    if not (profile / "global.ini").is_file() or not (profile / "user.ini").is_file():
        raise AssertionError("Portable OBS did not persist its own configuration")
    summary = {"schema": 1, "status": "passed", "obsVersion": "32.1.2", "qtVersion": receipt["qtVersion"],
               "dockLoaded": True, "mediaSourceRegistered": True, "normalExit": True,
               "portableProfile": True, "externalObsProfileUnchanged": True,
               "inheritedPluginOverridesCleared": True, "mediaQualified": False,
               "qualification": "Qt/plugin startup and one clean portable launch only; no camera/pixel/performance/auth/upgrade claim"}
    with result.open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2)
        output.write("\n")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    run(args.runtime.resolve(), args.result.resolve())
