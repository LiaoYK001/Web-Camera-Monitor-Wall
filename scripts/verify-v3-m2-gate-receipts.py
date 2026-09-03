#!/usr/bin/env python3
"""Fail closed unless revision-bound v3-M2 model/worker gates are present."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONTRACT = "webobs-v3-m2-gate-receipt-v1"
SPECS = {
    "v3-m2-windows": {"chromeWebGpuPerson", "edgeOfflinePerson"},
    "v3-m2-linux": {"wasmPerson", "workerCpuPerson", "detectorResourceRelease", "directZeroMedia"},
    "v3-m2-model": {"modelLicense", "modelSha256", "personOnlyPostprocess", "fixturePrecisionRecall"},
    "v3-m2-regression": {"v1ToV3Regression", "m7FaultAndScheduling", "publicAuditRedaction"},
}


def fail(message: str) -> None:
    raise SystemExit(f"v3-M2 release gate rejected: {message}")


def main() -> int:
    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True).stdout.strip()).resolve()
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    now = datetime.now(timezone.utc)
    for name, expected in SPECS.items():
        path = root / "build" / "private-gates" / f"{name}.json"
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024: fail(f"missing or invalid {name}")
        try: value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError): fail(f"{name} is not valid JSON")
        if set(value) != {"contract", "name", "revision", "completedAt", "checks"} or value.get("contract") != CONTRACT or value.get("name") != name:
            fail(f"{name} contract mismatch")
        if value.get("revision") != revision or not isinstance(value.get("checks"), list) or set(value["checks"]) != expected or len(value["checks"]) != len(expected): fail(f"{name} revision or checks mismatch")
        try: completed = datetime.fromisoformat(value["completedAt"].replace("Z", "+00:00"))
        except (AttributeError, ValueError): fail(f"{name} completion time invalid")
        if completed.tzinfo is None or completed > now + timedelta(minutes=5) or now - completed > timedelta(hours=48): fail(f"{name} is outside the 48 hour validity window")
    print(f"v3-M2 release receipts passed for revision {revision[:12]}.")
    return 0


if __name__ == "__main__": raise SystemExit(main())
