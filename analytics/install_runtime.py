#!/usr/bin/env python3
"""Install the optional first-party detector runtime from a hash-locked set."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import urllib.parse


MAX_WHEEL_BYTES = 250 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=pathlib.Path, required=True)
    parser.add_argument("--venv", type=pathlib.Path, required=True)
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    if lock.get("schemaVersion") != 1 or lock.get("python") != "3.12" or \
            lock.get("platform") != "manylinux_2_28_x86_64" or not isinstance(lock.get("artifacts"), list) or \
            len(lock["artifacts"]) != 2:
        raise SystemExit("detector dependency lock is invalid")
    args.venv.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "venv", str(args.venv)], check=True)
    wheels: list[str] = []
    with tempfile.TemporaryDirectory(prefix="webobs-detector-wheels-") as directory:
        root = pathlib.Path(directory)
        for artifact in lock["artifacts"]:
            if not isinstance(artifact, dict) or not all(isinstance(artifact.get(key), str)
                                                          for key in ("name", "version", "url", "sha256", "license")):
                raise SystemExit("detector dependency lock entry is invalid")
            parsed = urllib.parse.urlsplit(artifact["url"])
            if parsed.scheme != "https" or parsed.netloc != "files.pythonhosted.org" or \
                    not artifact["url"].endswith(".whl") or len(artifact["sha256"]) != 64 or \
                    any(character not in "0123456789abcdefABCDEF" for character in artifact["sha256"]):
                raise SystemExit("detector dependency URL or digest is invalid")
            destination = root / pathlib.Path(parsed.path).name
            subprocess.run(["curl", "--fail", "--location", "--retry", "5", "--retry-all-errors",
                            "--max-filesize", str(MAX_WHEEL_BYTES), "--output", str(destination), artifact["url"]],
                           check=True, timeout=300)
            digest = hashlib.sha256()
            total = 0
            with destination.open("rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    digest.update(chunk)
            if digest.hexdigest().lower() != artifact["sha256"].lower():
                raise SystemExit(f"detector dependency digest mismatch: {artifact['name']}")
            wheels.append(str(destination))
        pip = args.venv / "bin" / "pip"
        subprocess.run([str(pip), "install", "--no-index", "--no-deps", *wheels], check=True)
        subprocess.run([str(args.venv / "bin" / "python"), "-c",
                        "import numpy, onnxruntime; print(onnxruntime.__version__)"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
