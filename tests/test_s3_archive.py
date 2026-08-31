#!/usr/bin/env python3
"""S3 SigV4 and bounded archive queue tests without external endpoints."""

from __future__ import annotations

import datetime as dt
import importlib.machinery
import importlib.util
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICE = pathlib.Path(__import__("os").environ.get(
    "WEBOBS_TEST_ARCHIVE_SERVICE", ROOT / "archive" / "s3_archive.py"))
LOADER = importlib.machinery.SourceFileLoader("webobs_s3_archive", str(SERVICE))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC and SPEC.loader
archive = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = archive
SPEC.loader.exec_module(archive)


class ArchiveTests(unittest.TestCase):
    def config(self) -> dict:
        return {"host": "s3.example.test", "port": 443, "bucket": "webobs-archive",
                "region": "us-east-1", "accessKeyId": "AKIDEXAMPLE",
                "secretAccessKey": "example-secret-value"}

    def test_sigv4_is_deterministic_and_never_places_secret_in_headers(self) -> None:
        client = archive.S3Client(self.config())
        headers = client.headers("PUT", "segments/aa/" + "a" * 64, "a" * 64, 1024,
                                 dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc))
        self.assertEqual(headers["X-Amz-Date"], "20260102T030405Z")
        self.assertIn("Credential=AKIDEXAMPLE/20260102/us-east-1/s3/aws4_request", headers["Authorization"])
        self.assertNotIn("example-secret-value", str(headers))

    def test_queue_is_idempotent_bounded_and_backoff_is_capped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = archive.ArchiveQueue(pathlib.Path(directory) / "queue.sqlite3")
            self.assertTrue(queue.enqueue("segment-1", "segments/aa/object"))
            self.assertTrue(queue.enqueue("segment-1", "segments/aa/object"))
            self.assertEqual(queue.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
            claimed = queue.claim()
            self.assertEqual(claimed["segment_id"], "segment-1")
            for _ in range(20):
                queue.retry("segment-1", "fixture_failure")
                queue.db.execute("UPDATE jobs SET state='uploading' WHERE segment_id='segment-1'")
            row = queue.db.execute("SELECT * FROM jobs WHERE segment_id='segment-1'").fetchone()
            self.assertLessEqual(row["next_attempt_at"] - row["updated_at"], 300)
            queue.db.close()

    def test_request_rejects_path_traversal_and_invalid_digest_before_network(self) -> None:
        client = archive.S3Client(self.config())
        with self.assertRaises(archive.ArchiveError):
            client.request("PUT", "../secret", "a" * 64, 1, b"x")
        with self.assertRaises(archive.ArchiveError):
            client.request("PUT", "segments/object", "invalid", 1, b"x")


if __name__ == "__main__":
    unittest.main()
