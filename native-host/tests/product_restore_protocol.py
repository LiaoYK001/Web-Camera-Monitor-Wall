"""Bounded test-only RTSP request witness; never returns URLs or header values."""
from __future__ import annotations

import re
import time


def inspect_request(connection, token: bytes, *, timeout=1.0):
    result = {"tcpConnections": 1, "completeHeaders": 0, "options": 0,
              "describe": 0, "matchingRequests": 0}
    deadline = time.monotonic() + timeout
    message = bytearray()
    try:
        # A TCP recv can contain any prefix of an RTSP request. Do not answer
        # before the bounded complete header, including its CSeq, has arrived.
        while b"\r\n\r\n" not in message and len(message) < 4096:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return result
            connection.settimeout(remaining)
            chunk = connection.recv(4096 - len(message))
            if not chunk:
                return result
            message.extend(chunk)
        if b"\r\n\r\n" not in message:
            return result
        result["completeHeaders"] = 1
        first = message.split(b"\r\n", 1)[0]
        result["options"] = int(first.startswith(b"OPTIONS rtsp://"))
        result["describe"] = int(first.startswith(b"DESCRIBE rtsp://"))
        sequence = re.search(rb"(?:^|\r\n)CSeq:[ \t]*([0-9]{1,10})[ \t]*\r\n", message, re.I)
        if sequence and (result["options"] or result["describe"]) and b"/" + token + b" RTSP/1.0" in first:
            result["matchingRequests"] = 1
        if sequence:
            connection.sendall(b"RTSP/1.0 404 Not Found\r\nCSeq: " + sequence[1] +
                               b"\r\nContent-Length: 0\r\n\r\n")
    except OSError:
        pass
    return result
