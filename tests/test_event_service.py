#!/usr/bin/env python3
"""Deterministic v1-M11 event and automation contract tests."""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import time
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    loader = SourceFileLoader("webobs_event_service_test", os.environ.get(
        "WEBOBS_TEST_EVENT_SERVICE", str(ROOT / "events" / "event_service.py")))
    specification = importlib.util.spec_from_loader(loader.name, loader)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification); specification.loader.exec_module(module)
    return module


events = load_module()


class EventServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="webobs-event-tests-")
        events.DB_PATH = Path(self.temporary.name) / "events.db"
        events.NVR_DB_PATH = Path(self.temporary.name) / "nvr.db"
        events.SECRET_ROOT = Path(self.temporary.name) / "secrets"; events.SECRET_ROOT.mkdir()
        events.MOTION_STATE.clear(); events.initialize()

    def tearDown(self) -> None: self.temporary.cleanup()

    def test_normalization_deduplication_search_and_ack_audit(self) -> None:
        timestamp = events.now_ms()
        first = events.ingest_event({"cameraId": "front-door", "type": "motion", "source": "onvif", "occurredAt": timestamp, "properties": {"active": True}})
        duplicate = events.ingest_event({"cameraId": "front-door", "type": "motion", "source": "onvif", "occurredAt": timestamp, "properties": {"active": True}})
        self.assertFalse(first["deduplicated"]); self.assertTrue(duplicate["deduplicated"]); self.assertEqual(first["id"], duplicate["id"])
        with events.connect() as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)
            database.execute("UPDATE events SET acknowledged=1,note='reviewed' WHERE id=?", (first["id"],))
            database.execute("INSERT INTO event_audit(event_id,operation,actor,created_at) VALUES(?,?,?,?)", (first["id"], "acknowledge", "operator", timestamp))
            self.assertEqual(database.execute("SELECT operation FROM event_audit").fetchone()[0], "acknowledge")
        with self.assertRaises(ValueError): events.validate_event({"cameraId": "front-door", "type": "face-identity", "source": "onvif"})

    def test_motion_ground_truth_zones_debounce_cooldown_and_mask(self) -> None:
        include = events.validate_zone({"id": "door", "cameraId": "cam-1", "name": "Door", "polygon": [[0,0],[.5,0],[.5,1],[0,1]], "sensitivity": .2, "debounceMs": 100, "cooldownMs": 1000})
        privacy = events.validate_zone({"id": "private", "cameraId": "cam-1", "name": "Private", "mode": "privacy", "polygon": [[.5,0],[1,0],[1,1],[.5,1]], "sensitivity": .2, "debounceMs": 0, "cooldownMs": 1000})
        with events.connect() as database:
            for zone in (include, privacy): database.execute("INSERT INTO motion_zones VALUES(?,?,?,?,?,?,?,?,?,?,?)", (zone["id"],zone["cameraId"],zone["name"],zone["mode"],json.dumps(zone["polygon"]),zone["sensitivity"],zone["debounceMs"],zone["cooldownMs"],"[]",1,events.now_ms()))
        previous = [0] * 16; current = [255 if index % 4 < 2 else 0 for index in range(16)]
        timestamp = events.now_ms()
        self.assertEqual(events.evaluate_motion({"cameraId":"cam-1","width":4,"height":4,"previous":previous,"current":current,"occurredAt":timestamp}), [])
        emitted = events.evaluate_motion({"cameraId":"cam-1","width":4,"height":4,"previous":previous,"current":current,"occurredAt":timestamp + 110})
        self.assertEqual([event["zoneId"] for event in emitted], ["door"])
        self.assertEqual(events.evaluate_motion({"cameraId":"cam-1","width":4,"height":4,"previous":previous,"current":current,"occurredAt":timestamp + 200}), [])

    def test_segment_link_rule_outbox_bound_and_detector_contract(self) -> None:
        timestamp = events.now_ms()
        nvr = sqlite3.connect(events.NVR_DB_PATH)
        try:
            nvr.execute("CREATE TABLE segments(id TEXT,camera_id TEXT,start_utc_ms INTEGER,end_utc_ms INTEGER)")
            nvr.execute("INSERT INTO segments VALUES('segment-a','cam-2',?,?)", (timestamp - 1000, timestamp + 1000))
            nvr.commit()
        finally: nvr.close()
        with events.connect() as database:
            database.execute("INSERT INTO event_rules VALUES(?,?,?,?,?,?,0,?)", ("notify", "Notify", 1, json.dumps({"cameraId":"cam-2","type":"object","label":"person","minimumConfidence":.7}), json.dumps([{"kind":"webhook","destinationRef":"ops"}]), 0, events.now_ms()))
            database.execute("INSERT INTO detector_providers VALUES(?,?,?,?,?,?,?,?)", ("detector","Fixture",1,"cpu",1,1,"configured",events.now_ms()))
        accepted = events.ingest_event({"cameraId":"cam-2","type":"object","source":"detector-v1","occurredAt":timestamp,"label":"person","confidence":.9})
        self.assertEqual(accepted["segmentIds"], ["segment-a"])
        with events.connect() as database:
            outbox = database.execute("SELECT * FROM notification_outbox").fetchone(); self.assertIsNotNone(outbox)
            self.assertNotIn("secret", outbox["payload_json"].lower())
        with self.assertRaises(ValueError): events.validate_event({"cameraId":"cam-2","type":"object","source":"detector-v1","confidence":2})

    def test_webhook_ssrf_and_secret_reference_protection(self) -> None:
        (events.SECRET_ROOT / "local.json").write_text(json.dumps({"url":"https://127.0.0.1/hook","signingSecret":"fixture-signing-secret"}), encoding="utf-8")
        row = {"destination_ref":"local", "payload_json":"{}", "kind":"webhook"}
        with self.assertRaisesRegex(ValueError, "private or special"):
            events.deliver(row)
        with self.assertRaises(ValueError): events.secret("../escape")
        with patch.object(events.socket, "getaddrinfo", return_value=[(2,1,6,"",("127.0.0.1",443))]):
            with self.assertRaises(ValueError): events.public_destination("attacker.invalid", 443)

    def test_index_latency_and_outbox_ceiling_are_bounded(self) -> None:
        with events.connect() as database:
            database.execute("INSERT INTO event_rules VALUES(?,?,?,?,?,?,0,?)", ("bounded", "Bounded", 1, "{}", json.dumps([{"kind":"webhook","destinationRef":"ops"}]), 0, events.now_ms()))
        original_limit = events.MAX_OUTBOX; events.MAX_OUTBOX = 3; durations = []
        try:
            with patch.object(events, "trigger_nvr_event"):
                for index in range(40):
                    started = time.perf_counter_ns(); events.ingest_event({"cameraId":"bench","type":"motion","source":"software-motion","dedupeKey":f"event-{index}","properties":{}}); durations.append((time.perf_counter_ns() - started) / 1_000_000)
            p95 = sorted(durations)[int(len(durations) * .95) - 1]
            self.assertLess(p95, 50, f"event index p95 exceeded budget: {p95:.2f} ms")
            with events.connect() as database: self.assertLessEqual(database.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0], 3)
        finally: events.MAX_OUTBOX = original_limit

    def test_signed_webhook_and_authenticated_mqtt_delivery_frames(self) -> None:
        (events.SECRET_ROOT / "webhook.json").write_text(json.dumps({"url":"https://alerts.example.invalid/hook?site=one","signingSecret":"fixture-signing-secret"}), encoding="utf-8")
        (events.SECRET_ROOT / "mqtt.json").write_text(json.dumps({"host":"mqtt.example.invalid","port":8883,"topic":"webobs/events","username":"fixture-user","password":"fixture-pass"}), encoding="utf-8")
        class FakeChannel:
            def __init__(self): self.sent = []
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def sendall(self, data): self.sent.append(data)
            def recv(self, size): return b"\x20\x02\x00\x00"
        class FakeResponse:
            status = 204
            def __init__(self, channel): pass
            def begin(self): pass
            def read(self, size): return b""
        webhook_channel, mqtt_channel = FakeChannel(), FakeChannel()
        with patch.object(events, "tls_channel", return_value=webhook_channel), patch.object(events.http.client, "HTTPResponse", FakeResponse):
            events.deliver({"destination_ref":"webhook", "payload_json":"{\"event\":1}", "kind":"webhook"})
        request = webhook_channel.sent[0]
        self.assertIn(b"POST /hook?site=one HTTP/1.1", request)
        self.assertIn(b"X-WebOBS-Signature-256: sha256=", request)
        self.assertNotIn(b"fixture-signing-secret", request)
        with patch.object(events, "tls_channel", return_value=mqtt_channel):
            events.deliver({"destination_ref":"mqtt", "payload_json":"{\"event\":1}", "kind":"mqtt"})
        frames = b"".join(mqtt_channel.sent)
        self.assertIn(b"fixture-user", frames); self.assertIn(b"fixture-pass", frames); self.assertIn(b"webobs/events", frames)


if __name__ == "__main__": unittest.main()
