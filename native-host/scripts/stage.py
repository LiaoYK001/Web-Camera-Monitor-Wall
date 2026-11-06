#!/usr/bin/env python3
"""Finalize a separate non-default portable prototype, never an installer."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from prepare import OBS_COMMIT, OBS_VERSION

REQUIRED = (
    "bin/64bit/obs64.exe",
    "bin/64bit/obs.dll",
    "bin/64bit/obs-frontend-api.dll",
    "bin/64bit/Qt6Core.dll",
    "bin/64bit/Qt6Widgets.dll",
    "bin/64bit/platforms/qwindows.dll",
    "obs-plugins/64bit/obs-ffmpeg.dll",
    "obs-plugins/64bit/webobs-native-host.dll",
    "data/obs-plugins/webobs-native-host/locale/en-US.ini",
)


def finalize(repo: Path, source: Path, runtime: Path, version: str) -> dict:
    if not version or "-dev." not in version:
        raise ValueError("Only an explicitly development-tagged prototype may be staged")
    if not runtime.is_dir() or runtime.is_symlink() or (runtime / "webobs-native-prototype.json").exists():
        raise ValueError("Staging requires a new, separate runtime directory")
    missing = [name for name in REQUIRED if not (runtime / name).is_file() or (runtime / name).is_symlink()]
    if missing:
        raise ValueError("Incomplete OBS native runtime: " + ", ".join(missing))
    if (runtime / "config").exists():
        raise ValueError("Do not stage over an existing user configuration")
    # Do not strip/rewrite DLLs after OBS's own runtime and Qt deployment.
    for sentinel in ("portable_mode.txt", "disable_updater.txt"):
        (runtime / sentinel).write_text("WebOBS independent development prototype\n", encoding="utf-8")
    shutil.copy2(repo / "native-host/scripts/launch-native.ps1", runtime / "launch-native.ps1")
    shutil.copy2(repo / "native-host/README.md", runtime / "NATIVE-PROTOTYPE-README.md")
    licenses = runtime / "licenses/webobs-native"
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "COPYING", licenses / "OBS-COPYING.txt")
    shutil.copy2(repo / "native-host/LICENSE", licenses / "PLUGIN-COPYING.txt")
    shutil.copy2(repo / "desktop/dependencies.lock.json", licenses / "desktop-dependencies.lock.json")
    # OBS's own runtime install retains its data/licenses and dependency licenses.
    # This development tree is NOT approved as a redistributable license bundle.
    files = [p for p in runtime.rglob("*") if p.is_file()]
    groups = {"qt": 0, "plugins": 0, "other": 0}
    for path in files:
        relative = path.relative_to(runtime).as_posix()
        group = "qt" if path.name.startswith("Qt6") or "/platforms/" in relative else "plugins" if relative.startswith(("obs-plugins/", "data/obs-plugins/")) else "other"
        groups[group] += path.stat().st_size
    manifest = {
        "schema": 1,
        "version": version,
        "obsVersion": OBS_VERSION,
        "obsCommit": OBS_COMMIT,
        "defaultProduct": False,
        "qualification": "development-only; auth, migration, lifecycle, installer and real camera gates remain open",
        "profile": "config/obs-studio (portable; no migration)",
        "media": "existing OBS ffmpeg_source objects and native preview/Program projectors",
        "optionalFeaturesDisabled": ["browser/CEF", "scripting", "websocket", "VLC", "VST", "AJA", "DeckLink"],
        "servicesStarted": [],
        "sizeBytesBeforeManifest": sum(groups.values()),
        "sizeGroups": groups,
    }
    (runtime / "webobs-native-prototype.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    manifest = finalize(args.repo.resolve(), args.source.resolve(), args.runtime.resolve(), args.version)
    print(json.dumps(manifest, indent=2))
