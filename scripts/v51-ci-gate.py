#!/usr/bin/env python3
"""Read one WebOBS Windows CI run and summarize the next decision as JSON."""

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path


REPO = "LiaoYK001/Web-Camera-Monitor-Wall"
WORKFLOW = ".github/workflows/windows-obs-native-host.yaml"
PREFIX = "native-product-"


def gh(*args):
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=45)
    if proc.returncode:
        raise ValueError(f"gh {args[0]} failed (exit {proc.returncode})")
    return proc.stdout


def api(path):
    return json.loads(gh("api", f"repos/{REPO}/{path}"))


def read_receipts(run_id, artifact):
    with tempfile.TemporaryDirectory(prefix="webobs-v51-ci-") as folder:
        gh("run", "download", str(run_id), "--repo", REPO, "--name", artifact, "--dir", folder)
        reports = {}
        for path in sorted(Path(folder).glob(f"{PREFIX}*.json")):
            obj = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(obj, dict):
                raise ValueError(f"expected a JSON object in {path.name}")
            reports[path.stem.removeprefix(PREFIX)] = obj
        return reports


def inspect(args, report):
    route = f"actions/runs/{args.run_id}"
    run = api(route)
    report.update(status=run["status"], conclusion=run["conclusion"], actualSha=run["head_sha"],
                  branch=run["head_branch"], attempt=run["run_attempt"])
    if run["path"] != WORKFLOW or run["head_sha"] != args.sha:
        report["issue"] = "workflow or source SHA does not match the requested run"
        return "identity-mismatch", 4

    jobs = api(f"{route}/attempts/{run['run_attempt']}/jobs?per_page=100")["jobs"]
    steps = [step for job in jobs if job["name"] == "native-host" for step in job["steps"]]
    report["activeSteps"] = [step["name"] for step in steps if step["status"] == "in_progress"]
    report["failedSteps"] = [step["name"] for step in steps if step["conclusion"] == "failure"]
    if run["status"] != "completed":
        return "wait-for-ci", 2

    artifacts = api(f"{route}/artifacts?per_page=100")["artifacts"]
    names = [item["name"] for item in artifacts if not item["expired"]]
    bundle = f"native-product-integration-receipts-{args.version}"
    reports = read_receipts(args.run_id, bundle) if names.count(bundle) == 1 else {}
    report["receipts"] = list(reports)
    version = args.version
    rc_base, rc_number = version.rsplit(".", 1)
    upgraded_version = f"{rc_base}.{int(rc_number) + 1}"
    for name, row in reports.items():
        expected_version = upgraded_version if name == "upgraded-ui" else version
        if row.get("sourceRevision", args.sha) != args.sha or row.get("version", expected_version) != expected_version:
            report["issue"] = f"unexpected source SHA or version in {PREFIX}{name}.json"
            return "identity-mismatch", 4
    entry = reports.get("entry-ui", {})
    if "entry-ui" in reports and (entry.get("sourceRevision") != args.sha or entry.get("version") != version):
        report["issue"] = "missing portable entry identity"
        return "identity-mismatch", 4

    report["failureReceipts"] = [
        {"file": f"{PREFIX}{name}.json", "phase": row.get("failurePhase"),
         "detail": str(row.get("failureDetail") or "")[:300], "checkpoint": row.get("lastCheckpoint")}
        for name, row in reports.items() if row.get("passed") is False
    ]
    if "programTrackGain" in entry:
        report["programTrackGain"] = entry["programTrackGain"]
    if run["conclusion"] != "success":
        return "inspect-first-failure" if run["conclusion"] == "failure" else "inspect-ci-conclusion", 3

    required = {"entry-ui", "restore", "installed-ui", "nsis", "restore-pair", "legacy-import",
                "lan", "updater", "upgraded-ui"}
    issues = [f"{PREFIX}{name}.json missing or not passed"
              for name in sorted(required) if reports.get(name, {}).get("passed") is not True]
    for name in ("installed-ui", "nsis", "upgraded-ui"):
        if reports.get(name, {}).get("sourceRevision") != args.sha:
            issues.append(f"{PREFIX}{name}.json missing source SHA")
    nsis = reports.get("nsis", {})
    if any(nsis.get(key) is not True for key in ("freshInstalledEntryQualified", "sameMachineUpgradeQualified",
                                                "upgradedEntryQualified")):
        issues.append("NSIS fresh install or same-source upgrade is unqualified")
    if any(row.get("publicationForbidden") is True for row in reports.values()):
        issues.append("a receipt explicitly forbids publication")
    if names.count(f"webobs-wall-complete-candidate-{version}") != 1:
        issues.append("complete candidate installer artifact missing or ambiguous")
    size = reports.get("size-split", {})
    if size.get("sourceRevision") != args.sha or size.get("version") != version or not size.get("installedTree"):
        issues.append("missing same-source component size report")

    installed = reports.get("installed-ui", {})
    soak = installed.get("soak") or {}
    checks = installed.get("checks") or []
    if args.freeze and (nsis.get("soakMinutes") != 120 or soak.get("minutes") != 120
                        or "installed-soak-120-minutes-five-inputs" not in checks):
        issues.append("missing passed installed 120-minute five-input soak")
    lan = reports.get("lan", {})
    report["lan"] = {"httpsQualified": lan.get("lanHttpsQualified"),
                     "remoteDeviceQualified": lan.get("remoteDeviceQualified"),
                     "skipReason": lan.get("lanHttpsSkipReason")}
    report["issues"] = issues
    if issues:
        return "collect-missing-evidence", 4
    return "review-frozen-candidate" if args.freeze else "review-install-evidence", 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=int)
    parser.add_argument("--sha", required=True, help="expected full source SHA")
    parser.add_argument("--version", required=True, help="expected version in 5.1.0-rc.N form")
    parser.add_argument("--freeze", action="store_true", help="also require the installed two-hour soak")
    args = parser.parse_args()
    if args.run_id < 1 or not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        parser.error("expected a positive run ID and a full lowercase Git SHA")
    if not re.fullmatch(r"5\.1\.0-rc\.[1-9][0-9]*", args.version):
        parser.error("expected 5.1.0-rc.N with a positive RC number")
    report = {"runId": args.run_id, "expectedSha": args.sha, "version": args.version,
              "mode": "freeze" if args.freeze else "install"}
    try:
        result, code = inspect(args, report)
    except (KeyError, OSError, TypeError, ValueError, subprocess.TimeoutExpired) as exc:
        result, code = "cannot-read-evidence", 4
        report["issue"] = str(exc)[:300]
    print(json.dumps({**report, "result": result}, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
