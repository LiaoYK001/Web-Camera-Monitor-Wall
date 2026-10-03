"""Loopback NVR HTTP validators, reader lifetime and account resource contracts."""
import hashlib
import http.client
import http.server
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'nvr'))
import nvr_service as nvr


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='WebOBS media ')
        root = pathlib.Path(self.temp.name)
        self.service = nvr.NvrService(root / 'config.json', root / 'storage')
        self.service.audit = mock.Mock()
        self.service.config = nvr.validate_config({'schemaVersion': 1, 'cameras': [
            {'id': name, 'mainUrl': 'rtsp://camera.invalid/live', 'policy': 'off'} for name in ['a', 'b']]})
        self.service.catalog.sync_cameras(self.service.config)
        self.payload = bytes(range(256)) * 1024
        self.segment = 'a' * 32
        path = self.service.storage_root / 'media.mp4'
        path.write_bytes(self.payload)
        self.service.catalog.add_segment({'id': self.segment, 'cameraId': 'a', 'startUtcMs': 1000,
            'endUtcMs': 2000, 'durationMs': 1000, 'storageKey': path.name, 'kind': 'continuous',
            'videoCodec': 'h264', 'audioCodec': '', 'sizeBytes': len(self.payload), 'integrity': 'ok'})
        self.env = mock.patch.dict(os.environ, {'WEBOBS_CLUSTER_ENABLED': 'false', 'WEBOBS_CLUSTER_INTERNAL_TOKEN': ''})
        self.env.start()
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), nvr.Handler)
        self.server.service = self.service
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.service.catalog.connection.close()
        self.env.stop()
        self.temp.cleanup()

    def request(self, path=None, method='GET', headers=None, body=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        connection.request(method, path or '/media/' + self.segment, body=body, headers=headers or {})
        response = connection.getresponse()
        status, fields, payload = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, fields, payload

    def assert_readers_released(self):
        # A HEAD/416 client can receive the final headers before the server
        # thread exits its reader context. Require bounded eventual cleanup.
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            with self.service.reader_lock:
                if not self.service.active_readers:
                    return
            time.sleep(.005)
        self.assertFalse(self.service.active_readers, 'Media reader did not release within one second')

    def test_ranges_head_and_conditional_resume(self):
        status, headers, payload = self.request()
        self.assertEqual((status, payload), (200, self.payload))
        etag = headers['ETag']
        self.assertEqual(self.request(method='HEAD')[2], b'')
        self.assertEqual(self.request(method='HEAD')[1]['Content-Length'], str(len(self.payload)))
        status, headers, payload = self.request(headers={'Range': 'bytes=123-456', 'If-Range': etag})
        self.assertEqual((status, payload), (206, self.payload[123:457]))
        self.assertEqual(headers['Content-Range'], f'bytes 123-456/{len(self.payload)}')
        self.assertEqual(self.request(headers={'Range': 'bytes=-32'})[2], self.payload[-32:])
        self.assertEqual(self.request(headers={'Range': 'bytes=123-', 'If-Range': '"changed"'})[0], 200)
        self.assertEqual(self.request(headers={'If-None-Match': 'W/' + etag})[0], 304)
        for value in ['bytes=-0', 'bytes=-', 'bytes=9999999-', 'bytes=10-5', 'bytes=0-1,2-3']:
            status, fields, payload = self.request(headers={'Range': value})
            self.assertEqual(status, 416, value)
            self.assertEqual(fields['Content-Range'], f'bytes */{len(self.payload)}')
            self.assertEqual(payload, b'')
        self.assert_readers_released()

    def test_permissions_are_checked_even_for_head_and_304(self):
        def deny(*_args, **_kwargs):
            raise nvr.EvidenceError('recording_scope_rejected', 'Revoked', 403)
        with mock.patch.object(self.service, 'authorize_segment', side_effect=deny):
            for method in ['GET', 'HEAD']:
                status, _, _ = self.request(method=method, headers={'X-WebObs-Nvr-Principal': 'scoped-user'})
                self.assertEqual(status, 403)
            self.assertEqual(self.request(headers={'If-None-Match': '*', 'X-WebObs-Nvr-Principal': 'scoped-user'})[0], 403)
        self.assert_readers_released()

    def test_filtered_lists_do_not_expand_empty_camera_scopes(self):
        with mock.patch.object(self.service, 'authorized_cameras', return_value=[]):
            self.assertEqual(self.service.segments({}, 'scoped-user'), [])
            timeline = self.service.timeline({'from': ['1000'], 'to': ['3000']}, 'scoped-user')
            self.assertEqual(timeline['cameras'], [])
        for query in [{'cameraId': ['']}, {'cameraId': ['../a']}, {'cameraId': ['a'] * 65}]:
            with self.assertRaises(nvr.ConfigError):
                self.service.segments(query, 'scoped-user')

    def test_stopped_recorders_remain_available_for_scoped_playback(self):
        self.assertFalse(self.service.workers)
        with mock.patch.object(self.service, 'authorized_cameras', return_value=['a']):
            status = self.service.status('account-a')
            self.assertEqual([camera['id'] for camera in status['cameras']], ['a'])
            self.assertEqual(status['cameras'][0]['state'], 'idle')

    def test_revoked_stream_closes_without_appending_an_error_response(self):
        calls = 0
        def revoke(*_args):
            nonlocal calls
            calls += 1
            if calls >= 3:
                raise nvr.EvidenceError('recording_scope_rejected', 'Revoked', 403)
        with mock.patch.object(nvr.Handler, 'access_recheck_seconds', 0), \
                mock.patch.object(self.service, 'authorize_segment', side_effect=revoke):
            connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
            try:
                connection.request('GET', '/media/' + self.segment, headers={'X-WebObs-Nvr-Principal': 'scoped-user'})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                with self.assertRaises(http.client.IncompleteRead) as error:
                    response.read()
                self.assertEqual(error.exception.partial, self.payload[:65536])
            finally:
                connection.close()
        self.assert_readers_released()

    def test_alias_batch_authorization_is_fresh_bounded_and_fails_closed(self):
        self.service.config['cameras'][0]['cameraId'] = 'registry-camera'
        approved = mock.MagicMock()
        approved.__enter__.return_value = approved
        approved.status = 200
        approved.read.return_value = b'{"permission":"playback.view","cameraIds":["registry-camera"]}'
        with mock.patch.dict(os.environ, {'WEBOBS_CLUSTER_ENABLED': 'true', 'WEBOBS_CLUSTER_INTERNAL_TOKEN': 'a' * 64}), \
                mock.patch.object(nvr.urllib.request, 'urlopen', return_value=approved) as authorize:
            self.assertEqual(self.service.authorized_cameras('account-a', 'playback.view', ['a']), ['a'])
            payload = json.loads(authorize.call_args.args[0].data)
            self.assertEqual(payload['cameraIds'], ['registry-camera'])
            approved.read.return_value = b'{"permission":"playback.view","cameraIds":[]}'
            with self.assertRaises(nvr.EvidenceError) as error:
                self.service.authorized_cameras('account-a', 'playback.view', ['a'])
            self.assertEqual(error.exception.status, 403)
            self.assertEqual(self.service.authorized_cameras('account-a', 'playback.view', ['a'], require_all=False), [])
            approved.read.return_value = b'[]'
            with self.assertRaises(nvr.EvidenceError) as error:
                self.service.authorized_cameras('account-a', 'playback.view', ['a'])
            self.assertEqual(error.exception.status, 503)

    def test_playback_lease_owner_and_capacity(self):
        request = {'segmentId': self.segment, 'ttlSeconds': 30}
        lease = self.service.create_playback_lease(request, 'account-a')
        with self.assertRaises(KeyError):
            self.service.release_playback_lease(lease['id'], 'account-b')
        self.assertIn(lease['id'], self.service.playback_leases)
        for _ in range(63):
            self.service.create_playback_lease(request, 'account-a')
        with self.assertRaises(nvr.EvidenceError) as error:
            self.service.create_playback_lease(request, 'account-a')
        self.assertEqual(error.exception.status, 429)
        self.service.release_playback_lease(lease['id'], 'account-a')

    def test_snapshot_catalog_owner_and_scope_survive_restart(self):
        preview = self.service.thumbnail_root / 'preview.jpg'
        preview.write_bytes(b'synthetic-thumbnail')
        with mock.patch.object(self.service, 'thumbnail', return_value=preview):
            snapshot = self.service.snapshot({'segmentId': self.segment, 'offsetMs': 0}, 'account-a')
        self.assertFalse(self.service.active_readers)
        self.service.catalog.connection.close()
        self.service = nvr.NvrService(self.service.config_path, self.service.storage_root)
        self.server.service = self.service
        relative = snapshot['id'] + '.jpg'
        with self.assertRaises(KeyError):
            self.service.download_path(relative, 'account-b')
        with mock.patch.object(self.service, 'authorized_cameras') as check:
            path, _ = self.service.download_path(relative, 'account-a')
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), snapshot['sha256'])
            check.assert_called_once_with('account-a', 'snapshot.create', ['a'])


if __name__ == '__main__':
    unittest.main()
