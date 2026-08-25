#!/usr/bin/env python3
"""Bounded HLS fixture readiness probe without printing its private URL."""

import os
import time
import urllib.parse
import urllib.request


endpoint = os.environ.get("WEBOBS_FIXTURE_HLS", "")
parsed = urllib.parse.urlsplit(endpoint)
if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
    raise SystemExit("invalid HLS fixture endpoint")

deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(endpoint, timeout=5) as response:  # nosec B310 - bounded fixture URL
            body = response.read(256)
        if body.startswith(b"#EXTM3U"):
            print("HLS fixture ready")
            raise SystemExit(0)
    except Exception:  # readiness retries intentionally collapse transport details
        pass
    time.sleep(0.25)

raise SystemExit("HLS fixture did not become ready within 30 seconds")
