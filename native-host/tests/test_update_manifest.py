#!/usr/bin/env python3
"""latest.yml generation is bound to the candidate installer bytes."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[2]


def load():
    specification = importlib.util.spec_from_file_location(
        "update_manifest", ROOT / "native-host/scripts/update_manifest.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def exercise():
    module = load()
    payload = b"MZ" + b"candidate" * 500
    with tempfile.TemporaryDirectory(prefix="webobs-manifest-") as temporary:
        base = Path(temporary)
        installer = base / "WebOBS-Wall-5.0.0-rc.1-windows-x64-SETUP.exe"
        installer.write_bytes(payload)
        output = base / "latest.yml"
        assert module.main(["--installer", str(installer), "--version", "5.0.0-rc.1",
                            "--output", str(output)]) == 0
        text = output.read_text(encoding="utf-8")
        digest = base64.b64encode(hashlib.sha512(payload).digest()).decode()
        assert "version: 5.0.0-rc.1" in text
        assert f"size: {len(payload)}" in text
        assert digest in text
        assert installer.name in text
        try:
            module.main(["--installer", str(installer), "--version", "5.0.0",
                         "--output", str(output)])
        except SystemExit:
            pass
        else:
            raise AssertionError("metadata accepted a non-candidate version")
        print("PASS update manifest binds candidate version, size, SHA-512 and installer name")


if __name__ == "__main__":
    exercise()
