#!/usr/bin/env python3
"""Bounded event, motion, rule and notification service for WebOBS.

The listener is loopback-only. It never owns recording processes, so analytics
and notification failures cannot stop the NVR data plane.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import socket
import sqlite3
import ssl
import struct
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

DB_PATH = Path(os.environ.get("WEBOBS_EVENT_DATABASE", "/config/webobs/events.db"))
NVR_DB_PATH = Path(os.environ.get("WEBOBS_NVR_DATABASE", "/config/webobs/nvr.db"))
SECRET_ROOT = Path(os.environ.get("WEBOBS_NOTIFICATION_SECRET_ROOT", "/run/secrets/webobs-notifications"))
LISTEN = ("127.0.0.1", 8093)
MAX_BODY = 1024 * 1024
MAX_EVENTS = 100_000
MAX_OUTBOX = 4096
ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
EVENT_TYPES = {"motion", "scene-change", "tamper", "line-crossing", "region-crossing", "object", "sound", "input", "device-health", "recording-failure", "manual-marker", "rule-result"}
EVENT_SOURCES = {"onvif", "software-motion", "detector-v1", "system", "manual", "rule"}
MOTION_STATE_LOCK = threading.Lock()
MOTION_STATE: dict[tuple[str, str], dict[str, int | bool]] = {}
NVR_TIMER_LOCK = threading.Lock()
NVR_TIMERS: dict[str, threading.Timer] = {}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try: return super().__exit__(exc_type, exc_value, traceback)
        finally: self.close()


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=3, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with connect() as database:
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA synchronous=NORMAL")
        database.executescript("""
        CREATE TABLE IF NOT EXISTS events(
          id TEXT PRIMARY KEY,camera_id TEXT NOT NULL,type TEXT NOT NULL,source TEXT NOT NULL,
          topic TEXT NOT NULL,occurred_at INTEGER NOT NULL,severity TEXT NOT NULL,confidence REAL,
          zone_id TEXT,label TEXT,acknowledged INTEGER NOT NULL DEFAULT 0,note TEXT NOT NULL DEFAULT '',
          properties_json TEXT NOT NULL,segment_ids_json TEXT NOT NULL,dedupe_key TEXT NOT NULL UNIQUE,
          created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS events_search ON events(occurred_at DESC,camera_id,type);
        CREATE TABLE IF NOT EXISTS motion_zones(
          id TEXT PRIMARY KEY,camera_id TEXT NOT NULL,name TEXT NOT NULL,mode TEXT NOT NULL,
          polygon_json TEXT NOT NULL,sensitivity REAL NOT NULL,debounce_ms INTEGER NOT NULL,
          cooldown_ms INTEGER NOT NULL,schedule_json TEXT NOT NULL,enabled INTEGER NOT NULL,updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS detector_providers(
          id TEXT PRIMARY KEY,name TEXT NOT NULL,api_version INTEGER NOT NULL,kind TEXT NOT NULL,
          enabled INTEGER NOT NULL,resource_limit INTEGER NOT NULL,health TEXT NOT NULL,updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS event_rules(
          id TEXT PRIMARY KEY,name TEXT NOT NULL,enabled INTEGER NOT NULL,conditions_json TEXT NOT NULL,
          actions_json TEXT NOT NULL,cooldown_ms INTEGER NOT NULL,last_triggered_at INTEGER NOT NULL,updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notification_outbox(
          id TEXT PRIMARY KEY,event_id TEXT NOT NULL,kind TEXT NOT NULL,destination_ref TEXT NOT NULL,
          payload_json TEXT NOT NULL,state TEXT NOT NULL,attempts INTEGER NOT NULL,next_attempt_at INTEGER NOT NULL,
          expires_at INTEGER NOT NULL,dedupe_key TEXT NOT NULL UNIQUE,last_error TEXT NOT NULL,created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS outbox_due ON notification_outbox(state,next_attempt_at);
        CREATE TABLE IF NOT EXISTS event_audit(
          id INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT NOT NULL,operation TEXT NOT NULL,
          actor TEXT NOT NULL,created_at INTEGER NOT NULL
        );
        """)


def now_ms() -> int: return time.time_ns() // 1_000_000


def bounded_text(value: object, name: str, maximum: int, empty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value) or (not empty and not value):
        raise ValueError(f"{name} is invalid")
    return value


def json_object(value: object, name: str, maximum_keys: int = 64) -> dict:
    if not isinstance(value, dict) or len(value) > maximum_keys:
        raise ValueError(f"{name} must be a bounded object")
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True)
    if len(encoded) > 32_768: raise ValueError(f"{name} is too large")
    return value


def segment_links(camera_id: str, occurred_at: int) -> list[str]:
    if not NVR_DB_PATH.is_file(): return []
    try:
        uri = f"file:{NVR_DB_PATH.as_posix()}?mode=ro"
        database = sqlite3.connect(uri, uri=True, timeout=.2)
        try:
            columns = {row[1] for row in database.execute("PRAGMA table_info(segments)")}
            required = {"id", "camera_id", "start_utc_ms", "end_utc_ms"}
            if not required.issubset(columns): return []
            return [row[0] for row in database.execute(
                "SELECT id FROM segments WHERE camera_id=? AND start_utc_ms<=? AND end_utc_ms>=? LIMIT 16",
                (camera_id, occurred_at, occurred_at)).fetchall()]
        finally: database.close()
    except (OSError, sqlite3.Error): return []


def validate_event(raw: object) -> dict:
    if not isinstance(raw, dict): raise ValueError("event must be an object")
    camera_id = bounded_text(raw.get("cameraId", ""), "cameraId", 64, False)
    if not ID_RE.fullmatch(camera_id): raise ValueError("cameraId is invalid")
    event_type, source = raw.get("type"), raw.get("source")
    if event_type not in EVENT_TYPES or source not in EVENT_SOURCES: raise ValueError("event type or source is unsupported")
    occurred_at = raw.get("occurredAt", now_ms())
    if isinstance(occurred_at, bool) or not isinstance(occurred_at, int) or abs(now_ms() - occurred_at) > 366 * 86400_000:
        raise ValueError("occurredAt is invalid")
    confidence = raw.get("confidence")
    if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
        raise ValueError("confidence must be between zero and one")
    properties = json_object(raw.get("properties", {}), "properties")
    result = {"cameraId": camera_id, "type": event_type, "source": source,
              "topic": bounded_text(raw.get("topic", ""), "topic", 256), "occurredAt": occurred_at,
              "severity": raw.get("severity", "info"), "confidence": confidence,
              "zoneId": bounded_text(raw.get("zoneId", ""), "zoneId", 64),
              "label": bounded_text(raw.get("label", ""), "label", 128), "properties": properties}
    if result["severity"] not in {"info", "warning", "critical"}: raise ValueError("severity is invalid")
    return result


def row_event(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "cameraId": row["camera_id"], "type": row["type"], "source": row["source"],
            "topic": row["topic"], "occurredAt": row["occurred_at"], "severity": row["severity"],
            "confidence": row["confidence"], "zoneId": row["zone_id"], "label": row["label"],
            "acknowledged": bool(row["acknowledged"]), "note": row["note"],
            "properties": json.loads(row["properties_json"]), "segmentIds": json.loads(row["segment_ids_json"])}


def schedule_active(schedule: object, timestamp: int) -> bool:
    if not schedule: return True
    if not isinstance(schedule, list) or len(schedule) > 32: return False
    current = time.gmtime(timestamp / 1000); minute = current.tm_hour * 60 + current.tm_min
    for window in schedule:
        try:
            start_hour, start_minute = map(int, window["start"].split(":")); end_hour, end_minute = map(int, window["end"].split(":"))
            start, end = start_hour * 60 + start_minute, end_hour * 60 + end_minute
            if current.tm_wday in window["days"] and (start <= minute < end if start <= end else minute >= start or minute < end): return True
        except (KeyError, TypeError, ValueError): return False
    return False


def matches_rule(event: dict, conditions: dict) -> bool:
    duration = event.get("properties", {}).get("durationMs", 0)
    return schedule_active(conditions.get("schedule", []), event["occurredAt"]) and all(not expected or event.get(field) == expected for field, expected in (
        ("cameraId", conditions.get("cameraId")), ("type", conditions.get("type")),
        ("zoneId", conditions.get("zoneId")), ("label", conditions.get("label")))) and (
        event.get("confidence") is None or event["confidence"] >= float(conditions.get("minimumConfidence", 0))) and (
        isinstance(duration, (int, float)) and duration >= float(conditions.get("minimumDurationMs", 0)))


def post_nvr_state(camera_id: str, active: bool) -> None:
    try:
        data = json.dumps({"active": active}, separators=(",", ":")).encode()
        request = urllib.request.Request(f"http://127.0.0.1:8091/events/{camera_id}", data,
                                         {"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=.5) as response: response.read(1024)
    except Exception:
        return


def stop_nvr_event(camera_id: str) -> None:
    post_nvr_state(camera_id, False)
    with NVR_TIMER_LOCK: NVR_TIMERS.pop(camera_id, None)


def trigger_nvr_event(camera_id: str, post_seconds: int = 10) -> None:
    threading.Thread(target=post_nvr_state, args=(camera_id, True), daemon=True).start()
    timer = threading.Timer(post_seconds, stop_nvr_event, args=(camera_id,)); timer.daemon = True
    with NVR_TIMER_LOCK:
        previous = NVR_TIMERS.pop(camera_id, None)
        if previous: previous.cancel()
        NVR_TIMERS[camera_id] = timer
    timer.start()


def apply_rules(database: sqlite3.Connection, event: dict) -> None:
    current = now_ms()
    for rule in database.execute("SELECT * FROM event_rules WHERE enabled=1").fetchall():
        conditions, actions = json.loads(rule["conditions_json"]), json.loads(rule["actions_json"])
        if current - rule["last_triggered_at"] < rule["cooldown_ms"] or not matches_rule(event, conditions): continue
        database.execute("UPDATE event_rules SET last_triggered_at=? WHERE id=?", (current, rule["id"]))
        for action in actions[:8]:
            if not isinstance(action, dict) or action.get("kind") not in {"webhook", "mqtt"}: continue
            destination = action.get("destinationRef", "")
            if not isinstance(destination, str) or not ID_RE.fullmatch(destination): continue
            dedupe = hashlib.sha256(f'{event["id"]}\0{rule["id"]}\0{action["kind"]}\0{destination}'.encode()).hexdigest()
            database.execute("INSERT OR IGNORE INTO notification_outbox VALUES(?,?,?,?,?,'pending',0,?,?,?,'',?)",
                (uuid.uuid4().hex, event["id"], action["kind"], destination,
                 json.dumps({"schemaVersion": 1, "event": event, "ruleId": rule["id"]}, separators=(",", ":")),
                 current, current + 86400_000, dedupe, current))
    database.execute("DELETE FROM notification_outbox WHERE id NOT IN (SELECT id FROM notification_outbox ORDER BY created_at DESC LIMIT ?)", (MAX_OUTBOX,))


def ingest_event(raw: object) -> dict:
    event = validate_event(raw)
    bucket = event["occurredAt"] // 1000
    supplied = raw.get("dedupeKey", "") if isinstance(raw, dict) else ""
    material = supplied or json.dumps([event["cameraId"], event["type"], event["source"], event["topic"], event["zoneId"], event["label"], bucket], separators=(",", ":"))
    dedupe = hashlib.sha256(material.encode()).hexdigest()
    event_id, created = uuid.uuid4().hex, now_ms()
    segments = segment_links(event["cameraId"], event["occurredAt"])
    with connect() as database:
        database.execute("BEGIN IMMEDIATE")
        existing = database.execute("SELECT * FROM events WHERE dedupe_key=?", (dedupe,)).fetchone()
        if existing: return row_event(existing) | {"deduplicated": True}
        database.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,0,'',?,?,?,?)", (
            event_id, event["cameraId"], event["type"], event["source"], event["topic"], event["occurredAt"],
            event["severity"], event["confidence"], event["zoneId"], event["label"],
            json.dumps(event["properties"], separators=(",", ":"), sort_keys=True), json.dumps(segments), dedupe, created))
        stored = event | {"id": event_id, "acknowledged": False, "note": "", "segmentIds": segments}
        apply_rules(database, stored)
        retention_days = max(1, min(int(os.environ.get("WEBOBS_EVENT_RETENTION_DAYS", "90")), 3650))
        database.execute("DELETE FROM events WHERE occurred_at<?", (now_ms() - retention_days * 86400_000,))
        database.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY occurred_at DESC LIMIT ?)", (MAX_EVENTS,))
    if event["type"] in {"motion", "tamper", "line-crossing", "region-crossing", "object", "sound", "input"}:
        trigger_nvr_event(event["cameraId"])
    return stored | {"deduplicated": False}


def point_in_polygon(x: float, y: float, polygon: list[list[float]]) -> bool:
    inside, previous = False, polygon[-1]
    for current in polygon:
        if ((current[1] > y) != (previous[1] > y)) and x < (previous[0] - current[0]) * (y - current[1]) / ((previous[1] - current[1]) or 1e-12) + current[0]: inside = not inside
        previous = current
    return inside


def validate_zone(raw: object, zone_id: str = "") -> dict:
    if not isinstance(raw, dict): raise ValueError("zone must be an object")
    zone_id = zone_id or raw.get("id", uuid.uuid4().hex)
    camera_id = raw.get("cameraId", "")
    if not isinstance(zone_id, str) or not ID_RE.fullmatch(zone_id) or not isinstance(camera_id, str) or not ID_RE.fullmatch(camera_id): raise ValueError("zone or camera id is invalid")
    polygon = raw.get("polygon", [])
    if not isinstance(polygon, list) or not 3 <= len(polygon) <= 64 or any(not isinstance(p, list) or len(p) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1 for v in p) for p in polygon): raise ValueError("polygon must contain normalized points")
    sensitivity = raw.get("sensitivity", .15)
    debounce, cooldown = raw.get("debounceMs", 500), raw.get("cooldownMs", 5000)
    if not isinstance(sensitivity, (int, float)) or isinstance(sensitivity, bool) or not .01 <= sensitivity <= 1: raise ValueError("sensitivity is invalid")
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (debounce, cooldown)) or not 0 <= debounce <= 60_000 or not 0 <= cooldown <= 3600_000: raise ValueError("motion timing is invalid")
    mode = raw.get("mode", "include")
    if mode not in {"include", "exclude", "privacy"}: raise ValueError("zone mode is invalid")
    schedule = raw.get("schedule", [])
    if not isinstance(schedule, list) or len(schedule) > 32: raise ValueError("zone schedule is invalid")
    return {"id": zone_id, "cameraId": camera_id, "name": bounded_text(raw.get("name", "Motion zone"), "name", 128, False),
            "mode": mode, "polygon": polygon, "sensitivity": float(sensitivity),
            "debounceMs": debounce, "cooldownMs": cooldown, "schedule": schedule, "enabled": bool(raw.get("enabled", True))}


def evaluate_motion(raw: object) -> list[dict]:
    if not isinstance(raw, dict): raise ValueError("motion frame must be an object")
    camera_id, width, height = raw.get("cameraId", ""), raw.get("width"), raw.get("height")
    previous, current = raw.get("previous", []), raw.get("current", [])
    if not isinstance(camera_id, str) or not ID_RE.fullmatch(camera_id) or not isinstance(width, int) or not isinstance(height, int) or width * height > 262144 or width < 2 or height < 2: raise ValueError("motion frame dimensions are invalid")
    if not isinstance(previous, list) or not isinstance(current, list) or len(previous) != width * height or len(current) != width * height or any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255 for v in previous + current): raise ValueError("motion frames must be bounded grayscale arrays")
    timestamp, emitted = raw.get("occurredAt", now_ms()), []
    with connect() as database: zones = database.execute("SELECT * FROM motion_zones WHERE camera_id=? AND enabled=1", (camera_id,)).fetchall()
    masks = [json.loads(row["polygon_json"]) for row in zones if row["mode"] in {"exclude", "privacy"}]
    for row in zones:
        if row["mode"] != "include": continue
        polygon = json.loads(row["polygon_json"]); changed = total = 0
        for index, (left, right) in enumerate(zip(previous, current)):
            x, y = (index % width + .5) / width, (index // width + .5) / height
            if point_in_polygon(x, y, polygon) and not any(point_in_polygon(x, y, mask) for mask in masks):
                total += 1; changed += abs(left - right) >= 24
        active = bool(total and changed / total >= row["sensitivity"])
        key = (camera_id, row["id"])
        with MOTION_STATE_LOCK:
            state = MOTION_STATE.setdefault(key, {"activeSince": 0, "lastEvent": 0, "active": False})
            if active and not state["active"]: state["activeSince"] = timestamp
            state["active"] = active
            should_emit = active and timestamp - int(state["activeSince"]) >= row["debounce_ms"] and timestamp - int(state["lastEvent"]) >= row["cooldown_ms"]
            if should_emit: state["lastEvent"] = timestamp
        if should_emit: emitted.append(ingest_event({"cameraId": camera_id, "type": "motion", "source": "software-motion", "occurredAt": timestamp, "zoneId": row["id"], "confidence": min(1, changed / max(total, 1)), "properties": {"changedPixels": changed, "sampledPixels": total}}))
    return emitted


def secret(ref: str) -> dict:
    if not ID_RE.fullmatch(ref): raise ValueError("notification destination reference is invalid")
    root, path = SECRET_ROOT.resolve(), (SECRET_ROOT / f"{ref}.json").resolve()
    if root not in path.parents or not path.is_file() or path.stat().st_size > 16_384: raise ValueError("notification destination is unavailable")
    value = json.loads(path.read_text("utf-8")); return json_object(value, "notification secret", 16)


def public_destination(host: str, port: int) -> tuple[int, tuple]:
    allowed = set()
    raw_allowed = os.environ.get("WEBOBS_NOTIFICATION_ALLOWED_HOSTS", "")
    for item in raw_allowed.split(",") if raw_allowed else ():
        candidate = item.strip().lower()
        if not candidate or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", candidate):
            raise ValueError("notification destination allowlist is invalid")
        allowed.add(candidate)
    results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not results: raise ValueError("notification destination cannot be resolved")
    for result in results:
        address = ipaddress.ip_address(result[4][0])
        if not address.is_global and host.lower() not in allowed:
            raise ValueError("notification destination resolves to a private or special address")
    return results[0][0], results[0][4]


def tls_channel(host: str, port: int):
    family, destination = public_destination(host, port)
    raw = socket.socket(family, socket.SOCK_STREAM); raw.settimeout(5)
    try:
        raw.connect(destination)
        ca_file = os.environ.get("WEBOBS_NOTIFICATION_CA_FILE", "")
        if ca_file:
            ca_path = Path(ca_file)
            try:
                ca_path.resolve().relative_to("/run/secrets")
            except ValueError as error:
                raise ValueError("notification CA must be mounted below /run/secrets") from error
            if not ca_path.is_file() or ca_path.is_symlink() or ca_path.stat().st_size > 1024 * 1024:
                raise ValueError("notification CA is unavailable")
        return ssl.create_default_context(cafile=ca_file or None).wrap_socket(raw, server_hostname=host)
    except Exception:
        raw.close(); raise


def mqtt_string(value: str) -> bytes:
    encoded = value.encode(); return struct.pack("!H", len(encoded)) + encoded


def mqtt_remaining(value: int) -> bytes:
    result = bytearray()
    while True:
        digit = value % 128; value //= 128
        if value: digit |= 128
        result.append(digit)
        if not value: return bytes(result)


def mqtt_publications(configuration: dict, payload_json: str) -> list[tuple[str, bytes, bool]]:
    """Build stable v1 MQTT and optional HA Discovery publications.

    Only stable IDs and bounded event state leave the process. Source endpoints,
    credentials, media URLs and arbitrary event properties are intentionally
    excluded from the v1 integration schema.
    """
    explicit = configuration.get("topic", "")
    raw = json.loads(payload_json)
    event = raw.get("event", {}) if isinstance(raw, dict) else {}
    if not isinstance(event, dict):
        event = {}
    camera_id = event.get("cameraId", "")
    event_type = event.get("type", "")
    if (not isinstance(camera_id, str) or not ID_RE.fullmatch(camera_id) or not isinstance(event_type, str) or
            event_type not in EVENT_TYPES) and isinstance(explicit, str) and explicit and len(explicit) <= 256 and \
            "#" not in explicit and "+" not in explicit:
        return [(explicit, payload_json.encode(), False)]
    if not isinstance(camera_id, str) or not ID_RE.fullmatch(camera_id) or not isinstance(event_type, str) or \
            event_type not in EVENT_TYPES:
        raise ValueError("MQTT event envelope is invalid")
    prefix = configuration.get("topicPrefix", "webobs/v1")
    if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z0-9._/-]{1,128}", prefix) or \
            "#" in prefix or "+" in prefix or ".." in prefix.split("/"):
        raise ValueError("MQTT topic prefix is invalid")
    topic = explicit or f"{prefix}/cameras/{camera_id}/events/{event_type}"
    if not isinstance(topic, str) or not topic or len(topic) > 256 or "#" in topic or "+" in topic:
        raise ValueError("MQTT topic is invalid")
    public = {
        "schemaVersion": "webobs.mqtt.v1", "eventId": str(event.get("id", ""))[:64],
        "cameraId": camera_id, "type": event_type,
        "occurredAt": int(event.get("occurredAt", 0)),
        "severity": event.get("severity", "info") if event.get("severity") in {"info", "warning", "error"} else "info",
        "active": True,
    }
    publications = [(topic, json.dumps(public, separators=(",", ":"), sort_keys=True).encode(), False)]
    discovery = configuration.get("homeAssistantDiscoveryPrefix", "")
    if discovery:
        if not isinstance(discovery, str) or not re.fullmatch(r"[A-Za-z0-9._/-]{1,64}", discovery) or \
                "#" in discovery or "+" in discovery:
            raise ValueError("Home Assistant discovery prefix is invalid")
        if event_type in {"motion", "scene-change"}:
            object_id = f"webobs_{camera_id}_{event_type.replace('-', '_')}"
            state_topic = f"{prefix}/cameras/{camera_id}/{event_type}"
            config_topic = f"{discovery}/binary_sensor/{object_id}/config"
            config = {
                "name": f"WebOBS {camera_id} {event_type}", "unique_id": object_id,
                "state_topic": state_topic, "payload_on": "ON", "payload_off": "OFF",
                "off_delay": 30, "device_class": "motion" if event_type == "motion" else "problem",
                "device": {"identifiers": [f"webobs_camera_{camera_id}"], "name": f"WebOBS {camera_id}"},
                "origin": {"name": "Web Camera Monitor Wall", "sw_version": "2.3"},
            }
            publications.append((config_topic, json.dumps(config, separators=(",", ":"), sort_keys=True).encode(), True))
            publications.append((state_topic, b"ON", False))
    return publications


def mqtt_publish(channel, topic: str, payload: bytes, retain: bool = False) -> None:
    publish = mqtt_string(topic) + payload
    packet_type = b"\x31" if retain else b"\x30"
    channel.sendall(packet_type + mqtt_remaining(len(publish)) + publish)


def deliver(row: sqlite3.Row) -> None:
    configuration, payload = secret(row["destination_ref"]), row["payload_json"].encode()
    if row["kind"] == "webhook":
        endpoint = configuration.get("url", ""); parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment: raise ValueError("webhook must be an HTTPS URL without credentials")
        port = parsed.port or 443
        signing = configuration.get("signingSecret", "")
        if not isinstance(signing, str) or len(signing) < 16: raise ValueError("webhook signing secret is invalid")
        signature = hmac.new(signing.encode(), payload, hashlib.sha256).hexdigest()
        path = parsed.path or "/"
        if parsed.query: path += "?" + parsed.query
        authority = parsed.hostname if port == 443 else f"{parsed.hostname}:{port}"
        headers = (f"POST {path} HTTP/1.1\r\nHost: {authority}\r\nContent-Type: application/json\r\n"
                   f"X-WebOBS-Signature-256: sha256={signature}\r\nContent-Length: {len(payload)}\r\n"
                   "Connection: close\r\n\r\n").encode()
        with tls_channel(parsed.hostname, port) as channel:
            channel.sendall(headers + payload)
            response = http.client.HTTPResponse(channel); response.begin(); response.read(1024)
            if response.status < 200 or response.status >= 300: raise OSError("webhook rejected delivery")
    else:
        host, port = configuration.get("host", ""), configuration.get("port", 8883)
        publications = mqtt_publications(configuration, row["payload_json"])
        if not isinstance(host, str) or not host or not isinstance(port, int) or not 1 <= port <= 65535: raise ValueError("MQTT destination is invalid")
        username, password = configuration.get("username", ""), configuration.get("password", "")
        if (username or password) and (not isinstance(username, str) or not isinstance(password, str) or len(username) > 256 or len(password) > 4096): raise ValueError("MQTT credentials are invalid")
        flags = 2 | (0x80 if username else 0) | (0x40 if password else 0)
        client = mqtt_string("MQTT") + bytes([4, flags, 0, 10]) + mqtt_string("webobs-" + uuid.uuid4().hex[:12])
        if username: client += mqtt_string(username)
        if password: client += mqtt_string(password)
        with tls_channel(host, port) as channel:
            channel.sendall(b"\x10" + mqtt_remaining(len(client)) + client)
            reply = channel.recv(4)
            if len(reply) < 4 or reply[3] != 0: raise OSError("MQTT connect rejected")
            for topic, publication, retain in publications:
                mqtt_publish(channel, topic, publication, retain)


def process_outbox(limit: int = 16) -> dict:
    processed = delivered = 0; current = now_ms()
    with connect() as database:
        rows = database.execute("SELECT * FROM notification_outbox WHERE state='pending' AND next_attempt_at<=? AND expires_at>? ORDER BY created_at LIMIT ?", (current, current, limit)).fetchall()
    for row in rows:
        processed += 1
        try: deliver(row); state, error, delivered = "delivered", "", delivered + 1
        except Exception: state, error = "pending", "delivery_failed"
        attempts = row["attempts"] + 1
        if attempts >= 8 or row["expires_at"] <= now_ms(): state = "expired"
        with connect() as database: database.execute("UPDATE notification_outbox SET state=?,attempts=?,next_attempt_at=?,last_error=? WHERE id=?", (state, attempts, now_ms() + min(300_000, 1000 * (2 ** attempts)), error, row["id"]))
    with connect() as database: database.execute("UPDATE notification_outbox SET state='expired',last_error='expired' WHERE state='pending' AND expires_at<=?", (now_ms(),))
    return {"processed": processed, "delivered": delivered}


def outbox_worker() -> None:
    while True:
        try: process_outbox()
        except (OSError, ValueError, sqlite3.Error): pass
        time.sleep(1)


def rows_as_documents(table: str) -> list[dict]:
    allowed = {"motion_zones", "event_rules", "detector_providers", "notification_outbox"}
    if table not in allowed: raise ValueError("table is invalid")
    with connect() as database: rows = database.execute(f"SELECT * FROM {table} ORDER BY updated_at DESC" if table != "notification_outbox" else "SELECT * FROM notification_outbox ORDER BY created_at DESC LIMIT 256").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        for key in list(item):
            if key.endswith("_json"): item[key.removesuffix("_json")] = json.loads(item.pop(key))
        result.append(item)
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "webobs-events"
    def log_message(self, format: str, *args: object) -> None: return
    def respond(self, status: int, value: object) -> None:
        body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode(); self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def payload(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY: raise ValueError("request body is empty or too large")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict): raise ValueError("request JSON must be an object")
        return value
    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")
        if path == "/health": self.respond(200, {"status": "ready", "database": "sqlite-wal", "queueLimit": MAX_OUTBOX}); return
        if path == "/events":
            values = parse_qs(query); clauses, args = [], []
            mapping = {"cameraId": "camera_id", "type": "type", "zoneId": "zone_id", "label": "label", "acknowledged": "acknowledged"}
            for key, column in mapping.items():
                if key in values: clauses.append(f"{column}=?"); args.append(1 if key == "acknowledged" and values[key][0] == "true" else 0 if key == "acknowledged" else values[key][0])
            for key, operator in (("from", ">="), ("to", "<=")):
                if key in values: clauses.append(f"occurred_at{operator}?"); args.append(int(values[key][0]))
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            with connect() as database: rows = database.execute("SELECT * FROM events" + where + " ORDER BY occurred_at DESC LIMIT 500", args).fetchall()
            self.respond(200, {"events": [row_event(row) for row in rows]}); return
        tables = {"/motion-zones": ("motion_zones", "zones"), "/event-rules": ("event_rules", "rules"), "/detector-providers": ("detector_providers", "providers"), "/notification-outbox": ("notification_outbox", "outbox")}
        if path in tables:
            table, key = tables[path]; self.respond(200, {key: rows_as_documents(table)}); return
        self.respond(404, {"error": "not_found"})
    def do_POST(self) -> None:
        try:
            if self.path == "/events": self.respond(201, ingest_event(self.payload())); return
            if self.path == "/motion/evaluate": self.respond(200, {"events": evaluate_motion(self.payload())}); return
            if self.path == "/notification-outbox/process": self.respond(200, process_outbox()); return
            payload = self.payload()
            if self.path == "/motion-zones":
                zone = validate_zone(payload)
                with connect() as database: database.execute("INSERT INTO motion_zones VALUES(?,?,?,?,?,?,?,?,?,?,?)", (zone["id"], zone["cameraId"], zone["name"], zone["mode"], json.dumps(zone["polygon"]), zone["sensitivity"], zone["debounceMs"], zone["cooldownMs"], json.dumps(zone["schedule"]), int(zone["enabled"]), now_ms()))
                self.respond(201, zone); return
            if self.path == "/event-rules":
                rule_id = payload.get("id", uuid.uuid4().hex); conditions = json_object(payload.get("conditions", {}), "conditions", 16); actions = payload.get("actions", [])
                if not isinstance(rule_id, str) or not ID_RE.fullmatch(rule_id) or not isinstance(actions, list) or len(actions) > 8: raise ValueError("rule id or actions are invalid")
                cooldown = payload.get("cooldownMs", 5000)
                if not isinstance(cooldown, int) or isinstance(cooldown, bool) or not 0 <= cooldown <= 86400_000: raise ValueError("rule cooldown is invalid")
                with connect() as database: database.execute("INSERT INTO event_rules VALUES(?,?,?,?,?,?,0,?)", (rule_id, bounded_text(payload.get("name", "Rule"), "name", 128, False), int(bool(payload.get("enabled", True))), json.dumps(conditions), json.dumps(actions), cooldown, now_ms()))
                self.respond(201, {"id": rule_id}); return
            if self.path == "/detector-providers":
                provider_id = payload.get("id", uuid.uuid4().hex)
                if not isinstance(provider_id, str) or not ID_RE.fullmatch(provider_id) or payload.get("apiVersion") != 1 or payload.get("kind") not in {"cpu", "gpu", "remote"}: raise ValueError("detector provider contract is invalid")
                limit = payload.get("resourceLimit", 1)
                if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 64: raise ValueError("provider resource limit is invalid")
                with connect() as database: database.execute("INSERT INTO detector_providers VALUES(?,?,?,?,?,?,?,?)", (provider_id, bounded_text(payload.get("name", "Detector"), "name", 128, False), 1, payload["kind"], int(bool(payload.get("enabled", True))), limit, "configured", now_ms()))
                self.respond(201, {"id": provider_id, "apiVersion": 1}); return
            match = re.fullmatch(r"/detector-providers/([A-Za-z0-9._-]{1,64})/events", self.path)
            if match:
                with connect() as database: provider = database.execute("SELECT * FROM detector_providers WHERE id=? AND enabled=1", (match.group(1),)).fetchone()
                if not provider: self.respond(404, {"error": "provider_not_found"}); return
                if payload.get("schemaVersion") != 1 or not isinstance(payload.get("events"), list) or len(payload["events"]) > provider["resource_limit"] * 64: raise ValueError("provider event batch is invalid")
                events = [ingest_event(dict(item, source="detector-v1")) for item in payload["events"]]
                self.respond(202, {"accepted": len(events), "events": events}); return
            self.respond(404, {"error": "not_found"})
        except (ValueError, TypeError, json.JSONDecodeError, sqlite3.IntegrityError) as error: self.respond(400, {"error": str(error)})
    def do_PUT(self) -> None:
        match = re.fullmatch(r"/events/([a-f0-9]{32})/acknowledgement", self.path)
        if not match: self.respond(404, {"error": "not_found"}); return
        try:
            payload = self.payload(); acknowledged = payload.get("acknowledged")
            if not isinstance(acknowledged, bool): raise ValueError("acknowledged must be boolean")
            note = bounded_text(payload.get("note", ""), "note", 1024)
            with connect() as database:
                changed = database.execute("UPDATE events SET acknowledged=?,note=? WHERE id=?", (int(acknowledged), note, match.group(1))).rowcount
                if changed: database.execute("INSERT INTO event_audit(event_id,operation,actor,created_at) VALUES(?,?,?,?)", (match.group(1), "acknowledge" if acknowledged else "reopen", "operator", now_ms()))
            self.respond(200 if changed else 404, {"id": match.group(1), "acknowledged": acknowledged, "note": note}); return
        except (ValueError, TypeError, json.JSONDecodeError) as error: self.respond(400, {"error": str(error)})


if __name__ == "__main__":
    initialize()
    threading.Thread(target=outbox_worker, daemon=True).start()
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
