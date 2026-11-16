#!/usr/bin/env python3
"""Native updater contracts: GitHub feed parsing, size/SHA-512 and no silent install."""
from __future__ import annotations

import base64
import hashlib
import http.server
import importlib.util
import json
from pathlib import Path
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]


def load():
    specification = importlib.util.spec_from_file_location(
        "native_updater", ROOT / "native-host/scripts/native_updater.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def serve(directory: Path):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def exercise():
    updater = load()
    assert updater.is_newer("5.0.0", "5.0.1")
    assert updater.is_newer("5.0.0-rc.1", "5.0.0")
    assert not updater.is_newer("5.0.1", "5.0.0")
    installer = b"MZ" + b"synthetic-installer" * 1000
    with tempfile.TemporaryDirectory(prefix="webobs-updater-") as temporary:
        base = Path(temporary)
        feed_dir = base / "feed"
        feed_dir.mkdir()
        (feed_dir / "WebOBS-Wall-5.0.1-windows-x64.exe").write_bytes(installer)
        digest = base64.b64encode(hashlib.sha512(installer).digest()).decode()
        (feed_dir / "latest.yml").write_text(
            "version: 5.0.1\nfiles:\n  - url: WebOBS-Wall-5.0.1-windows-x64.exe\n"
            f"    sha512: {digest}\n    size: {len(installer)}\npath: WebOBS-Wall-5.0.1-windows-x64.exe\n",
            encoding="utf-8")
        server, origin = serve(feed_dir)
        try:
            result = updater.check(origin + "/latest.yml", "5.0.0", allow_loopback=True)
            assert result["status"] == "available" and result["version"] == "5.0.1"
            assert result["size"] == len(installer)
            output = base / "updates"
            receipt = updater.download(result, output, allow_loopback=True)
            assert receipt["verified"] is True and (output / receipt["installer"]).read_bytes() == installer
            assert receipt["sha512"] == digest
            bad = dict(result, sha512="A" * 100)
            bad_output = base / "bad"
            try:
                updater.download(bad, bad_output, allow_loopback=True)
            except updater.UpdateError:
                pass
            else:
                raise AssertionError("updater accepted an installer with a wrong SHA-512")
            assert not (bad_output / "WebOBS-Wall-5.0.1-windows-x64.exe").exists()
            try:
                updater.install(result, output, None, base / "data", confirm=False, allow_loopback=True)
            except updater.UpdateError:
                pass
            else:
                raise AssertionError("updater installed without explicit confirmation")
            try:
                updater.check(origin + "/latest.yml", "5.0.1", allow_loopback=True)
            except updater.UpdateError:
                pass
            current = updater.check(origin + "/latest.yml", "5.0.2", allow_loopback=True)
            assert current["status"] == "current"
            try:
                updater.check("https://example.invalid/latest.yml", "5.0.0")
            except updater.UpdateError:
                pass
            else:
                raise AssertionError("updater accepted an unapproved update origin")
        finally:
            server.shutdown()
            server.server_close()
        print("PASS native updater feed, version, size/SHA-512, origin and explicit-confirmation contracts")


if __name__ == "__main__":
    exercise()
