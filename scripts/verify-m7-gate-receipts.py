#!/usr/bin/env python3
"""Fail closed unless every revision-bound v2-M7 private gate passed."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
from typing import Any, NoReturn


CONTRACT = "webobs-m7-gate-receipt-v1"
MAX_AGE = timedelta(hours=48)
SPECS: dict[str, dict[str, Any]] = {
    "m7-scale-8": {
        "kind": "scale", "cameraCount": 8, "minimumDurationSeconds": 900,
        "checks": {"controllerThreeRecorders", "threeStorageVolumes", "assignmentsAccepted",
                   "recordingAllNodes", "catalogIntegrity", "resourceCapacityReported",
                   "archivedPlaybackVerified"},
    },
    "m7-scale-16": {
        "kind": "scale", "cameraCount": 16, "minimumDurationSeconds": 900,
        "checks": {"controllerThreeRecorders", "threeStorageVolumes", "assignmentsAccepted",
                   "recordingAllNodes", "catalogIntegrity", "resourceCapacityReported",
                   "archivedPlaybackVerified"},
    },
    "m7-scale-32": {
        "kind": "scale", "cameraCount": 32, "minimumDurationSeconds": 900,
        "checks": {"controllerThreeRecorders", "threeStorageVolumes", "assignmentsAccepted",
                   "recordingAllNodes", "catalogIntegrity", "resourceCapacityReported",
                   "archivedPlaybackVerified"},
    },
    "m7-faults": {
        "kind": "fault", "cameraCount": None, "minimumDurationSeconds": 0,
        "checks": {"controllerIsolationBounded", "recorderFailureDetected",
                   "minioOutageRecordingContinues", "readOnlyVolumeRejected",
                   "staleGenerationRejected", "clockSkewRejected", "mqttReconnectBounded",
                   "archiveDigestVerified", "backupRestoreVerified"},
    },
    "windows-m7-admin": {
        "kind": "windows", "cameraCount": None, "minimumDurationSeconds": 0,
        "checks": {"rbacRoleMatrix", "cameraAndGroupScopes", "nodeStorageUi",
                   "crossNodeTimeline", "s3Playback", "offlinePwa", "sessionRevocation"},
    },
}


def fail(message: str) -> NoReturn:
    raise SystemExit(f"v2-M7 release gate rejected: {message}")


def repository_revision() -> tuple[Path, str]:
    repository = Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], check=True,
        capture_output=True, text=True,
    ).stdout.strip()).resolve()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    return repository, revision


def validate_receipt(path: Path, name: str, spec: dict[str, Any], revision: str,
                     now: datetime) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
        fail(f"missing or invalid {name} receipt")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail(f"{name} receipt is not valid UTF-8 JSON")
    expected_fields = {"contract", "name", "kind", "revision", "completedAt",
                       "durationSeconds", "cameraCount", "checks"}
    if not isinstance(receipt, dict) or set(receipt) != expected_fields:
        fail(f"{name} receipt contains unknown or missing fields")
    if receipt["contract"] != CONTRACT or receipt["name"] != name or receipt["kind"] != spec["kind"]:
        fail(f"{name} receipt contract does not match")
    if receipt["revision"] != revision:
        fail(f"{name} receipt belongs to a different revision")
    if receipt["cameraCount"] != spec["cameraCount"]:
        fail(f"{name} receipt camera count does not match")
    duration = receipt["durationSeconds"]
    if isinstance(duration, bool) or not isinstance(duration, int) or duration < spec["minimumDurationSeconds"]:
        fail(f"{name} receipt duration is below the required minimum")
    checks = receipt["checks"]
    if not isinstance(checks, list) or set(checks) != spec["checks"] or len(checks) != len(spec["checks"]):
        fail(f"{name} receipt does not contain the exact required checks")
    try:
        completed_at = datetime.fromisoformat(receipt["completedAt"].replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        fail(f"{name} receipt has an invalid completion time")
    if completed_at.tzinfo is None or completed_at > now + timedelta(minutes=5):
        fail(f"{name} receipt completion time is invalid")
    if now - completed_at > MAX_AGE:
        fail(f"{name} receipt is older than 48 hours")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, default=Path("build/private-gates"))
    args = parser.parse_args()
    repository, revision = repository_revision()
    evidence_dir = ((repository / args.evidence_dir).resolve()
                    if not args.evidence_dir.is_absolute() else args.evidence_dir.resolve())
    now = datetime.now(timezone.utc)
    for name, spec in SPECS.items():
        validate_receipt(evidence_dir / f"{name}.json", name, spec, revision, now)
    print(f"v2-M7 release receipts passed for revision {revision[:12]}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
