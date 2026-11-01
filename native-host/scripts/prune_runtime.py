"""Remove non-runtime build products from the staged native host.

The prototype is assembled with `cmake --install`, whose Windows OBS install
rules also stage debug symbols. Those PDBs are build products, not runtime
files: they are not loaded by obs64, and the development installer packages
every byte. Strip them after both install steps and before stage.py writes the
file manifest, then prove that none survived.

The command is deliberately narrow. It only removes case-insensitive `*.pdb`
files inside the runtime tree and writes a receipt with the removed count and
bytes, so the size change is attributable and reproducible.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCHEMA = 1
RECEIPT_KIND = "native-runtime-prune"


def prune(runtime: Path) -> dict:
    runtime = runtime.resolve()
    if not runtime.is_dir():
        raise SystemExit(f"runtime is not a directory: {runtime}")
    removed: list[dict] = []
    for path in sorted(runtime.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".pdb":
            continue
        # Refuse anything that resolves outside the runtime tree, including a
        # symlinked or reparse-point parent.
        resolved = path.resolve()
        try:
            resolved.relative_to(runtime)
        except ValueError:
            raise SystemExit(f"refusing to remove outside the runtime: {resolved}")
        size = resolved.stat().st_size
        resolved.unlink()
        removed.append({"path": resolved.relative_to(runtime).as_posix(), "bytes": size})
    remaining = [
        path.relative_to(runtime).as_posix()
        for path in runtime.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdb"
    ]
    if remaining:
        raise SystemExit(f"PDB files survived pruning: {remaining[:5]}")
    return {
        "schema": SCHEMA,
        "kind": RECEIPT_KIND,
        "runtime": "runtime",
        "removedFiles": len(removed),
        "removedBytes": sum(item["bytes"] for item in removed),
        "remainingPdbFiles": 0,
        "removed": removed,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    receipt = prune(args.runtime)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(
        "pruned {} PDB files ({} bytes); no PDB remains".format(
            receipt["removedFiles"], receipt["removedBytes"]
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
