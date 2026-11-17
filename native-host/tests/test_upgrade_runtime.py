"""Verify the upgrade fixture changes actual payload identity and remains inventoried."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "native-host/scripts"))
import product_package
import release_policy


def exercise():
    spec = importlib.util.spec_from_file_location("prepare_upgrade_runtime",
                                                Path(__file__).with_name("prepare_upgrade_runtime.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix="webobs-upgrade-payload-") as directory:
        root = Path(directory) / "original"
        root.mkdir()
        manifest = {"version": "5.1.0-rc.1", "productIntegration": True,
                    "obsCommit": product_package.OBS_COMMIT, "defaultProduct": False}
        release_policy.configure_complete(manifest)
        for name in product_package.REQUIRED | product_package.COMPLETE_REQUIRED:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"inert test file, never executable")
        (root / "webobs-native-prototype.json").write_text(json.dumps(manifest))
        files = [{"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size,
                  "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in root.rglob("*") if p.is_file()]
        receipt = {"schema": 1, "kind": "native-product-integration-components",
                   "sourceRevision": "a" * 40, "obsCommit": product_package.OBS_COMMIT,
                   "version": manifest["version"], "completeStaging": True,
                   **release_policy.copy_delivery(manifest), "files": files,
                   "totalBytesBeforeReceipt": sum(f["bytes"] for f in files)}
        (root / "product-components.json").write_text(json.dumps(receipt))
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        output = root.parent / "next"
        result = module.prepare(root, output, "5.1.0-rc.2")
        assert result["distinctRuntimeIdentity"] is True
        assert product_package.verify(output)["version"] == "5.1.0-rc.2"
        assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        changed = output / "services/product/supervisor.py"
        changed.write_bytes(b"changed after inventory")
        try:
            product_package.verify(output)
        except ValueError:
            pass
        else:
            raise AssertionError("upgrade inventory accepted changed payload bytes")
        print("PASS distinct runtime version/inventory, preserved original and tamper rejection")


if __name__ == "__main__":
    exercise()
