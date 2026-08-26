#!/usr/bin/env python3
"""Verify redacted Windows and WSL2 gate receipts before an OCI release."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
from typing import NoReturn


CONTRACT = "webobs-local-gate-receipt-v1"
PLATFORMS = ("linux-wsl2-chromium", "windows")
MAX_AGE = timedelta(hours=48)
EXPECTED_CHECKS = {
    "linux-wsl2-chromium": {
        "whepDirect", "hlsDirect", "mjpegDirect", "gatewayFallback",
        "rtspNotTrueDirect", "zeroServerMediaIncrement", "revocationStopsPlayback",
    },
    "windows": {
        "chromeWhepDirect", "chromeHlsDirect", "chromeMjpegDirect",
        "chromeSixteenStreamsThirtyMinutes", "chromeDropRateBelowTwoPercent",
        "chromeMemoryStable", "chromeBackgroundReleased", "edgeInstall",
        "edgeOfflineRestore", "edgeUpdate", "edgeThreeProtocols",
        "edgeFourStreamsTenMinutes",
    },
}


def fail(message: str) -> NoReturn:
    raise SystemExit(f"local release gate rejected: {message}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, default=Path("build/private-gates"))
    args = parser.parse_args()

    repository = Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], check=True,
        capture_output=True, text=True,
    ).stdout.strip()).resolve()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    evidence_dir = (repository / args.evidence_dir).resolve() if not args.evidence_dir.is_absolute() else args.evidence_dir.resolve()
    now = datetime.now(timezone.utc)

    for platform in PLATFORMS:
        path = evidence_dir / f"{platform}.json"
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
            fail(f"missing or invalid {platform} receipt")
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            fail(f"{platform} receipt is not valid UTF-8 JSON")
        if set(receipt) != {"contract", "platform", "revision", "completedAt", "checks"}:
            fail(f"{platform} receipt contains unknown or missing fields")
        if receipt["contract"] != CONTRACT or receipt["platform"] != platform:
            fail(f"{platform} receipt contract does not match")
        if receipt["revision"] != revision:
            fail(f"{platform} receipt belongs to a different revision")
        if not isinstance(receipt["checks"], list) or set(receipt["checks"]) != EXPECTED_CHECKS[platform]:
            fail(f"{platform} receipt does not contain the exact required checks")
        if len(receipt["checks"]) != len(EXPECTED_CHECKS[platform]):
            fail(f"{platform} receipt contains duplicate checks")
        try:
            completed_at = datetime.fromisoformat(receipt["completedAt"].replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            fail(f"{platform} receipt has an invalid completion time")
        if completed_at.tzinfo is None or completed_at > now + timedelta(minutes=5):
            fail(f"{platform} receipt completion time is invalid")
        if now - completed_at > MAX_AGE:
            fail(f"{platform} receipt is older than 48 hours")

    print(f"Local release receipts passed for revision {revision[:12]}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
