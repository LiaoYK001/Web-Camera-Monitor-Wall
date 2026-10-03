"""Private, durable evidence jobs. No URLs, credentials or process output in jobs."""
from __future__ import annotations

import contextlib
import errno
from fractions import Fraction
import json
import os
import pathlib
import re
import shutil
import subprocess
import threading
import time
import uuid


class EvidenceError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.status = code, status


def now_ms():
    return time.time_ns() // 1_000_000


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise EvidenceError("export_cancelled", "Export cancelled")


def run_export(command, cancel):
    check_cancel(cancel)
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 300
        while process.poll() is None:
            check_cancel(cancel)
            if time.monotonic() >= deadline:
                raise EvidenceError("export_timeout", "Export exceeded its time limit", 504)
            if cancel is not None:
                cancel.wait(0.1)
            else:
                time.sleep(0.1)
        if process.returncode:
            raise EvidenceError("export_conversion_failed", "Media conversion failed; check source integrity", 422)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def coverage(rows, start, end):
    intervals, gaps, cursor, overlap = [], [], start, False
    previous_end = None
    for row in rows:
        left, right = max(start, row["start_utc_ms"]), min(end, row["end_utc_ms"])
        if right <= left:
            continue
        if previous_end is not None and left < previous_end:
            overlap = True
        if left > cursor:
            gaps.append({"fromUtcMs": cursor, "toUtcMs": left})
        intervals.append({"fromUtcMs": left, "toUtcMs": right})
        cursor, previous_end = max(cursor, right), max(previous_end or right, right)
    if cursor < end:
        gaps.append({"fromUtcMs": cursor, "toUtcMs": end})
    return {"intervals": intervals, "gaps": gaps, "overlap": overlap}


def remove_unpublished(root: pathlib.Path, export_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", export_id):
        raise ValueError("Invalid private export directory")
    root = root.resolve()
    target = root / export_id
    if target.is_symlink() or target.resolve().parent != root:
        raise ValueError("Unsafe private export directory")
    if target.is_dir():
        shutil.rmtree(target)


class ExportJobs:
    """One worker, eight outstanding jobs, idempotent per authenticated owner."""
    ACTIVE = ("queued", "running", "cancelling")

    def __init__(self, service):
        self.service, self.catalog = service, service.catalog
        self.lock = threading.RLock()
        self.wake, self.stop = threading.Event(), threading.Event()
        self.thread = None
        self.accepting = True
        self.cancel_events = {}
        self.catalog.execute("""CREATE TABLE IF NOT EXISTS export_jobs (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_id TEXT NOT NULL,
            request_json TEXT NOT NULL, state TEXT NOT NULL, created_ms INTEGER NOT NULL,
            updated_ms INTEGER NOT NULL, result_json TEXT, error_code TEXT, error_message TEXT,
            UNIQUE(owner,request_id))""")
        # A committed result and its evidence locks share the same transaction.
        pending = self.catalog.query("SELECT id FROM export_jobs WHERE state IN ('queued','running','cancelling')")
        for row in pending:
            if not self.catalog.query("SELECT id FROM exports WHERE id=?", (row["id"],)):
                remove_unpublished(service.exports_root, row["id"])
        self.catalog.execute("UPDATE export_jobs SET state='interrupted',updated_ms=?,"
                             "error_code='export_interrupted',error_message='Service restarted; submit a new export' "
                             "WHERE state IN ('queued','running','cancelling')", (now_ms(),))

    def start(self):
        with self.lock:
            if self.thread is None:
                self.thread = threading.Thread(target=self._worker, name="nvr-evidence", daemon=True)
                self.thread.start()

    def outstanding(self):
        return self.catalog.query("SELECT COUNT(*) AS count FROM export_jobs WHERE state IN ('queued','running','cancelling')")[0]["count"]

    def drain(self, timeout=20):
        with self.lock:
            self.accepting = False
        deadline = time.monotonic() + timeout
        while self.outstanding() and time.monotonic() < deadline:
            self.wake.set()
            time.sleep(0.1)
        if self.outstanding():
            self.accepting = True
            raise RuntimeError("active evidence jobs did not finish before shutdown")
        self.stop.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join(timeout=2)

    @staticmethod
    def public(row):
        return {"id": row["id"], "requestId": row["request_id"], "state": row["state"],
                "createdUtcMs": row["created_ms"], "updatedUtcMs": row["updated_ms"],
                "request": json.loads(row["request_json"]),
                "result": json.loads(row["result_json"]) if row["result_json"] else None,
                "error": {"code": row["error_code"], "message": row["error_message"]} if row["error_code"] else None}

    def get(self, owner, job_id):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise KeyError(job_id)
        rows = self.catalog.query("SELECT * FROM export_jobs WHERE id=? AND owner=?", (job_id, owner))
        if not rows:
            raise KeyError(job_id)
        job = self.public(rows[0])
        self.service.authorize_export(owner, job["request"])
        return job

    def list(self, owner):
        rows = self.catalog.query("SELECT * FROM export_jobs WHERE owner=? ORDER BY created_ms DESC LIMIT 50", (owner,))
        jobs = []
        checked, deadline = set(), time.monotonic() + 10
        for row in rows:
            try:
                self.service.authorize_export(owner, json.loads(row["request_json"]), checked=checked, deadline=deadline)
            except EvidenceError as error:
                if error.status == 403:
                    continue
                raise
            jobs.append(self.public(row))
        return {"jobs": jobs}

    def submit(self, owner, value):
        if not isinstance(value, dict):
            raise EvidenceError("invalid_export", "Export request must be an object", 422)
        request_id = value.get("requestId")
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9-]{32,36}", request_id):
            raise EvidenceError("invalid_request_id", "A stable requestId is required", 422)
        request = self.service.validate_export({key: item for key, item in value.items() if key != "requestId"})
        self.service.authorize_export(owner, request)
        encoded = json.dumps(request, separators=(",", ":"), sort_keys=True)
        with self.lock:
            existing = self.catalog.query("SELECT * FROM export_jobs WHERE owner=? AND request_id=?", (owner, request_id))
            if existing:
                if existing[0]["request_json"] != encoded:
                    raise EvidenceError("export_request_conflict", "requestId already belongs to another range")
                return self.public(existing[0])
            if not self.accepting or self.outstanding() >= 8:
                raise EvidenceError("export_queue_full", "Export queue is full or stopping; try later", 503)
            job_id, stamp = uuid.uuid4().hex, now_ms()
            self.catalog.execute("INSERT INTO export_jobs(id,owner,request_id,request_json,state,created_ms,updated_ms) "
                                 "VALUES(?,?,?,?,'queued',?,?)", (job_id, owner, request_id, encoded, stamp, stamp))
            self.wake.set()
        return self.get(owner, job_id)

    def cancel(self, owner, job_id):
        with self.lock:
            job = self.get(owner, job_id)
            if job["state"] in self.ACTIVE:
                event = self.cancel_events.get(job_id)
                if event is not None:
                    event.set()
                state = "cancelled" if job["state"] == "queued" else "cancelling"
                self.catalog.execute("UPDATE export_jobs SET state=?,updated_ms=? WHERE id=?", (state, now_ms(), job_id))
                self.wake.set()
        return self.get(owner, job_id)

    def complete(self, connection, job_id, result):
        # Called inside the evidence publication transaction; cancellation and
        # completion are serialized by self.lock held across that transaction.
        compact = {key: result[key] for key in ("exportId", "auditId", "mode", "requestedRange", "effectiveRange",
                   "manifestSha256", "manifestUrl", "createdUtcMs", "storageTimeZone")}
        compact["files"] = []
        for file in result["files"]:
            item = dict(file)
            info = file["coverage"]
            item["coverage"] = {"intervals": info["intervals"][:10], "gaps": info["gaps"][:10],
                                "gapCount": len(info["gaps"]), "overlap": info["overlap"],
                                "detailsInManifest": len(info["gaps"]) > 10 or len(info["intervals"]) > 10}
            compact["files"].append(item)
        connection.execute("UPDATE export_jobs SET state='completed',result_json=?,updated_ms=? WHERE id=?",
                           (json.dumps(compact, separators=(",", ":"), sort_keys=True), now_ms(), job_id))

    def _worker(self):
        while not self.stop.is_set():
            self.wake.clear()
            with self.lock:
                rows = self.catalog.query("SELECT * FROM export_jobs WHERE state='queued' ORDER BY created_ms LIMIT 1")
                if rows:
                    row = rows[0]
                    cancel = threading.Event()
                    self.cancel_events[row["id"]] = cancel
                    self.catalog.execute("UPDATE export_jobs SET state='running',updated_ms=? WHERE id=?", (now_ms(), row["id"]))
            if not rows:
                self.wake.wait(1)
                continue
            try:
                request = json.loads(row["request_json"])
                self.service.authorize_export(row["owner"], request)
                self.service.export_clip(request, job_id=row["id"], cancel=cancel, owner=row["owner"])
            except Exception as error:
                if isinstance(error, EvidenceError):
                    code, message = error.code, str(error)
                elif isinstance(error, OSError) and error.errno == errno.ENOSPC:
                    code, message = "export_disk_full", "Insufficient export storage; free space and retry"
                else:
                    code, message = "export_failed", "Export failed; check source availability and storage"
                state = "cancelled" if cancel.is_set() else "failed"
                self.catalog.execute("UPDATE export_jobs SET state=?,error_code=?,error_message=?,updated_ms=? WHERE id=? "
                                     "AND state!='completed'", (state, code, message, now_ms(), row["id"]))
            finally:
                with self.lock:
                    self.cancel_events.pop(row["id"], None)


def export_evidence(service, value, *, job_id=None, cancel=None, owner="local-only"):
    request = service.validate_export(value)
    camera_ids, start, end, mode = (request[key] for key in ("cameraIds", "fromUtcMs", "toUtcMs", "mode"))
    export_id, audit_id = job_id or uuid.uuid4().hex, uuid.uuid4().hex
    target_dir = service.exports_root / export_id
    files, source_ids, source_manifest, effective_start, effective_end = [], [], [], end, start
    published = False
    try:
        with contextlib.ExitStack() as pins:
            # Resolve and pin all source rows before starting conversion. Retention
            # cannot remove later cameras while an earlier camera is being encoded.
            with service.reader_lock:
                sources = {}
                for camera in camera_ids:
                    rows = service.catalog.query("SELECT * FROM segments WHERE camera_id=? AND end_utc_ms>? AND start_utc_ms<? "
                                                 "AND integrity NOT IN ('deleted','missing','corrupt') ORDER BY start_utc_ms,id LIMIT 5001",
                                                 (camera, start, end))
                    if not rows:
                        raise EvidenceError("export_range_incomplete", "No playable recording in the selected range", 422)
                    if len(rows) > 5000:
                        raise EvidenceError("export_range_too_large", "Too many segments; reduce the export range", 422)
                    info = coverage(rows, start, end)
                    if mode == "exact" and (info["gaps"] or info["overlap"]):
                        raise EvidenceError("export_range_incomplete", "Exact export requires continuous, non-overlapping recordings on every camera", 422)
                    pins.enter_context(service.pin_segments([row["id"] for row in rows]))
                    sources[camera] = (rows, info)
                    source_ids.extend(row["id"] for row in rows)
            required = sum(row["size_bytes"] for rows, _ in sources.values() for row in rows)
            reserve = service.config["minFreeBytes"]
            # Fast copy has predictable size; exact conversion still checks a
            # conservative input-size estimate and preserves the configured reserve.
            if shutil.disk_usage(service.exports_root).free < reserve + required * (2 if mode == "exact" else 1) + (16 << 20):
                raise EvidenceError("export_disk_full", "Insufficient export storage; free space and retry", 507)
            check_cancel(cancel)
            target_dir.mkdir(mode=0o700)
            for camera, (rows, info) in sources.items():
                check_cancel(cancel)
                concat = target_dir / f".{camera}.concat.txt"
                with concat.open("w", encoding="utf-8") as output:
                    for row in rows:
                        check_cancel(cancel)
                        path = service.media_path(row["id"])
                        digest = service._sha256(path, cancel=cancel)
                        if path.stat().st_size != row["size_bytes"] or (row["sha256"] and row["sha256"] != digest):
                            raise EvidenceError("export_source_changed", "Source recording no longer matches its catalog digest", 422)
                        source_manifest.append({"id": row["id"], "cameraId": camera,
                            "fromUtcMs": row["start_utc_ms"], "toUtcMs": row["end_utc_ms"],
                            "sha256": digest, "sizeBytes": row["size_bytes"]})
                        escaped = path.as_posix().replace("'", "'\\''")
                        output.write(f"file '{escaped}'\n")
                target = target_dir / f"{camera}.mp4"
                command = [service.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "concat",
                           "-safe", "0", "-i", str(concat)]
                if mode == "fast":
                    command += ["-map", "0:v:0", "-map", "0:a?", "-c", "copy"]
                    left, right = rows[0]["start_utc_ms"], max(row["end_utc_ms"] for row in rows)
                else:
                    command += ["-ss", f"{(start - rows[0]['start_utc_ms']) / 1000:.3f}", "-t", f"{(end-start) / 1000:.3f}",
                                "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast",
                                "-profile:v", "high", "-pix_fmt", "yuv420p", "-c:a", "aac"]
                    left, right = start, end
                run_export(command + ["-movflags", "+faststart", "-y", str(target)], cancel)
                concat.unlink()
                if target.stat().st_size > 64 * 1024 * 1024:
                    raise EvidenceError("export_file_too_large", "File exceeds the current 64 MiB product download limit; shorten the range", 422)
                media = service._probe(str(target))
                tracks = [{"type": item.get("codec_type", ""), "codec": item.get("codec_name", "")} for item in media.get("streams", [])]
                duration = float(media.get("format", {}).get("duration", 0))
                if not any(track["type"] == "video" for track in tracks) or duration <= 0:
                    raise EvidenceError("export_invalid_media", "Export contains no valid video", 422)
                video = next(item for item in media["streams"] if item.get("codec_type") == "video")
                try:
                    frame_ms = float(1000 / Fraction(video.get("avg_frame_rate", "25/1")))
                except (ValueError, ZeroDivisionError):
                    frame_ms = 40
                video_duration = float(video.get("duration", duration))
                if mode == "exact" and abs(video_duration * 1000 - (end-start)) > frame_ms + 2:
                    raise EvidenceError("export_duration_mismatch", "Recording duration does not match the requested range", 422)
                files.append({"cameraId": camera, "name": target.name, "sizeBytes": target.stat().st_size,
                              "sha256": service._sha256(target, cancel=cancel), "tracks": tracks, "durationMs": round(duration * 1000),
                              "coverage": info, "effectiveRange": {"fromUtcMs": left, "toUtcMs": right},
                              "downloadUrl": f"/api/v1/nvr/downloads/{export_id}/{target.name}"})
                effective_start, effective_end = min(effective_start, left), max(effective_end, right)
            manifest = {"schemaVersion": 2, "exportId": export_id, "auditId": audit_id, "mode": mode,
                        "softwareVersion": os.environ.get("WEBOBS_BUILD_VERSION", "unknown"),
                        "requestedRange": {"fromUtcMs": start, "toUtcMs": end},
                        "effectiveRange": {"fromUtcMs": effective_start, "toUtcMs": effective_end},
                        "cameraIds": camera_ids, "sourceSegmentIds": source_ids, "sourceSegments": source_manifest, "files": files,
                        "programRecordingId": request.get("programRecordingId"), "createdUtcMs": now_ms(), "storageTimeZone": "UTC"}
            # Import lazily to keep this module independent of executable layout.
            service.write_evidence_manifest(target_dir / "manifest.json", manifest)
            result = {**manifest, "manifestSha256": service._sha256(target_dir / "manifest.json"),
                      "manifestUrl": f"/api/v1/nvr/downloads/{export_id}/manifest.json"}
            with service.jobs.lock, service.reader_lock, service.catalog.lock, service.catalog.connection as connection:
                check_cancel(cancel)
                if request["lock"]:
                    connection.executemany("UPDATE segments SET locked=1 WHERE id=?", [(item,) for item in source_ids])
                connection.execute("INSERT INTO exports(id,audit_id,created_utc_ms,storage_key,manifest_key,mode,owner,request_json) VALUES(?,?,?,?,?,?,?,?)",
                                   (export_id, audit_id, now_ms(), f"exports/{export_id}", f"exports/{export_id}/manifest.json", mode,
                                    owner, json.dumps(request, separators=(",", ":"), sort_keys=True)))
                if job_id:
                    service.jobs.complete(connection, job_id, result)
            published = True
            service.audit("nvr.export.created", export_id=export_id, audit_id=audit_id, camera_count=len(camera_ids), mode=mode)
            return result
    finally:
        if not published:
            remove_unpublished(service.exports_root, export_id)
