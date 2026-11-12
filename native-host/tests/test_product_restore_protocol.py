"""Actual fragmented TCP requests for the restore-I/O witness, no product start."""
import socket
import threading
import time
import unittest

from product_restore_protocol import inspect_request


class RestoreProtocolTests(unittest.TestCase):
    def exchange(self, fragments, *, timeout=.3):
        observed = []
        client, server = socket.socketpair()
        with client, server:
            def receive():
                with server:
                    observed.append(inspect_request(server, b"private-fixture", timeout=timeout))
            thread = threading.Thread(target=receive)
            thread.start()
            try:
                for fragment in fragments:
                    client.sendall(fragment)
                    time.sleep(.01)
                try:
                    client.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                client.settimeout(1)
                try:
                    response = client.recv(4096)
                except ConnectionResetError:
                    response = b""
            finally:
                thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(observed), 1)
        return observed[0], response

    def test_fragmented_options_and_cseq_are_observed_and_echoed(self):
        result, reply = self.exchange([b"OPT", b"IONS rtsp://127.0.0.1:9/pri", b"vate-fixture RTSP/1.0\r\nC",
                                      b"Seq: 27\r\nUser-Agent: fixture\r\n", b"\r\n"])
        self.assertEqual(result["matchingRequests"], 1)
        self.assertEqual(result["options"], 1)
        self.assertIn(b"CSeq: 27\r\n", reply)
        self.assertNotIn(b"private-fixture", reply)

    def test_describe_works_but_other_path_and_invalid_cseq_do_not_match(self):
        for path, sequence, expected in ((b"private-fixture", b"2", 1),
                                         (b"other-private-path", b"2", 0),
                                         (b"private-fixture", b"invalid", 0)):
            result, _ = self.exchange([b"DESCRIBE rtsp://127.0.0.1:9/" + path +
                                      b" RTSP/1.0\r\nCSeq: " + sequence + b"\r\n\r\n"])
            self.assertEqual(result["matchingRequests"], expected)
            self.assertEqual(result["describe"], 1)
            self.assertNotIn(path.decode(), str(result))

    def test_partial_and_oversized_headers_never_count_as_media_requests(self):
        for message in (b"OPTIONS rtsp://127.0.0.1:9/private-fixture RTSP/1.0\r\n",
                        b"OPTIONS rtsp://127.0.0.1:9/private-fixture RTSP/1.0\r\nCSeq: 1\r\nX: " + b"x" * 4030):
            result, reply = self.exchange([message])
            self.assertEqual(result["matchingRequests"], 0)
            self.assertEqual(result["completeHeaders"], 0)
            self.assertEqual(reply, b"")

    def test_silent_peer_has_a_total_deadline(self):
        client, server = socket.socketpair()
        with client, server:
            started = time.monotonic()
            result = inspect_request(server, b"private-fixture", timeout=.1)
            self.assertLess(time.monotonic() - started, 1)
            self.assertEqual(result["matchingRequests"], 0)


if __name__ == "__main__":
    unittest.main()
