#!/usr/bin/env python3
"""Generate the six-run alternating P5 campaign schedule; never a performance verdict."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from common import SCHEMA, digest, metadata, new_private_directory, read_json, write_json

PAIRS = 3
BOUNDARIES = (
    "The plan is an operator aid only: it expands one validated metadata template into three alternating product/OBS "
    "pairs, but creates no measurements, starts no OBS process and never marks the campaign qualified. Each run still "
    "needs its own preflight result, operator window setup and a fresh private output directory."
)


def _run_id(campaign: str, pair: int, position: int, variant: str) -> str:
    value = f"{campaign}-p{pair:02d}-{'product' if position == 1 else 'obs'}"
    if len(value) > 64:
        raise ValueError("campaignId is too long to derive per-run ids (max 64 characters)")
    return value


def build(template_path: Path, output: Path, preflight_path: Path | None = None) -> dict:
    template = read_json(template_path)
    base = metadata(template)
    if base["variant"] != "product" or base["position"] != 1 or base["pairIndex"] != 1:
        raise ValueError("Template must describe pair 1 position 1 (variant=product) before expansion")
    if not all(base["declarations"].values()):
        raise ValueError("Every operator declaration must be confirmed before scheduling a campaign")
    preflight = None
    if preflight_path is not None:
        receipt = read_json(preflight_path)
        if receipt.get("kind") != "native-p5-preflight" or receipt.get("status") != "pass":
            raise ValueError("Preflight receipt must be a passing native-p5-preflight")
        if receipt.get("qualified") is not False or receipt.get("diagnostic") is not False:
            raise ValueError("Preflight receipt must be non-qualifying and non-diagnostic")
        preflight = {"sha256": digest(preflight_path), "generatedAt": receipt.get("generatedAt"),
                     "environment": receipt.get("environment")}
    campaign = base["campaignId"]
    runs = []
    for pair in range(1, PAIRS + 1):
        for position, variant in ((1, "product"), (2, "obs")):
            value = json.loads(json.dumps(template))
            value.update({"runId": _run_id(campaign, pair, position, variant), "pairId": f"{campaign}-pair{pair:02d}",
                          "pairIndex": pair, "position": position, "variant": variant})
            checked = metadata(value)
            name = f"run-{len(runs) + 1:02d}-{variant}.json"
            runs.append({"order": len(runs) + 1, "pairIndex": pair, "position": position, "variant": variant,
                         "runId": checked["runId"], "pairId": checked["pairId"], "metadataFile": name})
    if len({run["runId"] for run in runs}) != len(runs):
        raise ValueError("Derived run ids are not unique")
    plan = {
        "schemaVersion": SCHEMA,
        "kind": "native-p5-campaign-plan",
        "status": "planned",
        "qualified": False,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "campaignId": campaign,
        "templateSha256": digest(template_path),
        "preflight": preflight,
        "pairs": PAIRS,
        "runs": runs,
        "boundaries": BOUNDARIES,
    }
    new_private_directory(output)
    for run in runs:
        value = json.loads(json.dumps(template))
        value.update({"runId": run["runId"], "pairId": run["pairId"], "pairIndex": run["pairIndex"],
                      "position": run["position"], "variant": run["variant"]})
        write_json(output / run["metadataFile"], value)
    write_json(output / "plan.json", plan)
    (output / "README.txt").write_text(
        "Private P5 campaign plan. Not a performance receipt. Run each pair with a preflight result and the collector; "
        "keep this directory outside every Git tree.\n", encoding="utf-8")
    return plan


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Expand validated P5 metadata into three alternating pairs.")
    result.add_argument("--template", type=Path, required=True,
                        help="pair-1/position-1 metadata with anonymous identities and five h265 inputs")
    result.add_argument("--output", type=Path, required=True, help="New absolute private directory outside every Git tree")
    result.add_argument("--preflight", type=Path, help="Optional passing non-diagnostic preflight receipt to bind")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        plan = build(args.template, args.output, args.preflight)
    except (ValueError, OSError) as error:
        print(f"campaign plan failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": plan["status"], "campaignId": plan["campaignId"], "runs": len(plan["runs"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
