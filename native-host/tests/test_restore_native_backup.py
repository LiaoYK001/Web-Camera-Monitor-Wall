#!/usr/bin/env python3
"""Tests for inspecting and restoring native-host private-profile backups."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "native-host/scripts/restore_native_backup.py"
SPEC = importlib.util.spec_from_file_location("restore_native_backup", SCRIPT)
assert SPEC and SPEC.loader
restore_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(restore_module)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_install(base: Path) -> Path:
    root = base / "native"
    (root / "config/obs-studio").mkdir(parents=True)
    (root / "config/obs-studio/scenes").mkdir()
    (root / "webobs-native-prototype.json").write_text(
        json.dumps({"version": "4.1.0-dev.41", "obsCommit": "fb4d98bf"}), encoding="utf-8"
    )
    (root / "config/obs-studio/global.ini").write_text("current=1\n", encoding="utf-8")
    (root / "config/obs-studio/scenes/wall.json").write_text('{"wall":"current"}', encoding="utf-8")
    return root


def make_backup(root: Path, name: str = "config-4.1.0-dev.40-20261101T000000Z", files: dict | None = None) -> Path:
    backup = root / "backups" / name
    files = files if files is not None else {
        "obs-studio/global.ini": b"old=1\n",
        "obs-studio/scenes/wall.json": b'{"wall":"old"}',
    }
    entries = []
    for relative, data in files.items():
        target = backup / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        entries.append({"path": relative, "bytes": len(data), "sha256": sha256(data)})
    manifest = {
        "schema": 1,
        "kind": "native-config-upgrade-backup",
        "version": "4.1.0-dev.40",
        "createdAt": "2026-11-01T00:00:00Z",
        "source": "config",
        "files": len(entries),
        "bytes": sum(entry["bytes"] for entry in entries),
        "entries": entries,
    }
    (backup / "backup.json").write_text(json.dumps(manifest), encoding="utf-8")
    return backup


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), *args], capture_output=True, text=True, check=False
    )


class RestoreBackupTests(unittest.TestCase):
    def test_lists_and_validates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_install(Path(tmp))
            make_backup(root)
            result = run_cli("--install-root", str(root), "--list")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(len(payload["backups"]), 1)
            self.assertEqual(payload["backups"][0]["version"], "4.1.0-dev.40")
            self.assertEqual(payload["backups"][0]["files"], 2)

    def test_apply_replaces_config_and_keeps_pre_restore_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_install(Path(tmp))
            backup = make_backup(root)
            result = run_cli(
                "--install-root", str(root), "--backup", backup.name, "--apply",
                "--receipt", str(root / "receipt.json"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "config/obs-studio/global.ini").read_text(), "old=1\n")
            self.assertFalse((root / "config/obs-studio/scenes/current-only.txt").exists())
            snapshots = [
                path for path in (root / "backups").iterdir() if path.name.startswith("pre-restore-")
            ]
            self.assertEqual(len(snapshots), 1)
            snapshot_manifest = json.loads((snapshots[0] / "backup.json").read_text())
            self.assertEqual(snapshot_manifest["kind"], "native-config-pre-restore")
            self.assertEqual(
                (snapshots[0] / "obs-studio/global.ini").read_text(), "current=1\n"
            )
            receipt = json.loads((root / "receipt.json").read_text())
            self.assertEqual(receipt["restoredFrom"], backup.name)

    def test_rejects_tampered_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_install(Path(tmp))
            backup = make_backup(root)
            (backup / "obs-studio/global.ini").write_text("new=1\n")
            result = run_cli("--install-root", str(root), "--backup", backup.name)
            self.assertEqual(result.returncode, 1)
            self.assertIn("hash mismatch", result.stderr)

    def test_rejects_traversal_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_install(Path(tmp))
            backup = make_backup(root, files={"obs-studio/global.ini": b"old=1\n"})
            manifest = json.loads((backup / "backup.json").read_text())
            manifest["entries"].append({"path": "../escape.ini", "bytes": 1, "sha256": sha256(b"x")})
            manifest["files"] = len(manifest["entries"])
            manifest["bytes"] += 1
            (backup / "backup.json").write_text(json.dumps(manifest))
            result = run_cli("--install-root", str(root), "--backup", backup.name)
            self.assertEqual(result.returncode, 1)
            self.assertIn("unsafe entry path", result.stderr)

    def test_rejects_unlisted_extra_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_install(Path(tmp))
            backup = make_backup(root)
            (backup / "obs-studio/smuggled.txt").write_text("x")
            result = run_cli("--install-root", str(root), "--backup", backup.name)
            self.assertEqual(result.returncode, 1)
            self.assertIn("unlisted", result.stderr)

    def test_rejects_backup_outside_backups_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_install(Path(tmp))
            other = root / "other" / "config-x"
            other.mkdir(parents=True)
            (other / "backup.json").write_text("{}")
            result = run_cli("--install-root", str(root), "--backup", "../other/config-x")
            self.assertEqual(result.returncode, 1)
            self.assertIn("backup not found", result.stderr)

    def test_requires_prototype_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_install(Path(tmp))
            (root / "webobs-native-prototype.json").unlink()
            result = run_cli("--install-root", str(root), "--list")
            self.assertEqual(result.returncode, 2)
            self.assertIn("not a WebOBS native prototype", result.stderr)

    def test_list_skips_pre_restore_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_install(Path(tmp))
            make_backup(root)
            snapshot = root / "backups/pre-restore-20261101T010101Z"
            snapshot.mkdir()
            (snapshot / "backup.json").write_text(
                json.dumps({"schema": 1, "kind": "native-config-pre-restore", "files": 0, "bytes": 0})
            )
            result = run_cli("--install-root", str(root), "--list")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(len(payload["backups"]), 1)


if __name__ == "__main__":
    unittest.main()
