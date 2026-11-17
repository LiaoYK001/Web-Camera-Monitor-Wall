"""Make a separately inventoried next-version payload for the Windows update gate.

This is a qualification fixture with changed runtime identity, not a separately
released next version. It never changes the frozen input runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]


def prepare(runtime: Path, output: Path, version: str):
    spec = importlib.util.spec_from_file_location("upgrade_product_package",
                                                ROOT / "native-host/scripts/product_package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    before = module.verify(runtime)
    if output.exists() or output.is_symlink():
        raise ValueError("upgrade fixture requires a new directory")
    shutil.copytree(runtime, output)
    manifest_path = output / "webobs-native-prototype.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if before["version"] == version:
        raise ValueError("upgrade fixture must change the actual runtime version")
    manifest["version"] = version
    module.delivery(manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    inventory_path = output / "product-components.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["version"] = version
    entries = inventory["files"]
    entry = next(item for item in entries if item["path"] == manifest_path.name)
    entry["bytes"] = manifest_path.stat().st_size
    entry["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    inventory["totalBytesBeforeReceipt"] = sum(item["bytes"] for item in entries)
    inventory_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    after = module.verify(output)
    assert after["version"] == version
    assert json.loads((runtime / manifest_path.name).read_text())["version"] == before["version"]
    return {"from": before["version"], "to": after["version"],
            "distinctRuntimeIdentity": True, "sameSourceQualificationFixture": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.runtime, args.output, args.version)))
