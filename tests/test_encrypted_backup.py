#!/usr/bin/env python3
"""Authenticated backup round-trip and corruption tests."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


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

    def test_native_profile_is_restored_with_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            config = root / "webobs"
            config.mkdir()
            (config / "scene.json").write_text('{"schemaVersion":5}\n', encoding="utf-8")
            native = root / "native-profile"
            workspace = native / ("obs-studio/plugin_config/webobs-native-host/workspace-" + "a" * 32 + ".json")
            workspace.parent.mkdir(parents=True)
            workspace.write_text('{"schema":2,"sceneId":"fixture"}\n', encoding="utf-8")
            key = root / "key"
            key.write_bytes(bytes(range(32)))
            archive = backup.create(config, root / "backups", key, self.sodium, native)
            workspace.write_text('{"schema":2,"sceneId":"mutated"}\n', encoding="utf-8")
            (config / "scene.json").write_text('{"schemaVersion":4}\n', encoding="utf-8")
            rollback = backup.restore(config, archive, key, self.sodium, True, native)
            self.assertTrue(rollback.is_dir())
            self.assertEqual(workspace.read_text(encoding="utf-8"), '{"schema":2,"sceneId":"fixture"}\n')
            self.assertEqual((config / "scene.json").read_text(encoding="utf-8"), '{"schemaVersion":5}\n')

    def test_config_only_archive_keeps_existing_native_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            config = root / "webobs"
            config.mkdir()
            (config / "scene.json").write_text('{"schemaVersion":5}\n', encoding="utf-8")
            key = root / "key"
            key.write_bytes(bytes(range(32)))
            archive = backup.create(config, root / "backups", key, self.sodium)
            native = root / "native-profile"
            native.mkdir()
            (native / "user.ini").write_text("[BasicWindow]\nPreviewProgramMode=true\n", encoding="utf-8")
            backup.restore(config, archive, key, self.sodium, True, native)
            self.assertEqual((native / "user.ini").read_text(encoding="utf-8"),
                             "[BasicWindow]\nPreviewProgramMode=true\n")

    def seed_pair(self, root: pathlib.Path) -> pathlib.Path:
        """Create a configuration directory plus a native profile and their key."""
        config = root / "webobs"
        config.mkdir()
        (config / "scene.json").write_text('{"schemaVersion":5}\n', encoding="utf-8")
        native = root / "native-profile"
        native.mkdir()
        (native / "product-state.json").write_text('{"sceneId":"original"}\n', encoding="utf-8")
        key = root / "key"
        key.write_bytes(bytes(range(32)))
        return key

    def mutate_pair(self, root: pathlib.Path) -> None:
        (root / "webobs" / "scene.json").write_text('{"schemaVersion":4}\n', encoding="utf-8")
        (root / "native-profile" / "product-state.json").write_text('{"sceneId":"current"}\n', encoding="utf-8")

    def read_pair(self, root: pathlib.Path) -> tuple[str, str]:
        return (root / "webobs" / "scene.json").read_text(encoding="utf-8"), \
            (root / "native-profile" / "product-state.json").read_text(encoding="utf-8")

    def test_native_archive_refuses_a_restore_without_a_named_native_root(self) -> None:
        # Restoring one half of a paired archive would leave configuration and
        # native profile from different generations.
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            key = self.seed_pair(root)
            archive = backup.create(root / "webobs", root / "backups", key, self.sodium,
                                    root / "native-profile")
            self.mutate_pair(root)
            with self.assertRaisesRegex(backup.BackupError, "must name the native profile"):
                backup.restore(root / "webobs", archive, key, self.sodium, True)
            self.assertEqual(self.read_pair(root), ('{"schemaVersion":4}\n', '{"sceneId":"current"}\n'))
            self.assertFalse(list(root.glob(".webobs-restore-*")))
            self.assertFalse((root / backup.JOURNAL_NAME).exists())

    def test_failed_swap_restores_the_previous_pair_and_leaves_no_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            key = self.seed_pair(root)
            archive = backup.create(root / "webobs", root / "backups", key, self.sodium,
                                    root / "native-profile")
            self.mutate_pair(root)
            real_replace = os.replace

            def refuse_landing(source, destination):
                if pathlib.Path(source).name.startswith(".webobs-restore-"):
                    raise OSError("simulated failure while landing the configuration directory")
                return real_replace(source, destination)

            with mock.patch("os.replace", side_effect=refuse_landing):
                with self.assertRaises(OSError):
                    backup.restore(root / "webobs", archive, key, self.sodium, True,
                                   root / "native-profile")
            self.assertEqual(self.read_pair(root), ('{"schemaVersion":4}\n', '{"sceneId":"current"}\n'))
            self.assertFalse((root / backup.JOURNAL_NAME).exists())
            for prefix in (".webobs-restore-", ".webobs-native-restore-", ".webobs-decrypt-"):
                self.assertFalse(list(root.glob(f"{prefix}*")), f"{prefix} staging survived")

    def test_crash_before_the_configuration_lands_rolls_back_to_the_old_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            key = self.seed_pair(root)
            archive = backup.create(root / "webobs", root / "backups", key, self.sodium,
                                    root / "native-profile")
            self.mutate_pair(root)
            real_replace = os.replace

            def crash(source, destination):
                if pathlib.Path(destination).name.startswith(".webobs-rollback-"):
                    raise KeyboardInterrupt("simulated process loss")
                return real_replace(source, destination)

            with mock.patch("os.replace", side_effect=crash):
                with self.assertRaises(KeyboardInterrupt):
                    backup.restore(root / "webobs", archive, key, self.sodium, True,
                                   root / "native-profile")
            self.assertTrue((root / backup.JOURNAL_NAME).is_file())
            self.assertEqual(backup.recover_interrupted(root / backup.JOURNAL_NAME), "rolled-back")
            self.assertFalse((root / backup.JOURNAL_NAME).exists())
            self.assertEqual(self.read_pair(root), ('{"schemaVersion":4}\n', '{"sceneId":"current"}\n'))
            self.assertFalse(list(root.glob(".webobs-restore-*")))
            self.assertFalse(list(root.glob(".webobs-native-restore-*")))

    def test_crash_after_both_swaps_returns_both_halves_as_a_pair(self) -> None:
        # Killing the restore between the native swap-out and the configuration
        # landing used to put the configuration back while the OBS profile stayed
        # parked, which is exactly the mismatched pair this journal exists to stop.
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            key = self.seed_pair(root)
            archive = backup.create(root / "webobs", root / "backups", key, self.sodium,
                                    root / "native-profile")
            self.mutate_pair(root)
            real_replace = os.replace

            def crash(source, destination):
                if pathlib.Path(source).name.startswith(".webobs-restore-"):
                    raise KeyboardInterrupt("simulated process loss")
                return real_replace(source, destination)

            with mock.patch("os.replace", side_effect=crash):
                with self.assertRaises(KeyboardInterrupt):
                    backup.restore(root / "webobs", archive, key, self.sodium, True,
                                   root / "native-profile")
            self.assertFalse((root / "webobs").exists())
            self.assertFalse((root / "native-profile").exists())
            self.assertTrue((root / backup.JOURNAL_NAME).is_file())
            self.assertEqual(backup.recover_interrupted(root / backup.JOURNAL_NAME), "rolled-back")
            self.assertFalse((root / backup.JOURNAL_NAME).exists())
            self.assertEqual(self.read_pair(root), ('{"schemaVersion":4}\n', '{"sceneId":"current"}\n'))
            for prefix in (".webobs-restore-", ".webobs-native-restore-",
                           ".webobs-rollback-", ".webobs-native-rollback-"):
                self.assertFalse(list(root.glob(f"{prefix}*")), f"{prefix} survived the pair recovery")

    def test_recovery_parks_a_later_profile_and_lands_the_matching_pair(self) -> None:
        # A crash after the configuration landed leaves the archive's staged
        # profile to land. If a start without recovery already created a profile,
        # its bytes are kept parked instead of overwritten or deleted.
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            key = self.seed_pair(root)
            archive = backup.create(root / "webobs", root / "backups", key, self.sodium,
                                    root / "native-profile")
            self.mutate_pair(root)
            real_replace = os.replace

            def crash(source, destination):
                if pathlib.Path(source).name.startswith(".webobs-native-restore-"):
                    raise KeyboardInterrupt("simulated process loss")
                return real_replace(source, destination)

            with mock.patch("os.replace", side_effect=crash):
                with self.assertRaises(KeyboardInterrupt):
                    backup.restore(root / "webobs", archive, key, self.sodium, True,
                                   root / "native-profile")
            later = root / "native-profile"
            later.mkdir()
            (later / "product-state.json").write_text('{"sceneId":"recreated"}\n', encoding="utf-8")
            self.assertEqual(backup.recover_interrupted(root / backup.JOURNAL_NAME), "completed")
            self.assertFalse((root / backup.JOURNAL_NAME).exists())
            self.assertEqual((root / "webobs" / "scene.json").read_text(encoding="utf-8"),
                             '{"schemaVersion":5}\n')
            self.assertEqual((later / "product-state.json").read_text(encoding="utf-8"),
                             '{"sceneId":"original"}\n')
            parked = sorted(root.glob(".webobs-native-parked-*"))
            self.assertEqual(len(parked), 1, "the later profile must stay parked")
            self.assertEqual((parked[0] / "product-state.json").read_text(encoding="utf-8"),
                             '{"sceneId":"recreated"}\n')
            self.assertFalse(list(root.glob(".webobs-native-restore-*")))

    def test_crash_after_the_configuration_lands_completes_the_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            key = self.seed_pair(root)
            archive = backup.create(root / "webobs", root / "backups", key, self.sodium,
                                    root / "native-profile")
            self.mutate_pair(root)
            real_replace = os.replace

            def crash(source, destination):
                if pathlib.Path(source).name.startswith(".webobs-native-restore-"):
                    raise KeyboardInterrupt("simulated process loss")
                return real_replace(source, destination)

            with mock.patch("os.replace", side_effect=crash):
                with self.assertRaises(KeyboardInterrupt):
                    backup.restore(root / "webobs", archive, key, self.sodium, True,
                                   root / "native-profile")
            self.assertEqual((root / "webobs" / "scene.json").read_text(encoding="utf-8"),
                             '{"schemaVersion":5}\n')
            self.assertFalse((root / "native-profile").exists())
            self.assertTrue((root / backup.JOURNAL_NAME).is_file())
            self.assertEqual(backup.recover_interrupted(root / backup.JOURNAL_NAME), "completed")
            self.assertEqual(self.read_pair(root), ('{"schemaVersion":5}\n', '{"sceneId":"original"}\n'))
            self.assertFalse(list(root.glob(".webobs-native-restore-*")))

    def test_stale_journal_recovers_and_a_broken_journal_blocks_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            key = self.seed_pair(root)
            archive = backup.create(root / "webobs", root / "backups", key, self.sodium,
                                    root / "native-profile")
            self.mutate_pair(root)
            self.assertIsNone(backup.recover_interrupted(root / backup.JOURNAL_NAME))
            (root / backup.JOURNAL_NAME).write_text('{"schema":1,"state":"prepared"}\n', encoding="utf-8")
            with self.assertRaisesRegex(backup.BackupError, "invalid"):
                backup.recover_interrupted(root / backup.JOURNAL_NAME)
            staged = root / ".webobs-restore-staged"
            staged.mkdir()
            (root / backup.JOURNAL_NAME).write_text(json.dumps({
                "schema": 1, "state": "prepared", "configRoot": str(root / "webobs"),
                "configActivated": str(staged)}), encoding="utf-8")
            # Nothing had landed yet: the staged copy is dropped and the journal
            # cleared, so the next restore can proceed.
            self.assertEqual(backup.recover_interrupted(root / backup.JOURNAL_NAME), "rolled-back")
            self.assertFalse(staged.exists())
            self.assertEqual(self.read_pair(root), ('{"schemaVersion":4}\n', '{"sceneId":"current"}\n'))
            # A journal whose staged copies are already gone describes a
            # completed swap; the retained rollback directories are not deleted.
            (root / backup.JOURNAL_NAME).write_text(json.dumps({
                "schema": 1, "state": "prepared", "configRoot": str(root / "webobs"),
                "configActivated": str(root / ".webobs-restore-gone"),
                "nativeProfile": str(root / "native-profile"),
                "nativeActivated": str(root / ".webobs-native-restore-gone")}), encoding="utf-8")
            self.assertEqual(backup.recover_interrupted(root / backup.JOURNAL_NAME), "completed")
            self.assertEqual(self.read_pair(root), ('{"schemaVersion":4}\n', '{"sceneId":"current"}\n'))
            (root / backup.JOURNAL_NAME).write_text('{"schema":2,"state":"prepared"}\n', encoding="utf-8")
            with self.assertRaisesRegex(backup.BackupError, "invalid"):
                backup.recover_interrupted(root / backup.JOURNAL_NAME)
            (root / backup.JOURNAL_NAME).write_text("not json\n", encoding="utf-8")
            with self.assertRaisesRegex(backup.BackupError, "unreadable"):
                backup.recover_interrupted(root / backup.JOURNAL_NAME)
            self.assertTrue((root / "webobs" / "scene.json").is_file())
            # A restore refuses to run while an unreadable journal is present.
            with self.assertRaisesRegex(backup.BackupError, "unreadable"):
                backup.restore(root / "webobs", archive, key, self.sodium, True,
                               root / "native-profile")

    def test_nonlocal_backup_uses_pinned_s3_module_and_digest_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            archive = root / "fixture.wobk"
            archive.write_bytes(b"encrypted-fixture")
            config = root / "archive.json"
            config.write_text("{}\n", encoding="utf-8")
            marker = root / "upload.txt"
            implementation = root / "webobs-s3-archive"
            implementation.write_text(
                "import pathlib\n"
                "def load_config(path): return {'marker': str(path.parent / 'upload.txt')}\n"
                "class S3Client:\n"
                "  def __init__(self, config, ca): self.marker = pathlib.Path(config['marker'])\n"
                "  def upload_verified(self, path, key, digest, size):\n"
                "    self.marker.write_text(f'{key}|{digest}|{size}', encoding='ascii')\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {
                "WEBOBS_BACKUP_S3_TARGET_ID": "archive-main",
                "WEBOBS_BACKUP_S3_CONFIG": str(config),
                "WEBOBS_ARCHIVE_COMMAND": str(implementation),
            }, clear=False):
                digest = backup.upload_s3(archive, "archive-main")
            self.assertEqual(digest, backup.file_sha256(archive))
            self.assertEqual(marker.read_text(encoding="ascii"),
                             f"backups/{digest[:2]}/{digest}.wobk|{digest}|17")
            executable = root / "webobs-s3-archive.exe"
            executable.write_bytes(b"MZ native entrypoint, not Python source")
            with mock.patch.dict(os.environ, {
                "WEBOBS_BACKUP_S3_TARGET_ID": "archive-main",
                "WEBOBS_BACKUP_S3_CONFIG": str(config),
                "WEBOBS_ARCHIVE_COMMAND": str(executable),
                "WEBOBS_ARCHIVE_PYTHON_MODULE": str(implementation),
            }, clear=False):
                self.assertEqual(backup.upload_s3(archive, "archive-main"), digest)
            with self.assertRaisesRegex(backup.BackupError, "nonlocal_target_unavailable"):
                backup.upload_s3(archive, "archive-other")


if __name__ == "__main__":
    unittest.main()
