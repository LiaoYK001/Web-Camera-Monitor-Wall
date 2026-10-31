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
from typing import Sequence


PRODUCT_URLS = tuple(f"rtsp://127.0.0.1:9/smoke-{index}" for index in range(1, 6))


def product_config_payload() -> dict:
    cameras = [{"id": f"cam-{index}", "name": f"Smoke Camera {index}", "url": PRODUCT_URLS[index - 1],
                "hardwareDecode": False} for index in range(1, 6)]
    return {"schema": 1, "cameras": cameras}


def write_product_config(path: Path) -> None:
    """Write the product camera config a real installation would ship privately."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(product_config_payload()), encoding="utf-8")


def check_product_receipt(receipt_path: Path, urls: Sequence[str] = PRODUCT_URLS) -> dict:
    """Validate the URL-free bootstrap receipt; never leak or print camera URLs."""
    text = receipt_path.read_text(encoding="utf-8")
    receipt = json.loads(text)
    if receipt.get("ok") is not True or receipt.get("created") != 5 or receipt.get("items") != 5:
        raise AssertionError("Product camera bootstrap did not create five sources")
    if receipt.get("reused") != 0 or receipt.get("canvasApplied") not in (True, False):
        raise AssertionError("Product camera bootstrap reuse/canvas flag mismatch")
    if "error" in receipt:
        raise AssertionError("Product camera bootstrap reported an error")
    for url in urls:
        if url in text:
            raise AssertionError("Product bootstrap receipt leaked a camera URL")
    return receipt


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
    profile = (runtime / "config/obs-studio").resolve()
    product_file = (result.parent / (result.stem + "-product.json")).resolve()
    write_product_config(product_file)
    try:
        process = subprocess.run([pwsh, "-NoProfile", "-File", str(runtime / "launch-native.ps1"),
                                  "-AllowPrototype", "-SmokeToken", token, "-TimeoutSeconds", "90",
                                  "-ProductConfig", str(product_file)],
                                 cwd=runtime.parent, env=environment, check=False)
    finally:
        product_file.unlink(missing_ok=True)
    if fingerprint(external) != before:
        raise AssertionError("External OBS profile changed during native portable smoke; do not publish private files")
    if process.returncode:
        raise RuntimeError(f"Native startup/normal close failed with exit code {process.returncode}")
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
    product = check_product_receipt(profile / "plugin_config/webobs-native-host/product-bootstrap.json")
    summary = {"schema": 1, "status": "passed", "obsVersion": "32.1.2", "qtVersion": receipt["qtVersion"],
               "dockLoaded": True, "mediaSourceRegistered": True, "normalExit": True,
               "portableProfile": True, "externalObsProfileUnchanged": True,
               "productCameraCreated": product["created"], "productCameraReused": product["reused"],
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
