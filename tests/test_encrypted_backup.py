#!/usr/bin/env python3
"""Authenticated backup round-trip and corruption tests."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICE = pathlib.Path(os.environ.get(
    "WEBOBS_TEST_ENCRYPTED_BACKUP", ROOT / "backup" / "encrypted_backup.py"))
LOADER = importlib.machinery.SourceFileLoader("webobs_encrypted_backup", str(SERVICE))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC and SPEC.loader
backup = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = backup
SPEC.loader.exec_module(backup)


class BackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.sodium = backup.SodiumStream()
        except backup.BackupError as error:
            raise unittest.SkipTest(str(error)) from error

    def test_encrypted_round_trip_and_wrong_key_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            config = root / "webobs"
            config.mkdir()
            (config / "scene.json").write_text('{"schemaVersion":5}\n', encoding="utf-8")
            database = sqlite3.connect(config / "cluster.sqlite3")
            database.execute("CREATE TABLE fixture(value TEXT)")
            database.execute("INSERT INTO fixture VALUES('private')")
            database.commit()
            database.close()
            key = root / "key"
            key.write_bytes(bytes(range(32)))
            archive = backup.create(config, root / "backups", key, self.sodium)
            payload = archive.read_bytes()
            self.assertNotIn(b"private", payload)
            self.assertNotIn(b"schemaVersion", payload)
            wrong = root / "wrong"
            wrong.write_bytes(b"x" * 32)
            with self.assertRaises(backup.BackupError):
                backup.restore(root / "wrong-target", archive, wrong, self.sodium, True)
            rollback = backup.restore(config, archive, key, self.sodium, True)
            self.assertTrue(rollback.is_dir())
            self.assertEqual(sqlite3.connect(config / "cluster.sqlite3").execute(
                "SELECT value FROM fixture").fetchone()[0], "private")

    def test_restore_requires_explicit_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            archive = root / "fixture.wobk"
            archive.write_bytes(b"invalid")
            key = root / "key"
            key.write_bytes(b"k" * 32)
            with self.assertRaisesRegex(backup.BackupError, "confirmation"):
                backup.restore(root / "webobs", archive, key, self.sodium, False)


if __name__ == "__main__":
    unittest.main()
