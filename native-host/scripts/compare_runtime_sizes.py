"""Explain the installed-size gap between the prototype and stock OBS.

P4 requires the same-scope OBS gap to be explained rather than replaced by a
download-size comparison. This script walks the staged native runtime and an
installed stock OBS tree, classifies files as shared / prototype-only /
OBS-only, and groups the OBS-only bytes so review can see what the prototype
intentionally does not ship (CEF, scripting, extra plug-ins, locales, ...).

It makes no qualification claim: both trees are Windows installs, but the
prototype is a development-scope subset, not an equal-feature build.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCHEMA = 1
RECEIPT_KIND = "native-size-compare"


def walk(root: Path) -> dict[str, int]:
    root = root.resolve()
    if not root.is_dir():
        raise SystemExit(f"tree is not a directory: {root}")
    files: dict[str, int] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError:
            raise SystemExit(f"refusing to walk outside the tree: {resolved}")
        files[relative] = resolved.stat().st_size
    return files


def group_key(relative: str) -> str:
    parts = relative.split("/")
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


def summarize(paths: dict[str, int]) -> dict:
    return {"files": len(paths), "bytes": sum(paths.values())}


def group_totals(paths: dict[str, int]) -> list[dict]:
    groups: dict[str, list[int]] = {}
    for relative, size in paths.items():
        entry = groups.setdefault(group_key(relative), [0, 0])
        entry[0] += 1
        entry[1] += size
    return [
        {"group": key, "files": files, "bytes": size}
        for key, (files, size) in sorted(groups.items(), key=lambda item: -item[1][1])
    ]


CEF_NAMES = {
    "libcef.dll",
    "icudtl.dat",
    "resources.pak",
    "libglesv2.dll",
    "libegl.dll",
    "chrome_elf.dll",
    "snapshot_blob.bin",
    "v8_context_snapshot.bin",
}


def category(relative: str) -> str:
    name = relative.rsplit("/", 1)[-1].lower()
    if name.endswith(".pdb"):
        return "debug-symbols"
    if name in CEF_NAMES or "/cef/" in relative.lower() or name.endswith(".pak"):
        return "cef-browser"
    if relative.startswith("data/obs-scripting/") or "obs-scripting" in name or "python" in relative.lower():
        return "scripting"
    if "obs-websocket" in name:
        return "websocket"
    if relative.startswith("data/obs-plugins/"):
        return "plugin-data-locales"
    if relative.startswith("obs-plugins/"):
        return "extra-plugins"
    if name == "uninstall.exe":
        return "uninstaller"
    return "other"


def category_totals(paths: dict[str, int]) -> list[dict]:
    totals: dict[str, list[int]] = {}
    for relative, size in paths.items():
        entry = totals.setdefault(category(relative), [0, 0])
        entry[0] += 1
        entry[1] += size
    return [
        {"category": key, "files": files, "bytes": size}
        for key, (files, size) in sorted(totals.items(), key=lambda item: -item[1][1])
    ]


def compare(prototype: Path, obs: Path, largest: int = 15) -> dict:
    prototype_files = walk(prototype)
    obs_files = walk(obs)
    shared = {
        path: size for path, size in prototype_files.items() if path in obs_files
    }
    prototype_only = {
        path: size for path, size in prototype_files.items() if path not in obs_files
    }
    obs_only = {
        path: size for path, size in obs_files.items() if path not in prototype_files
    }
    obs_without_symbols = {
        path: size for path, size in obs_files.items() if not path.lower().endswith(".pdb")
    }
    largest_obs_only = sorted(obs_only.items(), key=lambda item: -item[1])[:largest]
    prototype_total = sum(prototype_files.values())
    obs_total = sum(obs_files.values())
    overlap = (100.0 * sum(shared.values()) / obs_total) if obs_total else 0.0
    return {
        "schema": SCHEMA,
        "kind": RECEIPT_KIND,
        "scope": {
            "prototype": "staged portable prototype runtime (development scope)",
            "obs": "installed stock OBS 32.1.2 (full feature scope)",
        },
        "prototype": summarize(prototype_files),
        "obs": summarize(obs_files),
        "shared": summarize(shared),
        "prototypeOnly": summarize(prototype_only),
        "obsOnly": summarize(obs_only),
        "sharedPercentOfObsBytes": round(overlap, 2),
        "obsOnlyGroups": group_totals(obs_only),
        "obsOnlyCategories": category_totals(obs_only),
        "obsWithoutBuildSymbols": summarize(obs_without_symbols),
        "prototypePercentOfObsWithoutSymbols": round(
            100.0 * prototype_total / sum(obs_without_symbols.values()), 2
        )
        if obs_without_symbols
        else 0.0,
        "prototypeOnlyGroups": group_totals(prototype_only)[:largest],
        "largestObsOnly": [
            {"path": path, "bytes": size} for path, size in largest_obs_only
        ],
        "note": (
            "Byte attribution for review only; the trees differ in feature scope. "
            "This does not make the prototype equal-feature or a P4 completion claim."
        ),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prototype", required=True, type=Path)
    parser.add_argument("--obs", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--largest", type=int, default=15)
    args = parser.parse_args(argv)
    receipt = compare(args.prototype, args.obs, args.largest)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "size compare: prototype {} B / obs {} B / obs-only {} B / shared {} B".format(
            receipt["prototype"]["bytes"],
            receipt["obs"]["bytes"],
            receipt["obsOnly"]["bytes"],
            receipt["shared"]["bytes"],
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
