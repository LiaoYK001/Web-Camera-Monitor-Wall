#!/usr/bin/env python3
"""Verify one redacted MQTT v1 event and HA discovery publication over TLS."""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import struct
import threading
import time


os.environ["WEBOBS_NOTIFICATION_ALLOWED_HOSTS"] = "mosquitto"
os.environ["WEBOBS_NOTIFICATION_CA_FILE"] = "/run/secrets/cluster-ca.crt"
spec = importlib.util.spec_from_file_location("webobs_events_fixture", "/fixture/event_service.py")
events = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(events)
events.SECRET_ROOT = pathlib.Path("/run/secrets")


def connect():
    channel = events.tls_channel("mosquitto", 8883)
    client = events.mqtt_string("MQTT") + bytes([4, 2, 0, 10]) + events.mqtt_string("m7-gate-subscriber")
    channel.sendall(b"\x10" + events.mqtt_remaining(len(client)) + client)
    if channel.recv(4) != b"\x20\x02\x00\x00":
        raise RuntimeError("fixture MQTT broker rejected the subscriber")
    body = struct.pack("!H", 1) + events.mqtt_string("#") + b"\x00"
    channel.sendall(b"\x82" + events.mqtt_remaining(len(body)) + body)
    reply = channel.recv(5)
    if len(reply) < 5 or reply[0] != 0x90 or reply[-1] != 0:
        raise RuntimeError("fixture MQTT subscription was rejected")
    return channel


def packet(channel) -> tuple[str, bytes]:
    first = channel.recv(1)
    if not first:
        raise RuntimeError("fixture MQTT stream closed")
    multiplier = 1; remaining = 0
    while True:
        value = channel.recv(1)[0]
        remaining += (value & 127) * multiplier
        if not value & 128:
            break
        multiplier *= 128
        if multiplier > 128 ** 3:
            raise RuntimeError("fixture MQTT packet was unbounded")
    payload = b""
    while len(payload) < remaining:
        payload += channel.recv(remaining - len(payload))
    topic_size = struct.unpack("!H", payload[:2])[0]
    return payload[2:2 + topic_size].decode(), payload[2 + topic_size:]


def main() -> None:
    subscriber = connect()
    try:
        time.sleep(0.1)
        row = {
            "destination_ref": "mqtt", "kind": "mqtt",
            "payload_json": json.dumps({"schemaVersion": 1, "event": {
                "id": "fixture-event", "cameraId": "fixture-01", "type": "motion",
                "occurredAt": int(time.time() * 1000), "severity": "info",
                "properties": {"private": "must-not-leave"},
            }}, separators=(",", ":")),
        }
        events.deliver(row)
        received: dict[str, bytes] = {}
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and len(received) < 3:
            topic, payload = packet(subscriber)
            received[topic] = payload
        expected = {
            "webobs/v1/cameras/fixture-01/events/motion",
            "homeassistant/binary_sensor/webobs_fixture-01_motion/config",
            "webobs/v1/cameras/fixture-01/motion",
        }
        if not expected.issubset(received):
            raise SystemExit("versioned MQTT and Home Assistant publications were not observed")
        serialized = b"".join(received.values())
        if b"webobs.mqtt.v1" not in serialized or b"must-not-leave" in serialized:
            raise SystemExit("MQTT integration schema or redaction check failed")
    finally:
        subscriber.close()
    print("MQTT v1 and Home Assistant TLS fixture passed.")


if __name__ == "__main__":
    main()
