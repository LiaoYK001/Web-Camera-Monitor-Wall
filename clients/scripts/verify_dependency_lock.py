#!/usr/bin/env python3
"""Validate the native-client dependency lock and optional downloaded artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit


EXPECTED = {
    "qt-source": ("6.11.2", "all"),
    "gstreamer-source": ("1.28.6", "all"),
    "gstreamer-plugins-base-source": ("1.28.6", "all"),
    "gstreamer-plugins-good-source": ("1.28.6", "all"),
    "gstreamer-plugins-bad-source": ("1.28.6", "all"),
    "gstreamer-plugins-ugly-source": ("1.28.6", "all"),
    "gstreamer-libav-source": ("1.28.6", "all"),
    "gstreamer-plugins-rs-source": ("0.15.3", "all"),
    "gstreamer-windows-x86_64": ("1.28.6", "windows-x86_64"),
    "gstreamer-android-universal": ("1.28.6", "android"),
    "libsodium-source": ("1.0.22", "all"),
}


def fail(message: str) -> None:
    raise SystemExit(f"dependency lock rejected: {message}")


def load_unique_json(path: Path) -> object:
    def unique(values):
        result = {}
        for key, value in values:
            if key in result:
                fail(f"duplicate JSON field {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda value: fail(f"non-finite number {value}"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(str(error))


def verify_lock(path: Path) -> dict[str, dict[str, str]]:
    document = load_unique_json(path)
    if not isinstance(document, dict) or set(document) != {"schemaVersion", "artifacts"} or \
            document["schemaVersion"] != 2 or not isinstance(document["artifacts"], list):
        fail("root must be the exact schemaVersion 2 document")
    artifacts: dict[str, dict[str, str]] = {}
    required = {"id", "name", "platform", "version", "url", "sha256"}
    for item in document["artifacts"]:
        if not isinstance(item, dict) or set(item) != required or \
                any(not isinstance(item[field], str) for field in required):
            fail("artifact fields are invalid")
        identifier = item["id"]
        if identifier in artifacts or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", identifier):
            fail(f"artifact id {identifier!r} is invalid or duplicated")
        if EXPECTED.get(identifier) != (item["version"], item["platform"]):
            fail(f"artifact {identifier!r} does not match the release baseline")
        parsed = urlsplit(item["url"])
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or \
                parsed.query or parsed.fragment:
            fail(f"artifact {identifier!r} URL is not a credential-free HTTPS origin")
        if not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            fail(f"artifact {identifier!r} SHA-256 is invalid")
        artifacts[identifier] = item
    if set(artifacts) != set(EXPECTED):
        fail("artifact set differs from the release baseline")
    return artifacts


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path,
                        default=Path(__file__).resolve().parents[1] / "dependencies.lock.json")
    parser.add_argument("--artifact", action="append", default=[], metavar="ID=PATH",
                        help="verify a downloaded artifact; may be repeated")
    parser.add_argument("--require-platform", choices=("windows-x86_64", "linux-x86_64", "android"),
                        help="require every common and platform artifact to be supplied exactly once")
    arguments = parser.parse_args()
    artifacts = verify_lock(arguments.lock)
    verified: set[str] = set()
    for specification in arguments.artifact:
        identifier, separator, raw_path = specification.partition("=")
        if not separator or identifier not in artifacts or not raw_path:
            fail("--artifact must use a locked ID=PATH")
        if identifier in verified:
            fail(f"artifact {identifier!r} was supplied more than once")
        artifact_path = Path(raw_path)
        if not artifact_path.is_file():
            fail(f"artifact file for {identifier!r} does not exist")
        actual = sha256_file(artifact_path)
        if actual != artifacts[identifier]["sha256"]:
            fail(f"artifact {identifier!r} SHA-256 mismatch")
        verified.add(identifier)
    if arguments.require_platform:
        required = {
            identifier for identifier, item in artifacts.items()
            if item["platform"] in {"all", arguments.require_platform}
        }
        if verified != required:
            missing = sorted(required - verified)
            extra = sorted(verified - required)
            fail(f"{arguments.require_platform} artifact set mismatch; missing={missing}, extra={extra}")
    print(f"dependency lock passed: {len(artifacts)} pinned artifacts, {len(verified)} files verified")


if __name__ == "__main__":
    main()
