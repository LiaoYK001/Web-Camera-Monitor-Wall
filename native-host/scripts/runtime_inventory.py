"""Inventory the staged native runtime and enforce the P4 accounting gate.

P4 requires an explicit default scope, reviewable size groups and licence
material instead of a single "it is smaller" claim. This script walks the
staged runtime after `prune_runtime.py` and `stage.py`, refuses leftover build
products, reports every size group plus the bundle/plug-in locales, and hashes
the shipped binaries into a small inventory that can feed an SBOM.

The vendor/licence hints are inventory pointers for review, not a legal
conclusion; the runtime's `licenses/` tree stays authoritative.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA = 1
RECEIPT_KIND = "native-runtime-inventory"
DEFAULT_MAX_RUNTIME_BYTES = 104_857_600  # 100 MiB for the development scope.
FORBIDDEN_NAMES = {"cmakecache.txt"}
FORBIDDEN_SUFFIXES = {
    ".pdb",
    ".lib",
    ".exp",
    ".ilk",
    ".obj",
    ".vcxproj",
    ".props",
    ".targets",
    ".cmake",
}

# (path regex, vendor, licence hint). First match wins; unmatched binaries stay "unclassified".
VENDORS = (
    (re.compile(r"^bin/64bit/Qt6.*\.dll$|^bin/64bit/(platforms|imageformats|styles|iconengines)/"), "Qt", "LGPL-3.0-only"),
    (re.compile(r"^bin/64bit/(avcodec|avformat|avfilter|avutil|swscale|swresample)-.*\.dll$"), "FFmpeg", "LGPL-2.1-or-later (build may carry GPL parts)"),
    (re.compile(r"^bin/64bit/libx264.*\.dll$"), "x264", "GPL-2.0-or-later"),
    (re.compile(r"^bin/64bit/(libcurl|srt|librist|zlib|w32-pthreads)\.dll$"), "third-party", "see licenses/"),
    (re.compile(r"^bin/64bit/(obs64\.exe|obs\.dll|obs-frontend-api\.dll|libobs.*\.dll)$"), "OBS Studio", "GPL-2.0-or-later"),
    (re.compile(r"^(obs-plugins/64bit|data/obs-plugins)/"), "OBS Studio", "GPL-2.0-or-later (plug-in-specific terms apply)"),
    (re.compile(r"^bin/64bit/obs-.*-test\.exe$"), "OBS Studio", "GPL-2.0-or-later"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def classify(relative: str) -> str:
    name = relative.rsplit("/", 1)[-1]
    if relative.startswith("licenses/"):
        return "licenses"
    if relative.startswith(("obs-plugins/", "data/obs-plugins/")):
        return "plugins"
    if relative.startswith("data/"):
        return "data"
    if re.match(r"^bin/64bit/(Qt6|platforms/|imageformats/|styles/|iconengines/)", relative):
        return "qt"
    if relative.startswith("bin/"):
        return "bin"
    return "other"


def vendor_for(relative: str) -> tuple[str, str] | None:
    for pattern, vendor, licence in VENDORS:
        if pattern.search(relative):
            return vendor, licence
    return None


def inventory(runtime: Path, max_runtime_bytes: int = DEFAULT_MAX_RUNTIME_BYTES) -> dict:
    runtime = runtime.resolve()
    if not runtime.is_dir():
        raise SystemExit(f"runtime is not a directory: {runtime}")
    forbidden: list[str] = []
    groups = {"bin": 0, "qt": 0, "plugins": 0, "data": 0, "licenses": 0, "other": 0}
    locales = {"files": 0, "bytes": 0}
    languages: set[str] = set()
    components: list[dict] = []
    files = 0
    total = 0
    for path in sorted(runtime.rglob("*")):
        if not path.is_file():
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(runtime)
        except ValueError:
            raise SystemExit(f"refusing to inventory outside the runtime: {resolved}")
        relative = resolved.relative_to(runtime).as_posix()
        suffix = resolved.suffix.lower()
        if suffix in FORBIDDEN_SUFFIXES or resolved.name.lower() in FORBIDDEN_NAMES:
            forbidden.append(relative)
        size = resolved.stat().st_size
        files += 1
        total += size
        if "/locale/" in "/" + relative and suffix == ".ini":
            locales["files"] += 1
            locales["bytes"] += size
            languages.add(resolved.name)
        else:
            groups[classify(relative)] += size
        if suffix in {".dll", ".exe"}:
            match = vendor_for(relative)
            component = {
                "path": relative,
                "bytes": size,
                "sha256": sha256(resolved),
                "vendor": match[0] if match else "unclassified",
            }
            if match:
                component["licenseHint"] = match[1]
            components.append(component)
    if forbidden:
        raise SystemExit(
            "build products leaked into the runtime: " + ", ".join(sorted(forbidden)[:8])
        )
    if total > max_runtime_bytes:
        raise SystemExit(
            f"runtime {total} bytes exceeds the P4 budget {max_runtime_bytes} bytes"
        )
    version = None
    manifest = runtime / "webobs-native-prototype.json"
    if manifest.is_file():
        try:
            version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError):
            version = None
    vendors: dict[str, int] = {}
    for component in components:
        vendors[component["vendor"]] = vendors.get(component["vendor"], 0) + 1
    return {
        "schema": SCHEMA,
        "kind": RECEIPT_KIND,
        "version": version,
        "scope": "default portable prototype runtime (development-only)",
        "files": files,
        "totalBytes": total,
        "maxRuntimeBytes": max_runtime_bytes,
        "withinBudget": True,
        "groups": groups,
        "locales": {"files": locales["files"], "bytes": locales["bytes"], "languages": sorted(languages)},
        "binaries": len(components),
        "vendors": vendors,
        "components": components,
        "forbiddenArtifacts": [],
        "note": "vendor/licence hints are for review only; licenses/ is authoritative",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--max-runtime-bytes", type=int, default=DEFAULT_MAX_RUNTIME_BYTES)
    args = parser.parse_args(argv)
    receipt = inventory(args.runtime, args.max_runtime_bytes)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "runtime inventory: {} files, {} bytes (budget {}), {} binaries".format(
            receipt["files"], receipt["totalBytes"], receipt["maxRuntimeBytes"], receipt["binaries"]
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
