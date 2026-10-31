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


def check_product_receipt(receipt_path: Path, urls: Sequence[str] = PRODUCT_URLS, *, expect_created: int = 5,
                          expect_reused: int = 0, expect_scene_reused: bool | None = None) -> dict:
    """Validate the URL-free bootstrap receipt; never leak or print camera URLs."""
    text = receipt_path.read_text(encoding="utf-8")
    receipt = json.loads(text)
    if receipt.get("ok") is not True or receipt.get("created") != expect_created or receipt.get("items") != 5:
        raise AssertionError("Product camera bootstrap created/reused an unexpected number of sources")
    if receipt.get("reused") != expect_reused or receipt.get("canvasApplied") not in (True, False):
        raise AssertionError("Product camera bootstrap reuse/canvas flag mismatch")
    if expect_scene_reused is not None and receipt.get("sceneReused") is not expect_scene_reused:
        raise AssertionError("Product camera bootstrap wall reuse mismatch")
    if "error" in receipt:
        raise AssertionError("Product camera bootstrap reported an error")
    for url in urls:
        if url in text:
            raise AssertionError("Product bootstrap receipt leaked a camera URL")
    return receipt


def launch_once(runtime: Path, pwsh: str, environment: dict, token: str, product_file: Path,
                receipt: str, reuse: bool = False) -> None:
    args = [pwsh, "-NoProfile", "-File", str(runtime / "launch-native.ps1"), "-AllowPrototype",
            "-SmokeToken", token, "-TimeoutSeconds", "90", "-ProductConfig", str(product_file)]
    if reuse:
        args.append("-ReuseProfile")
    environment = dict(environment)
    environment["WEBOBS_NATIVE_SMOKE_RECEIPT"] = receipt
    process = subprocess.run(args, cwd=runtime.parent, env=environment, check=False)
    if process.returncode:
        raise RuntimeError(f"Native startup/normal close failed with exit code {process.returncode}")


def verify_smoke(receipt_path: Path, token: str, profile: Path) -> dict:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
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


def run(runtime: Path, result: Path, *, existing_wall: bool = False) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("The Qt startup smoke requires actual Windows x64")
    profile = (runtime / "config/obs-studio").resolve()
    if existing_wall:
        if not profile.is_dir() or not (profile / "global.ini").is_file() or not (profile / "user.ini").is_file():
            raise ValueError("Existing-wall smoke requires an installed private portable profile")
    elif (runtime / "config").exists():
        raise ValueError("Use a NEW disposable runtime; never overwrite private configuration")
    if result.exists():
        raise ValueError("Use a NEW result path")
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
    product_file = (result.parent / (result.stem + "-product.json")).resolve()
    write_product_config(product_file)
    first_name = f"native-smoke-{token[:12]}-first.json"
    second_name = f"native-smoke-{token[:12]}-second.json"
    try:
        launch_once(runtime, pwsh, environment, token, product_file, first_name, reuse=existing_wall)
        first_receipt = verify_smoke(profile / first_name, token, profile)
        product = check_product_receipt(
            profile / "plugin_config/webobs-native-host/product-bootstrap.json",
            expect_created=0 if existing_wall else 5,
            expect_reused=5 if existing_wall else 0,
            expect_scene_reused=True if existing_wall else None)
        if existing_wall:
            second = product
        else:
            launch_once(runtime, pwsh, environment, token, product_file, second_name, reuse=True)
            verify_smoke(profile / second_name, token, profile)
            second = check_product_receipt(profile / "plugin_config/webobs-native-host/product-bootstrap.json",
                                           expect_created=0, expect_reused=5, expect_scene_reused=True)
    finally:
        product_file.unlink(missing_ok=True)
    if fingerprint(external) != before:
        raise AssertionError("External OBS profile changed during native portable smoke; do not publish private files")
    qualification = ("Single launch over an installed private profile: reuse only; "
                     "no camera/pixel/performance/auth/upgrade claim") if existing_wall else (
        "Two launches in one disposable profile: fresh product creation then reuse; "
        "no camera/pixel/performance/auth/upgrade claim")
    summary = {"schema": 1, "status": "passed", "existingWallMode": existing_wall,
               "obsVersion": "32.1.2", "qtVersion": first_receipt["qtVersion"],
               "dockLoaded": True, "mediaSourceRegistered": True, "normalExit": True,
               "portableProfile": True, "externalObsProfileUnchanged": True,
               "productCameraCreated": product["created"], "productCameraReused": product["reused"],
               "productCameraCreatedSecond": second["created"], "productCameraReusedSecond": second["reused"],
               "productSceneReusedSecond": second["sceneReused"],
               "inheritedPluginOverridesCleared": True, "mediaQualified": False,
               "qualification": qualification}
    with result.open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2)
        output.write("\n")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--existing-wall", action="store_true",
                        help="existing installed profile already owns the five-camera wall")
    args = parser.parse_args()
    run(args.runtime.resolve(), args.result.resolve(), existing_wall=args.existing_wall)
