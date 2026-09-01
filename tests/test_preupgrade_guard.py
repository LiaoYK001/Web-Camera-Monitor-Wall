#!/usr/bin/env python3
"""v2-M7 pre-upgrade snapshot, commit and rollback tests."""

import importlib.util
from importlib.machinery import SourceFileLoader
import os
import pathlib
import sqlite3
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICE = pathlib.Path(os.environ.get(
    "WEBOBS_TEST_PREUPGRADE_GUARD", ROOT / "backup/preupgrade_guard.py"))
LOADER = SourceFileLoader("preupgrade", str(SERVICE))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
guard = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(guard)


class PreUpgradeGuardTests(unittest.TestCase):
    def fixture(self, parent: pathlib.Path) -> pathlib.Path:
        root = parent / "webobs"; root.mkdir()
        (root / "scene.json").write_text('{"schemaVersion":5}\n', encoding="utf-8")
        database = sqlite3.connect(root / "registry.sqlite3")
        database.execute("CREATE TABLE fixture(value TEXT)")
        database.execute("INSERT INTO fixture VALUES('before')")
        database.commit(); database.close()
        return root

    def test_failed_upgrade_restores_exact_files_and_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(pathlib.Path(directory))
            self.assertTrue(guard.prepare(root))
            (root / "scene.json").write_text('{"schemaVersion":999}\n', encoding="utf-8")
            (root / "created-by-failed-migration.json").write_text("{}\n", encoding="utf-8")
            database = sqlite3.connect(root / "registry.sqlite3")
            database.execute("UPDATE fixture SET value='after'"); database.commit(); database.close()
            backup = guard.rollback(root)
            self.assertTrue(backup.is_dir())
            self.assertEqual((root / "scene.json").read_text(encoding="utf-8"), '{"schemaVersion":5}\n')
            self.assertFalse((root / "created-by-failed-migration.json").exists())
            database = sqlite3.connect(root / "registry.sqlite3")
            self.assertEqual(database.execute("SELECT value FROM fixture").fetchone()[0], "before")
            database.close()

    def test_successful_upgrade_commits_once_and_preserves_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(pathlib.Path(directory))
            self.assertTrue(guard.prepare(root))
            backup = guard.commit(root)
            self.assertIsNotNone(backup); self.assertTrue(backup.is_dir())
            self.assertTrue((root / guard.READY).is_file())
            self.assertFalse((root / guard.PENDING).exists())
            self.assertFalse(guard.prepare(root))
            self.assertIsNone(guard.commit(root))

    def test_corrupt_snapshot_fails_before_active_tree_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(pathlib.Path(directory))
            guard.prepare(root)
            backup = guard.pending_backup(root)
            (backup / "snapshot/scene.json").write_text("corrupt", encoding="utf-8")
            before = (root / "scene.json").read_bytes()
            with self.assertRaisesRegex(guard.UpgradeError, "digest"):
                guard.rollback(root)
            self.assertEqual((root / "scene.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
