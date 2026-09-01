#!/usr/bin/env python3
"""WebOBS recorder/worker node agent.

The agent owns node keys locally, performs one-time enrollment, reports bounded
capacity/volume inventory, renews recording leases, and publishes an atomic
assignment snapshot consumed by the recorder. It never logs controller URLs,
tokens, certificates, storage paths, or camera identifiers.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import os
import pathlib
import re
import signal
import shutil
import ssl
import sqlite3
import subprocess
import tempfile
import time
from typing import Any
from urllib.parse import urlsplit


MAX_RESPONSE = 1024 * 1024
VOLUME_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
STOP = False


class AgentError(RuntimeError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def atomic_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = pathlib.Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(canonical_json(value) + b"\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def atomic_private_text(path: pathlib.Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = pathlib.Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


class ControllerClient:
    def __init__(self, authority: str, ca_file: pathlib.Path,
                 cert_file: pathlib.Path | None = None, key_file: pathlib.Path | None = None):
        parsed = urlsplit(authority)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or \
                parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise AgentError("controller must be an HTTPS authority")
        self.host = parsed.hostname
        self.port = parsed.port or 443
        self.context = ssl.create_default_context(cafile=str(ca_file))
        self.context.minimum_version = ssl.TLSVersion.TLSv1_3
        if cert_file and key_file:
            self.context.load_cert_chain(str(cert_file), str(key_file))

    def request(self, method: str, path: str, value: Any | None = None,
                node_id: str = "") -> tuple[int, Any]:
        if not path.startswith("/internal/v1/") or "\r" in path or "\n" in path:
            raise AgentError("internal request path is invalid")
        body = canonical_json(value) if value is not None else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))
        if node_id:
            headers["X-WebObs-Node-Id"] = node_id
        connection = http.client.HTTPSConnection(self.host, self.port, context=self.context, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            if response.getheader("Location"):
                raise AgentError("controller redirects are forbidden")
            payload = response.read(MAX_RESPONSE + 1)
            if len(payload) > MAX_RESPONSE:
                raise AgentError("controller response exceeded one MiB")
            parsed = json.loads(payload) if payload else {}
            return response.status, parsed
        except (OSError, ssl.SSLError, json.JSONDecodeError, http.client.HTTPException) as error:
            raise AgentError("controller request failed") from error
        finally:
            connection.close()


def generate_identity(key_file: pathlib.Path, csr_file: pathlib.Path, name: str) -> None:
    key_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if key_file.exists() != csr_file.exists():
        raise AgentError("partial node identity exists")
    if key_file.exists():
        return
    if not re.fullmatch(r"[A-Za-z0-9._ -]{1,64}", name):
        raise AgentError("node name is invalid")
    completed = subprocess.run([
        "openssl", "req", "-new", "-newkey", "ed25519", "-nodes", "-subj", f"/CN={name}",
        "-keyout", str(key_file), "-out", str(csr_file),
    ], capture_output=True, timeout=15, check=False)
    if completed.returncode != 0:
        raise AgentError("node identity generation failed")
    os.chmod(key_file, 0o600)
    os.chmod(csr_file, 0o600)


def complete_enrollment(controller: str, ca_file: pathlib.Path, state_dir: pathlib.Path,
                        enrollment_id: str, token: str, node_name: str) -> tuple[str, pathlib.Path, pathlib.Path]:
    key_file = state_dir / "node.key"
    csr_file = state_dir / "node.csr"
    cert_file = state_dir / "node.crt"
    identity_file = state_dir / "identity.json"
    if cert_file.is_file() and identity_file.is_file():
        identity = json.loads(identity_file.read_text(encoding="utf-8"))
        node_id = identity.get("nodeId", "")
        if re.fullmatch(r"[a-f0-9]{32}", node_id):
            return node_id, cert_file, key_file
        raise AgentError("stored node identity is invalid")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", enrollment_id) or len(token) < 32:
        raise AgentError("enrollment credentials are invalid")
    generate_identity(key_file, csr_file, node_name)
    client = ControllerClient(controller, ca_file)
    status, _ = client.request("POST", "/internal/v1/nodes/enroll", {
        "id": enrollment_id, "token": token, "csr": csr_file.read_text(encoding="ascii"),
    })
    if status not in {200, 409}:
        raise AgentError("node enrollment submission was rejected")
    while not STOP:
        status, response = client.request("POST", "/internal/v1/nodes/enroll/complete", {
            "id": enrollment_id, "token": token,
        })
        if status == 200:
            certificate = response.get("certificate", "")
            node_id = response.get("nodeId", "")
            if not isinstance(certificate, str) or "BEGIN CERTIFICATE" not in certificate or \
                    not isinstance(node_id, str) or not re.fullmatch(r"[a-f0-9]{32}", node_id):
                raise AgentError("controller returned an invalid node identity")
            cert_file.write_text(certificate, encoding="ascii")
            os.chmod(cert_file, 0o600)
            atomic_json(identity_file, {"nodeId": node_id,
                                        "certificateExpiresAt": response.get("certificateExpiresAt", 0)})
            return node_id, cert_file, key_file
        if status not in {403, 409}:
            raise AgentError("node enrollment completion failed")
        time.sleep(2)
    raise AgentError("node enrollment interrupted")


def memory_bytes() -> int:
    try:
        for line in pathlib.Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 64 * 1024 * 1024


def volume_inventory(root: pathlib.Path) -> list[dict[str, Any]]:
    if not root.is_dir() or root.is_symlink():
        return []
    result = []
    for child in sorted(root.iterdir()):
        if len(result) >= 256:
            break
        if not child.is_dir() or child.is_symlink() or not VOLUME_ID.fullmatch(child.name):
            continue
        usage = shutil.disk_usage(child)
        capacity = usage.total
        free = usage.free
        read_only = not os.access(child, os.W_OK)
        result.append({
            "id": child.name, "label": child.name, "tier": "hot",
            "state": "read-only" if read_only else "online",
            "capacityBytes": capacity, "freeBytes": free, "reserveBytes": 1 << 30,
            "highWatermark": 0.90, "lowWatermark": 0.80, "readOnly": read_only,
        })
    return result


def resource_report() -> dict[str, Any]:
    rated = os.environ.get("WEBOBS_NODE_RATED", "false") == "true"
    capabilities = {
        "vaapiDevicePresent": pathlib.Path("/dev/dri/renderD128").exists(),
        "runtimeProbePassed": os.environ.get("WEBOBS_HARDWARE_PROBE_PASSED", "false") == "true",
        "decodeSlots": int(os.environ.get("WEBOBS_DECODE_SLOTS", "0")),
        "encodeSlots": int(os.environ.get("WEBOBS_ENCODE_SLOTS", "0")),
        "diskBytesPerSecond": int(os.environ.get("WEBOBS_NODE_DISK_BYTES_PER_SECOND", "0")),
    }
    return {"cpuCores": max(1, os.cpu_count() or 1), "memoryBytes": memory_bytes(),
            "capabilities": capabilities, "reservations": [], "rated": rated}


def renew_certificate_if_needed(client: ControllerClient, node_id: str, state_dir: pathlib.Path,
                                identity: dict[str, Any]) -> bool:
    expires_at = identity.get("certificateExpiresAt", 0)
    if not isinstance(expires_at, int) or expires_at <= 0:
        raise AgentError("stored certificate expiry is invalid")
    if expires_at - int(time.time()) > 7 * 24 * 60 * 60:
        return False
    key_file = state_dir / "node.key"
    with tempfile.TemporaryDirectory(prefix="webobs-renew-") as directory:
        csr_file = pathlib.Path(directory) / "node.csr"
        completed = subprocess.run([
            "openssl", "req", "-new", "-key", str(key_file), "-subj", f"/CN={node_id}",
            "-out", str(csr_file),
        ], capture_output=True, timeout=15, check=False)
        if completed.returncode != 0:
            raise AgentError("node certificate renewal CSR failed")
        status, response = client.request("POST", "/internal/v1/nodes/certificate/renew", {
            "csr": csr_file.read_text(encoding="ascii"),
        }, node_id)
    certificate = response.get("certificate", "") if status == 200 else ""
    new_expiry = response.get("certificateExpiresAt", 0) if status == 200 else 0
    if not isinstance(certificate, str) or "BEGIN CERTIFICATE" not in certificate or \
            not isinstance(new_expiry, int) or new_expiry <= expires_at:
        raise AgentError("node certificate renewal was rejected")
    atomic_private_text(state_dir / "node.crt", certificate)
    atomic_json(state_dir / "identity.json", {"nodeId": node_id,
                                               "certificateExpiresAt": new_expiry})
    return True


def catalog_batch(catalog_path: pathlib.Path, assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Read a bounded, non-secret segment batch from the local recorder catalog."""
    if not catalog_path.is_file():
        return []
    allowed = {(item.get("cameraId"), item.get("profileId"), item.get("generation"))
               for item in assignments if isinstance(item, dict)}
    try:
        connection = sqlite3.connect(f"file:{catalog_path.as_posix()}?mode=ro", uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        columns = {row[1] for row in connection.execute("PRAGMA table_info(segments)")}
        required_columns = {"profile_id", "sha256", "volume_id", "assignment_generation", "archive_state",
                            "start_utc_ms", "end_utc_ms", "duration_ms", "kind", "video_codec",
                            "audio_codec", "locked"}
        if not required_columns.issubset(columns):
            return []
        rows = connection.execute("""
          SELECT id,camera_id,profile_id,volume_id,storage_key,size_bytes,sha256,
                 assignment_generation,archive_state,integrity,start_utc_ms,end_utc_ms,
                 duration_ms,kind,video_codec,audio_codec,locked
          FROM segments
          WHERE integrity NOT IN ('deleted','missing') AND length(sha256)=64
          ORDER BY created_utc_ms DESC LIMIT 256
        """).fetchall()
    except sqlite3.Error as error:
        raise AgentError("local recorder catalog could not be read") from error
    finally:
        with contextlib.suppress(UnboundLocalError):
            connection.close()
    result = []
    for row in rows:
        identity = (row["camera_id"], row["profile_id"], row["assignment_generation"])
        if identity not in allowed or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            continue
        result.append({
            "segmentId": row["id"], "cameraId": row["camera_id"], "profileId": row["profile_id"],
            "volumeId": row["volume_id"], "storageKey": row["storage_key"],
            "sizeBytes": row["size_bytes"], "sha256": row["sha256"],
            "generation": row["assignment_generation"], "archiveState": row["archive_state"],
            "integrity": row["integrity"], "startUtcMs": row["start_utc_ms"],
            "endUtcMs": row["end_utc_ms"], "durationMs": row["duration_ms"],
            "kind": row["kind"], "videoCodec": row["video_codec"],
            "audioCodec": row["audio_codec"], "locked": bool(row["locked"]),
        })
    return result


def run(args: argparse.Namespace) -> None:
    state_dir = pathlib.Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    identity_file = state_dir / "identity.json"
    cert_file = state_dir / "node.crt"
    key_file = state_dir / "node.key"
    if identity_file.is_file() and cert_file.is_file() and key_file.is_file():
        node_id = json.loads(identity_file.read_text(encoding="utf-8"))["nodeId"]
    else:
        node_id, cert_file, key_file = complete_enrollment(
            args.controller, pathlib.Path(args.ca_file), state_dir,
            args.enrollment_id, args.enrollment_token, args.node_name)
    identity = json.loads(identity_file.read_text(encoding="utf-8"))
    client = ControllerClient(args.controller, pathlib.Path(args.ca_file), cert_file, key_file)
    assignments_path = state_dir / "assignments.json"
    next_renew: dict[tuple[str, str], float] = {}
    failure_started = 0.0
    while not STOP:
        started = time.monotonic()
        try:
            if renew_certificate_if_needed(client, node_id, state_dir, identity):
                identity = json.loads(identity_file.read_text(encoding="utf-8"))
                client = ControllerClient(args.controller, pathlib.Path(args.ca_file), cert_file, key_file)
            status, heartbeat = client.request("POST", "/internal/v1/nodes/heartbeat", {
                "version": args.version, "nodeTime": int(time.time()),
                "capabilities": resource_report()["capabilities"],
                "volumes": volume_inventory(pathlib.Path(args.volumes_root)),
                "resources": resource_report(),
            }, node_id)
            if status != 200 or heartbeat.get("status") == "clock-skew":
                raise AgentError("heartbeat was rejected")
            status, payload = client.request("GET", "/internal/v1/assignments", node_id=node_id)
            if status != 200 or not isinstance(payload.get("assignments"), list) or \
                    not isinstance(payload.get("volumes", []), list):
                raise AgentError("assignment synchronization failed")
            now = int(time.time())
            accepted = []
            for assignment in payload["assignments"][:256]:
                required = {"cameraId", "profileId", "nodeId", "generation", "state",
                            "leaseExpiresAt", "isolationDeadline"}
                if not isinstance(assignment, dict) or not required.issubset(assignment):
                    raise AgentError("controller returned an invalid assignment")
                key = (assignment["cameraId"], assignment["profileId"])
                if assignment["state"] == "active" and next_renew.get(key, 0) <= time.monotonic():
                    renew_status, lease = client.request("POST", "/internal/v1/leases/renew", {
                        "cameraId": key[0], "profileId": key[1], "generation": assignment["generation"],
                    }, node_id)
                    if renew_status != 200:
                        raise AgentError("lease renewal was rejected")
                    assignment["leaseExpiresAt"] = lease["leaseExpiresAt"]
                    assignment["isolationDeadline"] = lease["isolationDeadline"]
                    next_renew[key] = time.monotonic() + 10
                if assignment["state"] == "active" and assignment["isolationDeadline"] > now:
                    accepted.append(assignment)
            atomic_json(assignments_path, {"nodeId": node_id, "controllerOnline": True,
                                           "updatedAt": now, "assignments": accepted,
                                           "volumes": payload.get("volumes", [])[:256]})
            segments = catalog_batch(pathlib.Path(args.catalog), accepted)
            if segments:
                catalog_status, _ = client.request("POST", "/internal/v1/catalog/batch",
                                                   {"segments": segments}, node_id)
                if catalog_status != 200:
                    raise AgentError("catalog synchronization was rejected")
            failure_started = 0.0
        except AgentError:
            if not failure_started:
                failure_started = time.monotonic()
            if time.monotonic() - failure_started >= 120:
                atomic_json(assignments_path, {"nodeId": node_id, "controllerOnline": False,
                                               "updatedAt": int(time.time()), "assignments": []})
        elapsed = time.monotonic() - started
        time.sleep(max(0.1, 5 - elapsed))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--controller", default=os.environ.get("WEBOBS_CONTROLLER_URL", ""))
    parser.add_argument("--ca-file", default=os.environ.get("WEBOBS_CLUSTER_CA_FILE", ""))
    parser.add_argument("--state-dir", default=os.environ.get("WEBOBS_NODE_STATE_DIR", "/config/webobs/node"))
    parser.add_argument("--volumes-root", default=os.environ.get("WEBOBS_VOLUMES_ROOT", "/recordings/volumes"))
    parser.add_argument("--catalog", default=os.environ.get(
        "WEBOBS_NVR_CATALOG", "/recordings/catalog.sqlite3"))
    parser.add_argument("--enrollment-id", default=os.environ.get("WEBOBS_NODE_ENROLLMENT_ID", ""))
    parser.add_argument("--enrollment-token", default=os.environ.get("WEBOBS_NODE_ENROLLMENT_TOKEN", ""))
    parser.add_argument("--node-name", default=os.environ.get("WEBOBS_NODE_NAME", "webobs-recorder"))
    parser.add_argument("--version", default=os.environ.get("WEBOBS_BUILD_VERSION", "2.3.0-dev"))
    args = parser.parse_args()
    if not args.controller or not pathlib.Path(args.ca_file).is_file():
        raise SystemExit("controller HTTPS authority and CA file are required")
    global STOP
    signal.signal(signal.SIGTERM, lambda *_: globals().__setitem__("STOP", True))
    signal.signal(signal.SIGINT, lambda *_: globals().__setitem__("STOP", True))
    run(args)


if __name__ == "__main__":
    main()
