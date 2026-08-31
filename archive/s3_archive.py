#!/usr/bin/env python3
"""Bounded asynchronous S3-compatible segment archiver for WebOBS v2-M7."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import hmac
import http.client
import json
import os
import pathlib
import re
import sqlite3
import ssl
import threading
import time
from typing import Any
from urllib.parse import quote, urlsplit


MAX_QUEUE = 4096
MAX_WORKERS = 2
MAX_OBJECT = 64 * 1024 * 1024 * 1024
DIGEST = re.compile(r"^[0-9a-f]{64}$")
VOLUME_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class ArchiveError(RuntimeError):
    pass


def load_config(path: pathlib.Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 64 * 1024:
        raise ArchiveError("archive configuration is unavailable")
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"endpoint", "bucket", "region", "credentialsFile"}
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - required:
        raise ArchiveError("archive configuration fields are invalid")
    endpoint = urlsplit(value["endpoint"])
    if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password or \
            endpoint.query or endpoint.fragment or endpoint.path not in {"", "/"}:
        raise ArchiveError("archive endpoint must be an HTTPS authority")
    if not isinstance(value["bucket"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", value["bucket"]):
        raise ArchiveError("archive bucket is invalid")
    secret = pathlib.Path(value["credentialsFile"])
    try:
        secret.relative_to("/run/secrets")
    except ValueError as error:
        raise ArchiveError("archive credentials must be mounted below /run/secrets") from error
    if not secret.is_file() or secret.is_symlink() or secret.stat().st_size > 4096:
        raise ArchiveError("archive credentials are unavailable")
    credentials = json.loads(secret.read_text(encoding="utf-8"))
    if not isinstance(credentials, dict) or set(credentials) != {"accessKeyId", "secretAccessKey"} or \
            not all(isinstance(item, str) and 8 <= len(item) <= 256 for item in credentials.values()):
        raise ArchiveError("archive credentials are invalid")
    return {**value, "host": endpoint.hostname, "port": endpoint.port or 443,
            "accessKeyId": credentials["accessKeyId"], "secretAccessKey": credentials["secretAccessKey"]}


def signing_key(secret: str, date: str, region: str) -> bytes:
    date_key = hmac.new(("AWS4" + secret).encode(), date.encode(), hashlib.sha256).digest()
    region_key = hmac.new(date_key, region.encode(), hashlib.sha256).digest()
    service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
    return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


class S3Client:
    def __init__(self, config: dict[str, Any], ca_file: str = ""):
        self.config = config
        self.context = ssl.create_default_context(cafile=ca_file or None)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2

    def headers(self, method: str, object_key: str, payload_hash: str, size: int,
                timestamp: dt.datetime | None = None) -> dict[str, str]:
        timestamp = timestamp or dt.datetime.now(dt.timezone.utc)
        amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ")
        short_date = timestamp.strftime("%Y%m%d")
        host = self.config["host"] if self.config["port"] == 443 else f"{self.config['host']}:{self.config['port']}"
        metadata = payload_hash
        canonical_headers = (f"content-length:{size}\nhost:{host}\n"
                             f"x-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
                             f"x-amz-meta-sha256:{metadata}\n")
        signed_headers = "content-length;host;x-amz-content-sha256;x-amz-date;x-amz-meta-sha256"
        canonical_uri = f"/{quote(self.config['bucket'], safe='')}/{quote(object_key, safe='/')}"
        canonical_request = "\n".join([method, canonical_uri, "", canonical_headers, signed_headers, payload_hash])
        scope = f"{short_date}/{self.config['region']}/s3/aws4_request"
        string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope,
                                     hashlib.sha256(canonical_request.encode()).hexdigest()])
        signature = hmac.new(signing_key(self.config["secretAccessKey"], short_date,
                                         self.config["region"]), string_to_sign.encode(), hashlib.sha256).hexdigest()
        return {"Host": host, "Content-Length": str(size), "X-Amz-Date": amz_date,
                "X-Amz-Content-Sha256": payload_hash, "X-Amz-Meta-Sha256": metadata,
                "Authorization": f"AWS4-HMAC-SHA256 Credential={self.config['accessKeyId']}/{scope}, "
                                 f"SignedHeaders={signed_headers}, Signature={signature}"}

    def request(self, method: str, object_key: str, digest: str, size: int,
                body: Any = None) -> tuple[int, dict[str, str]]:
        if not DIGEST.fullmatch(digest) or not 0 <= size <= MAX_OBJECT or \
                not re.fullmatch(r"[A-Za-z0-9._/-]{1,512}", object_key) or ".." in object_key.split("/"):
            raise ArchiveError("archive object metadata is invalid")
        headers = self.headers(method, object_key, digest, size)
        path = f"/{quote(self.config['bucket'], safe='')}/{quote(object_key, safe='/')}"
        connection = http.client.HTTPSConnection(self.config["host"], self.config["port"],
                                                  context=self.context, timeout=60)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            if response.getheader("Location"):
                raise ArchiveError("archive redirects are forbidden")
            response.read(4096)
            return response.status, {name.lower(): value for name, value in response.getheaders()}
        except (OSError, ssl.SSLError, http.client.HTTPException) as error:
            raise ArchiveError("archive request failed") from error
        finally:
            connection.close()

    def upload_verified(self, path: pathlib.Path, object_key: str, digest: str, size: int) -> None:
        if path.stat().st_size != size:
            raise ArchiveError("segment changed before upload")
        with path.open("rb") as source:
            status, _ = self.request("PUT", object_key, digest, size, source)
        if status not in {200, 201, 204}:
            raise ArchiveError("archive upload failed")
        status, headers = self.request("HEAD", object_key, digest, 0)
        if status != 200 or int(headers.get("content-length", "-1")) != size or \
                headers.get("x-amz-meta-sha256") != digest:
            raise ArchiveError("archive verification failed")

    def download_verified(self, object_key: str, destination: pathlib.Path,
                          digest: str, size: int) -> None:
        if not DIGEST.fullmatch(digest) or not 0 <= size <= MAX_OBJECT or \
                not re.fullmatch(r"[A-Za-z0-9._/-]{1,512}", object_key) or ".." in object_key.split("/"):
            raise ArchiveError("archive object metadata is invalid")
        empty_digest = hashlib.sha256(b"").hexdigest()
        headers = self.headers("GET", object_key, empty_digest, 0)
        path = f"/{quote(self.config['bucket'], safe='')}/{quote(object_key, safe='/')}"
        connection = http.client.HTTPSConnection(self.config["host"], self.config["port"],
                                                  context=self.context, timeout=60)
        temporary = destination.with_name(f".{destination.name}.archive-download")
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            if response.status != 200 or response.getheader("Location") or \
                    int(response.getheader("Content-Length", "-1")) != size or \
                    response.getheader("X-Amz-Meta-Sha256", "") != digest:
                raise ArchiveError("archive download metadata verification failed")
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            total = 0
            computed = hashlib.sha256()
            with temporary.open("xb") as output:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > size:
                        raise ArchiveError("archive download exceeded declared size")
                    computed.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if total != size or computed.hexdigest() != digest:
                raise ArchiveError("archive download digest verification failed")
            os.replace(temporary, destination)
        except (OSError, ssl.SSLError, http.client.HTTPException) as error:
            raise ArchiveError("archive download failed") from error
        finally:
            connection.close()
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()


class ArchiveQueue:
    def __init__(self, path: pathlib.Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.db:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript("""
              CREATE TABLE IF NOT EXISTS jobs(segment_id TEXT PRIMARY KEY,object_key TEXT NOT NULL,state TEXT NOT NULL,
                attempts INTEGER NOT NULL,next_attempt_at INTEGER NOT NULL,error_code TEXT NOT NULL,updated_at INTEGER NOT NULL);
              CREATE INDEX IF NOT EXISTS jobs_due ON jobs(state,next_attempt_at);
            """)
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)

    def enqueue(self, segment_id: str, object_key: str) -> bool:
        with self.lock, self.db:
            count = self.db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','retry','uploading')").fetchone()[0]
            if count >= MAX_QUEUE:
                return False
            self.db.execute("INSERT OR IGNORE INTO jobs VALUES(?,?, 'queued',0,0,'',?)",
                            (segment_id, object_key, int(time.time())))
            return True

    def claim(self) -> sqlite3.Row | None:
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM jobs WHERE state IN ('queued','retry') AND next_attempt_at<=? "
                                  "ORDER BY updated_at LIMIT 1", (int(time.time()),)).fetchone()
            if row:
                self.db.execute("UPDATE jobs SET state='uploading',updated_at=? WHERE segment_id=?",
                                (int(time.time()), row["segment_id"]))
            return row

    def complete(self, segment_id: str) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE jobs SET state='completed',error_code='',updated_at=? WHERE segment_id=?",
                            (int(time.time()), segment_id))

    def retry(self, segment_id: str, error_code: str) -> None:
        with self.lock, self.db:
            row = self.db.execute("SELECT attempts FROM jobs WHERE segment_id=?", (segment_id,)).fetchone()
            attempts = min(1000, (row[0] if row else 0) + 1)
            delay = min(300, max(5, 5 * (2 ** min(attempts - 1, 6))))
            self.db.execute("UPDATE jobs SET state='retry',attempts=?,next_attempt_at=?,error_code=?,updated_at=? WHERE segment_id=?",
                            (attempts, int(time.time()) + delay, error_code[:64], int(time.time()), segment_id))


class ArchiveService:
    def __init__(self, catalog_path: pathlib.Path, queue_path: pathlib.Path,
                 volumes_root: pathlib.Path, config: dict[str, Any], legacy_root: pathlib.Path | None = None):
        self.catalog = sqlite3.connect(catalog_path, check_same_thread=False, timeout=15)
        self.catalog.row_factory = sqlite3.Row
        self.queue = ArchiveQueue(queue_path)
        self.volumes_root = volumes_root
        self.legacy_root = legacy_root or volumes_root.parent
        self.client = S3Client(config, os.environ.get("WEBOBS_ARCHIVE_CA_FILE", ""))
        self.stop = threading.Event()

    def segment_path(self, row: sqlite3.Row) -> pathlib.Path:
        volume_id = row["volume_id"]
        if not VOLUME_ID.fullmatch(volume_id) or row["storage_key"].startswith("/") or \
                ".." in row["storage_key"].split("/"):
            raise ArchiveError("segment location is invalid")
        root = self.legacy_root if volume_id == "default" else self.volumes_root / volume_id
        candidate = (root / row["storage_key"]).resolve()
        if root.resolve() not in candidate.parents:
            raise ArchiveError("segment escaped its volume")
        return candidate

    def scan(self) -> None:
        rows = self.catalog.execute("SELECT id,sha256 FROM segments WHERE archive_state='local' "
                                    "AND length(sha256)=64 AND integrity NOT IN ('deleted','missing') LIMIT ?",
                                    (MAX_QUEUE,)).fetchall()
        for row in rows:
            self.queue.enqueue(row["id"], f"segments/{row['sha256'][:2]}/{row['sha256']}")

    def worker(self) -> None:
        while not self.stop.wait(1):
            job = self.queue.claim()
            if job is None:
                continue
            row = self.catalog.execute("SELECT * FROM segments WHERE id=?", (job["segment_id"],)).fetchone()
            try:
                if row is None or not DIGEST.fullmatch(row["sha256"]):
                    raise ArchiveError("catalog segment is unavailable")
                path = self.segment_path(row)
                self.client.upload_verified(path, job["object_key"], row["sha256"], row["size_bytes"])
                with self.catalog:
                    self.catalog.execute("UPDATE segments SET archive_state='uploaded' WHERE id=?", (row["id"],))
                self.queue.complete(row["id"])
            except (ArchiveError, OSError, sqlite3.Error) as error:
                self.queue.retry(job["segment_id"], type(error).__name__)

    def retrieve(self, segment_id: str, destination: pathlib.Path) -> pathlib.Path:
        """Restore one catalogued object without accepting an arbitrary object key."""
        if not re.fullmatch(r"[a-f0-9]{32}", segment_id) or not destination.is_absolute() or destination.is_symlink():
            raise ArchiveError("archive retrieval request is invalid")
        row = self.catalog.execute(
            "SELECT id,sha256,size_bytes,archive_state FROM segments WHERE id=? AND integrity NOT IN ('deleted','missing')",
            (segment_id,),
        ).fetchone()
        if row is None or row["archive_state"] != "uploaded" or not DIGEST.fullmatch(row["sha256"]):
            raise ArchiveError("archived segment is unavailable")
        object_key = f"segments/{row['sha256'][:2]}/{row['sha256']}"
        self.client.download_verified(object_key, destination, row["sha256"], row["size_bytes"])
        return destination

    def run(self) -> None:
        workers = [threading.Thread(target=self.worker, daemon=True) for _ in range(MAX_WORKERS)]
        for worker in workers:
            worker.start()
        while not self.stop.wait(10):
            self.scan()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.environ.get("WEBOBS_ARCHIVE_CONFIG", "/config/webobs/archive.json"))
    parser.add_argument("--catalog", default=os.environ.get("WEBOBS_NVR_CATALOG", "/recordings/nvr/catalog.sqlite3"))
    parser.add_argument("--queue", default=os.environ.get("WEBOBS_ARCHIVE_QUEUE", "/config/webobs/archive-queue.sqlite3"))
    parser.add_argument("--volumes-root", default=os.environ.get("WEBOBS_NVR_VOLUMES_ROOT", "/recordings/volumes"))
    parser.add_argument("--legacy-root", default=os.environ.get("WEBOBS_NVR_STORAGE_ROOT", "/recordings"))
    parser.add_argument("--retrieve-segment", default="")
    parser.add_argument("--destination", default="")
    args = parser.parse_args()
    paths = [pathlib.Path(item) for item in (args.config, args.catalog, args.queue, args.volumes_root,
                                             args.legacy_root)]
    if any(not path.is_absolute() for path in paths):
        raise SystemExit("archive paths must be absolute")
    service = ArchiveService(paths[1], paths[2], paths[3], load_config(paths[0]), paths[4])
    if args.retrieve_segment:
        if not args.destination:
            raise SystemExit("archive retrieval requires --destination")
        destination = pathlib.Path(args.destination)
        if not destination.is_absolute():
            raise SystemExit("archive retrieval destination must be absolute")
        service.retrieve(args.retrieve_segment, destination)
        return
    service.run()


if __name__ == "__main__":
    main()
