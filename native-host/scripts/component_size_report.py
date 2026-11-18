#!/usr/bin/env python3
"""Split one complete Windows candidate into per-component byte groups.

Offline receipt analysis: it reads the sanitized receipts a Windows run uploads
(``runtime/product-components.json`` plus the NSIS footprint receipt) and never
touches a device, a user profile or a private path. The point is to answer
"which component costs what" for download size and installed footprint, and to
compare the installed tree with the same-OS stock OBS reference recorded by the
opt-in baseline step. It measures bytes only: it never claims that a component
is required, qualified or media-correct.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA = 1
LIMIT = 4 * 1024 * 1024

# First matching rule wins, so order is meaningful. Names are stable because the
# release notes and the parity document quote them.
RULES: tuple[tuple[str, str], ...] = (
    ("OBS frontend and product plugin", r"^bin/64bit/obs64\.exe$"),
    ("OBS plugins shipped by the build", r"^bin/64bit/plugins/"),
    ("OBS plugin binaries", r"^obs-plugins/"),
    ("OBS data and assets", r"^data/"),
    ("Qt 6 runtime", r"^bin/64bit/(Qt|qt)[^/]*\.dll$"),
    ("Qt plugins", r"^bin/64bit/(imageformats|platforms|styles|iconengines)/"),
    ("FFmpeg (libav* / sw*)", r"^(bin/(64bit/)?)(av(codec|device|filter|format|util)|sw(scale|resample))[^/]*\.dll$"),
    ("go2rtc (binary + bundled UI)", r"^(bin/go2rtc[^/]*|go2rtc-www/)",),
    ("MediaMTX gateway", r"^bin/mediamtx[^/]*$"),
    ("Caddy LAN HTTPS proxy", r"^bin/caddy[^/]*$"),
    ("Node runtime for services", r"^bin/node[^/]*$"),
    ("Embedded Python runtime", r"^python/"),
    ("Product control server and online source", r"^bin/(webobsd|webobs-online-source)[^/]*$"),
    ("Python product services", r"^services/"),
    ("Web UI bundle (PWA)", r"^web/"),
    ("Support DLLs (OpenSSL, curl, sqlite, VC++)",
     r"^bin/(libcrypto|libssl|libcurl|libsodium|sqlite3|msvcp|vcruntime|concrt|ucrt)[^/]*\.dll$"),
    ("Licenses and notices", r"^licenses/"),
)
COMPILED = [(name, re.compile(pattern)) for name, pattern in RULES]


def component_for(path: str) -> str:
    for name, pattern in COMPILED:
        if pattern.match(path):
            return name
    return "Other staged files"


def read_receipt(path: Path) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > LIMIT:
        raise ValueError(f"missing or oversized receipt: {path.name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"receipt is not a JSON object: {path.name}")
    return payload


def components(files) -> list[dict]:
    grouped: dict[str, dict] = {}
    for entry in files:
        path, size = entry.get("path"), entry.get("bytes")
        if not isinstance(path, str) or not isinstance(size, int) or size < 0:
            raise ValueError("component receipt needs bounded path/bytes entries")
        group = grouped.setdefault(component_for(path), {"name": component_for(path), "files": 0, "bytes": 0})
        group["files"] += 1
        group["bytes"] += size
    total = sum(group["bytes"] for group in grouped.values())
    ordered = sorted(grouped.values(), key=lambda group: -group["bytes"])
    for group in ordered:
        group["sharePercent"] = round(group["bytes"] * 100 / total, 2) if total else 0.0
    return ordered


def report(components_receipt: Path, nsis_receipt: Path | None,
           obs_reference: Path | None = None) -> dict:
    staged = read_receipt(components_receipt)
    if not isinstance(staged.get("files"), list) or not staged["files"]:
        raise ValueError("component receipt has no files")
    groups = components(staged["files"])
    value = {
        "schema": SCHEMA,
        "kind": "windows-complete-candidate-size-split",
        "version": staged.get("version"),
        "sourceRevision": staged.get("sourceRevision"),
        "releaseProfile": staged.get("releaseProfile"),
        "candidate": staged.get("candidate"),
        "completeStaging": staged.get("completeStaging"),
        "stagedBytes": sum(group["bytes"] for group in groups),
        "stagedFiles": sum(group["files"] for group in groups),
        "components": groups,
    }
    if nsis_receipt is not None:
        nsis = read_receipt(nsis_receipt)
        footprint = nsis.get("footprint")
        if not isinstance(footprint, dict):
            raise ValueError("NSIS receipt has no installed footprint")
        value["installer"] = {"bytes": nsis.get("setupBytes"), "sha256": nsis.get("setupSha256"),
                              "version": nsis.get("version"), "sourceRevision": nsis.get("sourceRevision")}
        value["installedTree"] = {"logicalBytes": footprint.get("logicalBytes"),
                                  "allocationBytes": footprint.get("mainStreamAllocationBytes"),
                                  "fileCount": footprint.get("fileCount"),
                                  "directoryCount": footprint.get("directoryCountIncludingRoot"),
                                  "allocationUnitBytes": footprint.get("allocationUnitBytes"),
                                  "measurementPhase": "installed, before first product start"}
    if obs_reference is not None:
        reference = read_receipt(obs_reference)
        value["stockObsReference"] = {key: reference.get(key) for key in
            ("installerBytes", "logicalBytes", "allocationBytes", "fileCount", "obsVersion")}
        if isinstance(value.get("installedTree"), dict) and reference.get("logicalBytes"):
            value["installedTree"]["versusStockObsPercent"] = round(
                value["installedTree"]["logicalBytes"] * 100 / reference["logicalBytes"], 1)
    return value


def markdown(value: dict) -> str:
    lines = ["| 组件 / component | 文件 / files | 字节 / bytes | 占比 / share |",
             "| --- | ---: | ---: | ---: |"]
    for group in value["components"]:
        lines.append(f"| {group['name']} | {group['files']} | {group['bytes']:,} | "
                     f"{group['sharePercent']}% |")
    lines.append(f"| **合计 / total staged** | **{value['stagedFiles']:,}** | "
                 f"**{value['stagedBytes']:,}** | 100% |")
    installer = value.get("installer") or {}
    installed = value.get("installedTree") or {}
    if installer.get("bytes"):
        lines.append("")
        lines.append(f"- 安装包 / setup: {installer['bytes']:,} B · SHA-256 `{installer['sha256']}`")
    if installed.get("logicalBytes"):
        lines.append(f"- 安装树（首启前）/ installed tree before first start: "
                     f"{installed['logicalBytes']:,} logical / {installed['allocationBytes']:,} allocation B · "
                     f"{installed['fileCount']:,} files / {installed['directoryCount']:,} directories")
        if installed.get("versusStockObsPercent"):
            lines.append(f"- 相对同机原版 OBS 32.1.2 安装树 / versus stock OBS on the same machine: "
                         f"{installed['versusStockObsPercent']}% of its logical bytes")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--components", type=Path, required=True,
                        help="runtime/product-components.json from a Windows run")
    parser.add_argument("--nsis", type=Path, help="native-product-nsis.json footprint receipt")
    parser.add_argument("--obs-reference", type=Path,
                        help="recorded stock OBS 32.1.2 same-OS reference JSON")
    parser.add_argument("--markdown", action="store_true", help="print the table instead of JSON")
    parser.add_argument("--output", type=Path,
                        help="write the JSON report to this path (used by the Windows run)")
    arguments = parser.parse_args(argv)
    try:
        value = report(arguments.components, arguments.nsis, arguments.obs_reference)
    except (OSError, ValueError) as error:
        print(f"size split failed: {error}", file=sys.stderr)
        return 1
    payload = json.dumps(value, indent=2, sort_keys=True)
    if arguments.output is not None:
        if arguments.output.is_symlink():
            print("size split output must not be a symbolic link", file=sys.stderr)
            return 1
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(payload + "\n", encoding="utf-8")
        print(f"size split recorded: {value['stagedBytes']:,} staged bytes over "
              f"{len(value['components'])} components")
        return 0
    print(markdown(value) if arguments.markdown else payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
