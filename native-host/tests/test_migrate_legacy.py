#!/usr/bin/env python3
"""Legacy config migration contracts: consistent SQLite, no overwrite, old bytes kept."""
from __future__ import annotations

from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def load():
    specification = importlib.util.spec_from_file_location(
        "native_migrate_legacy", ROOT / "native-host/scripts/migrate_legacy.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def make_legacy(source: Path):
    source.mkdir(parents=True)
    with closing(sqlite3.connect(source / "cluster.sqlite3")) as database:
        database.execute("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT)")
        database.execute("INSERT INTO users VALUES ('1', 'owner')")
        database.commit()
    with closing(sqlite3.connect(source / "cameras.db")) as database:
        database.execute("CREATE TABLE cameras (id TEXT PRIMARY KEY)")
        database.execute("INSERT INTO cameras VALUES ('camera-a')")
        database.commit()
    (source / "scene.json").write_text(json.dumps({
        "schemaVersion": 6, "revision": 1, "id": "scene-a", "name": "Scene A",
        "canvas": {"width": 1920, "height": 1080, "backgroundColor": "#000000"},
        "sources": [], "items": []}), encoding="utf-8")
    (source / "secrets").mkdir()
    (source / "secrets" / "camera.key").write_bytes(b"private")
    (source / "desktop.json").write_text(json.dumps({
        "recordingDirectory": str(source.parent / "Videos" / "WebOBS")}), encoding="utf-8")
    (source / "auth-sessions.db").write_bytes(b"must not migrate")


def exercise():
    migrate = load()
    with tempfile.TemporaryDirectory(prefix="webobs-migration-") as temporary:
        base = Path(temporary)
        source = base / "Legacy WebOBS" / "config"
        make_legacy(source)
        destination = base / "Native" / "config"
        receipt = migrate.migrate(source, destination, confirm_stopped=True, include_backup_key=False)
        assert receipt["status"] == "migrated" and receipt["sourcePreserved"] is True
        with closing(sqlite3.connect(destination / "cluster.sqlite3")) as database:
            assert database.execute("SELECT username FROM users").fetchone() == ("owner",)
        with closing(sqlite3.connect(destination / "cameras.db")) as database:
            assert database.execute("SELECT id FROM cameras").fetchone() == ("camera-a",)
        assert json.loads((destination / "scene.json").read_text())["id"] == "scene-a"
        assert (destination / "secrets" / "camera.key").read_bytes() == b"private"
        assert not (destination / "auth-sessions.db").exists()
        manifest = json.loads((destination / "native-migration.json").read_text())
        assert manifest["kind"] == "native-legacy-config-migration"
        assert manifest["recordingsPath"].endswith("Videos/WebOBS") or manifest["recordingsPath"].endswith("Videos\\WebOBS")
        assert (source / "cluster.sqlite3").is_file() and (source / "scene.json").is_file()
        try:
            migrate.migrate(source, destination, confirm_stopped=True, include_backup_key=False)
        except migrate.MigrationError:
            pass
        else:
            raise AssertionError("migration silently overwrote a non-empty profile")
        try:
            migrate.migrate(source, destination.parent / "other", confirm_stopped=False,
                            include_backup_key=False)
        except migrate.MigrationError:
            pass
        else:
            raise AssertionError("migration ignored the stopped-product confirmation")
        broken = base / "broken" / "config"
        broken.mkdir(parents=True)
        (broken / "scene.json").write_text("{", encoding="utf-8")
        try:
            migrate.migrate(broken, base / "broken-target", confirm_stopped=True,
                            include_backup_key=False)
        except migrate.MigrationError:
            pass
        else:
            raise AssertionError("migration accepted invalid JSON")
        assert not (base / "broken-target").exists() or not any((base / "broken-target").iterdir())
        print("PASS explicit legacy config migration keeps old data and rejects overwrite/invalid input")


def exercise_preview_workspaces():
    migrate = load()
    with tempfile.TemporaryDirectory(prefix="webobs-preview-migration-") as temporary:
        base = Path(temporary)
        root = base / "NativePreview"
        source = root / "config"
        source.mkdir(parents=True)
        with closing(sqlite3.connect(source / "cluster.sqlite3")) as database:
            database.execute("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT)")
            database.execute("INSERT INTO users VALUES ('a' * 32, 'preview-owner')")
            database.commit()
        profile = root / "native-profile"
        profile.mkdir()
        owner = "a" * 32
        workspace = profile / f"workspace-{owner}.json"
        workspace.write_text(json.dumps({"schema": 2, "sceneId": "fixture-five"}), encoding="utf-8")
        (profile / "workspace-not-an-account.json").write_text("{}", encoding="utf-8")
        (profile / ("workspace-" + "b" * 32 + ".json")).write_text("{", encoding="utf-8")
        destination = base / "Native" / "config"
        try:
            migrate.migrate(source, destination, confirm_stopped=True,
                            include_backup_key=False, include_preview_workspaces=True)
        except migrate.MigrationError:
            # The malformed workspace must abort the whole migration atomically.
            assert not destination.exists() or not any(destination.iterdir())
        else:
            raise AssertionError("migration accepted a malformed v4.5 workspace")
        (profile / ("workspace-" + "b" * 32 + ".json")).unlink()
        receipt = migrate.migrate(source, destination, confirm_stopped=True,
                                  include_backup_key=False, include_preview_workspaces=True)
        assert receipt["status"] == "migrated" and receipt["previewWorkspacesCopied"] == 1
        migrated = destination / "native-profile" / workspace.name
        assert migrated.read_bytes() == workspace.read_bytes()
        assert not (destination / "native-profile/workspace-not-an-account.json").exists()
        manifest = json.loads((destination / "native-migration.json").read_text())
        assert manifest["sourceKind"] == "explicit-native-preview"
        assert manifest["previewWorkspacesCopied"] == 1
        print("PASS v4.5 native preview migration keeps account workspace and rejects invalid entries")


if __name__ == "__main__":
    exercise()
    exercise_preview_workspaces()
