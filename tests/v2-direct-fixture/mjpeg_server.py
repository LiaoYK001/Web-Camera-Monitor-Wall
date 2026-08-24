#!/usr/bin/env python3
"""Deterministic Server Push MJPEG fixture with no external endpoint data."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import time


FRAME = subprocess.run([
    "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
    "testsrc2=size=640x360:rate=1", "-frames:v", "1", "-f", "image2pipe",
    "-vcodec", "mjpeg", "pipe:1",
], check=True, capture_output=True).stdout
if not FRAME.startswith(b"\xff\xd8") or not FRAME.endswith(b"\xff\xd9"):
    raise RuntimeError("MJPEG fixture frame generation failed")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - HTTP handler contract
        if self.path != "/camera.mjpeg":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=webobs-frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            while True:
                self.wfile.write(b"--webobs-frame\r\nContent-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(FRAME)}\r\n\r\n".encode("ascii"))
                self.wfile.write(FRAME + b"\r\n")
                self.wfile.flush()
                time.sleep(1 / 15)
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, _format, *args):
        return


ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
