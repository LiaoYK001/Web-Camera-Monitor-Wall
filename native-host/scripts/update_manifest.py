#!/usr/bin/env python3
"""Emit the native updater's latest.yml for one verified installer.

Candidate metadata stays pinned to its own ``-rc.N`` Tag and is never stable
feed metadata. A three-part release version is accepted only with the recorded
acceptance receipt location, so a stable ``latest.yml`` cannot be produced from
a version number alone.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

from release_policy import read_acceptance, tag_for_version


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--acceptance", type=Path,
                        help="recorded acceptance file required for a stable release version")
    parser.add_argument("--repository", help="release repository the acceptance receipt belongs to")
    parser.add_argument("--source-revision", help="reviewed 40-character revision the acceptance receipt belongs to")
    arguments = parser.parse_args(argv)
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-rc\.[0-9]+)?", arguments.version):
        raise SystemExit("version must be three-part, optionally with a -rc.N suffix")
    candidate = "-rc." in arguments.version
    if candidate and not re.fullmatch(r"5\.[01]\.0-rc\.[0-9]+", arguments.version):
        raise SystemExit("complete candidate version must be 5.0.0-rc.N or 5.1.0-rc.N")
    accepted = None
    if not candidate:
        if arguments.acceptance is None:
            raise SystemExit("stable update metadata requires --acceptance with recorded acceptance")
        if not re.fullmatch(r"[a-f0-9]{40}", (arguments.source_revision or "").lower() or ""):
            raise SystemExit("stable update metadata requires --source-revision of the reviewed commit")
        if not arguments.repository:
            raise SystemExit("stable update metadata requires --repository of the release repository")
        try:
            accepted = read_acceptance(arguments.acceptance, version=arguments.version,
                                       repository=arguments.repository,
                                       source_revision=(arguments.source_revision or "").lower())
        except ValueError as error:
            raise SystemExit(f"stable update metadata rejected: {error}") from error
    release_tag = tag_for_version(arguments.version)
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
    payload = {"version": arguments.version, "releaseTag": release_tag, "candidate": candidate,
               "installer": installer.name, "size": size, "sha512": encoded}
    if accepted:
        payload["qualificationReceipt"] = accepted["qualificationReceipt"]
        payload["sourceRevision"] = (arguments.source_revision or "").lower()
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
