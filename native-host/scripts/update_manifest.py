#!/usr/bin/env python3
"""Emit the native updater's latest.yml for one verified installer."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    if not re.fullmatch(r"5\.[01]\.0-rc\.[0-9]+", arguments.version):
        raise SystemExit("complete candidate version must be 5.0.0-rc.N or 5.1.0-rc.N")
    installer = arguments.installer.absolute()
    if installer.name != f"WebOBS-Wall-{arguments.version}-windows-x64-SETUP.exe":
        raise SystemExit("installer name does not match its update version")
    if installer.is_symlink() or not installer.is_file():
        raise SystemExit("installer is missing")
    digest = hashlib.sha512()
    size = 0
    with installer.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
    encoded = base64.b64encode(digest.digest()).decode("ascii")
    text = "\n".join([
        f"version: {arguments.version}",
        "files:",
        f"  - url: {installer.name}",
        f"    sha512: {encoded}",
        f"    size: {size}",
        f"path: {installer.name}",
        f"sha512: {encoded}",
        f"releaseDate: {datetime.now(timezone.utc).isoformat()}",
        "",
    ])
    arguments.output.write_text(text, encoding="utf-8")
    print(json.dumps({"version": arguments.version, "installer": installer.name,
                      "size": size, "sha512": encoded}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
