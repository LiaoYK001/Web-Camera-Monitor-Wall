"""Export only clean, fully checked bytes for the explicitly scoped v4.5 preview."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from product_package import verify, bounded_json, digest
from release_policy import PREVIEW_PROFILE


def export(build, output, revision):
    build, output = Path(build), Path(output)
    runtime = build / "runtime"
    payload = verify(runtime)
    if payload.get("releaseProfile") != PREVIEW_PROFILE or payload["sourceRevision"] != revision:
        raise ValueError("not the requested preview source")
    receipts = {}
    for name in ("entry-ui", "restore", "installed-ui", "nsis"):
        path = build / f"native-product-{name}.json"
        receipt = bounded_json(path, 2 * 1024 * 1024)
        if receipt.get("passed") is not True or receipt.get("sourceRevision") != revision or \
                receipt.get("fullFeatureMigrationQualified") is not False:
            raise ValueError("missing matching successful product qualification")
        if name != "restore" and receipt.get("version") != "4.5.0":
            raise ValueError("qualification version mismatch")
        receipts[name] = receipt
    nsis = receipts["nsis"]
    installer = build / "internal-installer/WebOBS-Wall-4.5.0-windows-x64-PREVIEW-UNSIGNED.exe"
    if nsis.get("freshInstalledEntryQualified") is not True or nsis.get("publicationForbidden") is not False or \
            nsis.get("legacyUpgradeQualified") is not False or installer.stat().st_size != nsis["setupBytes"] or \
            digest(installer) != nsis["setupSha256"]:
        raise ValueError("installer was not the qualified preview bytes")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(installer, output / installer.name)
    shutil.copy2(runtime / "START-HERE.md", output / "START-HERE.md")
    archive = output / "WebOBS-Wall-4.5.0-windows-x64-PREVIEW.zip"
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for name in payload["files"]:
            bundle.write(runtime / name, "WebOBS-Wall-4.5/" + name)
    record = {"schema": 1, "version": "4.5.0", "tag": "v4.5", "sourceRevision": revision,
              "releaseProfile": PREVIEW_PROFILE, "prerelease": True, "stableUpdaterEnabled": False,
              "legacyUpgradeQualified": False, "fullFeatureMigrationQualified": False,
              "obsPerformanceParityQualified": False, "qualification": receipts}
    (output / "v4.5-qualification.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    checks = [f"{digest(path)}  {path.name}" for path in sorted(output.iterdir()) if path.is_file()]
    (output / "SHA256SUMS.txt").write_text("\n".join(checks) + "\n", encoding="ascii")
    return {"files": len(checks) + 1, "sourceRevision": revision}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.build, args.output, args.revision)))
