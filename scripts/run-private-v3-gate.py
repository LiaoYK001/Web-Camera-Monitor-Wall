#!/usr/bin/env python3
"""Run a machine-local v3 analytics gate and write only a redacted receipt.

The actual browser/media fixture is intentionally kept outside the public
checkout.  It must write a bounded JSON result to ``WEBOBS_PRIVATE_GATE_RESULT``
and exit successfully.  This adapter validates the result, binds the receipt
to the current Git revision, and never copies private fixture output into the
repository or a CI artifact.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
from typing import NoReturn


CONTRACTS = {
    "v3-M1": "webobs-v3-m1-gate-v1",
    "v3-M2": "webobs-v3-m2-gate-v1",
}
RECEIPT_CONTRACTS = {
    "v3-M1": "webobs-v3-m1-gate-receipt-v1",
    "v3-M2": "webobs-v3-m2-gate-receipt-v1",
}
CHECKS = {
    ("v3-M1", "windows"): {"windowsMotionScene"},
    ("v3-M1", "linux"): {"linuxDirectZeroMedia", "onvifBrowserFallback", "sixteenStreamScheduler"},
    ("v3-M1", "regression"): {"pwaOfflineUpgrade", "registryEventsNvr", "publicAuditRedaction"},
    ("v3-M2", "windows"): {"chromeWebGpuPerson", "edgeOfflinePerson"},
    ("v3-M2", "linux"): {"wasmPerson", "workerCpuPerson", "detectorResourceRelease", "directZeroMedia"},
    ("v3-M2", "model"): {"modelLicense", "modelSha256", "personOnlyPostprocess", "fixturePrecisionRecall"},
    ("v3-M2", "regression"): {"v1ToV3Regression", "m7FaultAndScheduling", "publicAuditRedaction"},
}
MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_RESULT_BYTES = 64 * 1024
TIMEOUT_SECONDS = 90 * 60


def fail(message: str) -> NoReturn:
    raise SystemExit(f"private v3 gate rejected: {message}")


def inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def command_argv(command: Path) -> list[str]:
    suffix = command.suffix.casefold()
    if suffix == ".py":
        return [os.environ.get("PYTHON", "python"), str(command)]
    if os.name != "nt" or suffix not in {".ps1", ".cmd", ".bat"}:
        return [str(command)]
    if suffix == ".ps1":
        # PowerShell 7 is preferred, but Windows Docker Desktop hosts commonly
        # only have the inbox Windows PowerShell executable.
        if subprocess.run(["where", "pwsh"], capture_output=True).returncode == 0:
            return ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(command)]
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(command)]
    return ["cmd.exe", "/d", "/s", "/c", str(command)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--milestone", choices=sorted(CONTRACTS), required=True)
    parser.add_argument("--platform", choices=sorted({platform for _, platform in CHECKS}), required=True)
    parser.add_argument("--command", type=Path, default=None,
                        help="absolute machine-local fixture command; defaults to WEBOBS_PRIVATE_V3_GATE_COMMAND")
    parser.add_argument("--evidence-dir", type=Path, default=Path("build/private-gates"))
    args = parser.parse_args()
    expected = CHECKS.get((args.milestone, args.platform))
    if expected is None:
        fail(f"{args.milestone} does not define a {args.platform} gate")

    workspace = Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], check=True,
        capture_output=True, text=True,
    ).stdout.strip()).resolve()
    command_value = args.command or Path(os.environ.get("WEBOBS_PRIVATE_V3_GATE_COMMAND", "")).expanduser()
    command = command_value.resolve()
    if not command.is_absolute() or not command.is_file():
        fail("command must be an existing absolute file")
    if inside(command, workspace):
        fail("command must be machine-local and outside the checkout")
    if os.name != "nt" and command.suffix.casefold() != ".py" and not command.stat().st_mode & stat.S_IXUSR:
        fail("machine-local command is not executable")

    with tempfile.TemporaryDirectory(prefix="webobs-private-v3-") as directory:
        root = Path(directory)
        result_path = root / "result.json"
        log_path = root / "gate.log"
        child_env = {
            **os.environ,
            "WEBOBS_PRIVATE_V3_GATE_MILESTONE": args.milestone,
            "WEBOBS_PRIVATE_V3_GATE_PLATFORM": args.platform,
            "WEBOBS_PRIVATE_GATE_RESULT": str(result_path),
        }
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                command_argv(command), cwd=command.parent, env=child_env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
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
            fail("machine-local command failed; inspect its private output locally")
        if not result_path.is_file() or result_path.stat().st_size > MAX_RESULT_BYTES:
            fail("bounded result JSON was not produced")
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            fail("result is not valid UTF-8 JSON")
        if set(result) != {"contract", "milestone", "platform", "checks"}:
            fail("result contains unknown or missing fields")
        if result["contract"] != CONTRACTS[args.milestone] or \
                result["milestone"] != args.milestone or result["platform"] != args.platform:
            fail("result contract, milestone or platform does not match")
        checks = result["checks"]
        if not isinstance(checks, dict) or set(checks) != expected or any(value is not True for value in checks.values()):
            fail("result check set does not match or a required check failed")

    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=workspace, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        fail("could not bind the gate receipt to a Git revision")
    evidence_dir = args.evidence_dir.expanduser().resolve()
    if inside(evidence_dir, workspace / "gate"):
        fail("receipts must not be written into the private fixture directory")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    # Keep the verifier's stable names (v3-m1-windows, v3-m2-model, ...).
    name = f"{args.milestone.lower()}-{args.platform}"
    receipt = {
        "contract": RECEIPT_CONTRACTS[args.milestone],
        "name": name,
        "revision": revision,
        "completedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "checks": sorted(expected),
    }
    temporary = evidence_dir / f".{name}.json.tmp"
    destination = evidence_dir / f"{name}.json"
    temporary.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    print(f"Private v3 acceptance passed for {name}: {len(expected)} checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
