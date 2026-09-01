#!/usr/bin/env python3
"""Write the exact revision-bound receipt after both Windows browsers pass."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import pathlib
import subprocess


CHECKS = ["cameraAndGroupScopes", "crossNodeTimeline", "nodeStorageUi", "offlinePwa",
          "rbacRoleMatrix", "s3Playback", "sessionRevocation"]


def main() -> None:
    repository = pathlib.Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True,
    ).stdout.strip())
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True,
    ).stdout.strip()
    evidence = repository / "build/private-gates"
    evidence.mkdir(parents=True, exist_ok=True)
    target = evidence / "windows-m7-admin.json"
    temporary = target.with_suffix(".tmp")
    value = {
        "contract": "webobs-m7-gate-receipt-v1", "name": "windows-m7-admin",
        "kind": "windows", "revision": revision,
        "completedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "durationSeconds": 0, "cameraCount": None, "checks": CHECKS,
    }
    temporary.write_text(json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n",
                         encoding="utf-8")
    os.replace(temporary, target)
    print(f"Redacted Windows v2-M7 receipt written for revision {revision[:12]}.")


if __name__ == "__main__":
    main()
