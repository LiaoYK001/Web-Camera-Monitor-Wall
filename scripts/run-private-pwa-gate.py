#!/usr/bin/env python3
"""Run a machine-local v2 PWA media gate without publishing private evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from typing import NoReturn


CONTRACT = "webobs-private-pwa-gate-v1"
MAX_LOG_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 90 * 60
REQUIRED_CHECKS = {
    "linux-wsl2-chromium": {
        "whepDirect",
        "hlsDirect",
        "mjpegDirect",
        "gatewayFallback",
        "rtspNotTrueDirect",
        "zeroServerMediaIncrement",
        "revocationStopsPlayback",
    },
    "windows": {
        "chromeWhepDirect",
        "chromeHlsDirect",
        "chromeMjpegDirect",
        "chromeSixteenStreamsThirtyMinutes",
        "chromeDropRateBelowTwoPercent",
        "chromeMemoryStable",
        "chromeBackgroundReleased",
        "edgeInstall",
        "edgeOfflineRestore",
        "edgeUpdate",
        "edgeThreeProtocols",
        "edgeFourStreamsTenMinutes",
    },
}


RECEIPT_CONTRACT = "webobs-local-gate-receipt-v1"


def fail(message: str) -> NoReturn:
    raise SystemExit(f"private PWA gate rejected: {message}")


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=sorted(REQUIRED_CHECKS), required=True)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="write a redacted, revision-bound gate receipt after all checks pass",
    )
    args = parser.parse_args()

    raw_command = os.environ.get("WEBOBS_PRIVATE_PWA_GATE_COMMAND", "").strip()
    if not raw_command:
        fail("WEBOBS_PRIVATE_PWA_GATE_COMMAND is not configured")
    command = Path(raw_command).expanduser().resolve()
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", Path.cwd())).resolve()
    if not command.is_absolute() or not command.is_file():
        fail("command must be an existing absolute file")
    if is_within(command, workspace):
        fail("command must be machine-local and outside GITHUB_WORKSPACE")
    if os.name != "nt" and not command.stat().st_mode & stat.S_IXUSR:
        fail("machine-local command is not executable")

    with tempfile.TemporaryDirectory(prefix="webobs-private-pwa-") as temp_dir:
        temp = Path(temp_dir)
        result_path = temp / "result.json"
        log_path = temp / "gate.log"
        child_env = {
            **os.environ,
            "WEBOBS_PRIVATE_GATE_PLATFORM": args.platform,
            "WEBOBS_PRIVATE_GATE_RESULT": str(result_path),
        }
        argv = [str(command)]
        if os.name == "nt" and command.suffix.casefold() == ".ps1":
            argv = ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(command)]
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                argv,
                cwd=command.parent,
                env=child_env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                shell=False,
            )
            deadline = time.monotonic() + TIMEOUT_SECONDS
            while process.poll() is None:
                time.sleep(1)
                if log_path.stat().st_size > MAX_LOG_BYTES:
                    process.kill()
                    process.wait()
                    fail("machine-local command exceeded the private log limit")
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait()
                    fail("machine-local command timed out")
            if process.returncode != 0:
                fail("machine-local command failed; rerun it locally to inspect private output")

        if not result_path.is_file() or result_path.stat().st_size > 64 * 1024:
            fail("bounded result JSON was not produced")
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            fail("result is not valid UTF-8 JSON")
        if set(result) != {"contract", "platform", "checks"}:
            fail("result contains unknown or missing top-level fields")
        if result["contract"] != CONTRACT or result["platform"] != args.platform:
            fail("result contract or platform does not match")
        checks = result["checks"]
        required = REQUIRED_CHECKS[args.platform]
        if not isinstance(checks, dict) or set(checks) != required:
            fail("result check set does not match the required release contract")
        if any(value is not True for value in checks.values()):
            fail("one or more required media checks failed")

    if args.evidence_dir is not None:
        evidence_dir = args.evidence_dir.expanduser().resolve()
        if is_within(evidence_dir, workspace / "gate"):
            fail("gate receipts must not be written into the private fixture directory")
        evidence_dir.mkdir(parents=True, exist_ok=True)
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
            fail("could not bind the gate receipt to a Git revision")
        receipt = {
            "contract": RECEIPT_CONTRACT,
            "platform": args.platform,
            "revision": revision,
            "completedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "checks": sorted(required),
        }
        receipt_path = evidence_dir / f"{args.platform}.json"
        temporary_path = evidence_dir / f".{args.platform}.json.tmp"
        temporary_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary_path, receipt_path)

    print(f"Private PWA acceptance passed for {args.platform}: {len(required)} checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
