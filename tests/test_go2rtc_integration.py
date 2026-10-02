#!/usr/bin/env python3
"""Real single-image HTTP/WS/media/RBAC/persistence smoke test; no cameras needed."""
import argparse
import base64
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

PREFIX = '/api/v1/go2rtc/'


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.STDOUT, timeout=45).strip()


class Client:
    def __init__(self, base):
        self.base = base
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, path, body=None, method='GET', origin=None):
        headers = {'Origin': self.base if origin is None else origin}
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        elif isinstance(body, str):
            body = body.encode()
        request = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            return self.opener.open(request, timeout=15)
        except urllib.error.HTTPError as error:
            return error

    def expect(self, path, code=200, body=None, method='GET', origin=None):
        with self.request(path, body, method, origin) as reply:
            data = reply.read()
            assert reply.status == code, f'{method} {path.split("?")[0]}: expected {code}, got {reply.status}'
            return data


def receive_exact(sock, count):
    data = b''
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise AssertionError('WebSocket closed early')
        data += chunk
    return data


def websocket_media(client):
    endpoint = urllib.parse.urlsplit(client.base)
    with socket.create_connection((endpoint.hostname, endpoint.port), timeout=15) as sock:
        key = base64.b64encode(os.urandom(16)).decode()
        cookie = '; '.join(f'{item.name}={item.value}' for item in client.cookies)
        request = (f'GET {PREFIX}api/ws?src=synthetic HTTP/1.1\r\nHost: {endpoint.netloc}\r\n'
                   f'Origin: {client.base}\r\nCookie: {cookie}\r\nUpgrade: websocket\r\n'
                   f'Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n')
        sock.sendall(request.encode())
        header = b''
        while not header.endswith(b'\r\n\r\n'):
            header += receive_exact(sock, 1)
        assert header.startswith(b'HTTP/1.1 101'), 'authenticated WebSocket handshake failed'
        expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
        assert expected in header
        message = json.dumps({'type': 'mse', 'value': 'avc1.640029'}).encode()
        mask = os.urandom(4)
        sock.sendall(bytes([0x81, 0x80 | len(message)]) + mask + bytes(value ^ mask[i % 4] for i, value in enumerate(message)))
        text_seen = False
        for _ in range(12):
            first, second = receive_exact(sock, 2)
            count = second & 127
            if count == 126:
                count = struct.unpack('!H', receive_exact(sock, 2))[0]
            elif count == 127:
                count = struct.unpack('!Q', receive_exact(sock, 8))[0]
            payload = receive_exact(sock, count)
            if first & 15 == 1:
                assert json.loads(payload)['type'] != 'error', 'upstream MSE stream failed'
                text_seen = True
            if first & 15 == 2 and payload:
                assert text_seen, 'MSE metadata missing'
                return
        raise AssertionError('no binary MSE media received')


def run(image):
    name = 'webobs-go2rtc-test-' + uuid.uuid4().hex[:10]
    created = False
    try:
        docker('run', '--detach', '--name', name, '-p', '127.0.0.1::8080',
               '-e', 'WEBOBS_LISTEN_ADDRESS=0.0.0.0', '-e', 'WEBOBS_ALLOW_INSECURE_REMOTE=true',
               '-e', 'WEBOBS_GO2RTC_ENABLED=true', '-e', 'WEBOBS_WEBRTC_ENABLED=false',
               '-e', 'WEBOBS_COMPOSITE_ENABLED=false', '-e', 'WEBOBS_CLUSTER_ENABLED=true',
               '-e', 'WEBOBS_COMPAT_BASIC_AUTH=false', '-e', 'WEBOBS_SESSION_COOKIE_SECURE=false',
               '-e', 'WEBOBS_REGISTRATION_ENABLED=true', image)
        created = True
        base = 'http://' + docker('port', name, '8080/tcp').splitlines()[0]
        anonymous = Client(base)
        for _ in range(120):
            try:
                anonymous.expect('/api/v1/health')
                break
            except (OSError, AssertionError):
                time.sleep(.25)
        else:
            raise AssertionError('product startup timed out')
        anonymous.expect(PREFIX + 'api', 401)
        admin = Client(base)
        password = uuid.uuid4().hex
        admin.expect('/api/v1/auth/setup', 201, body={'username': 'bridge-admin', 'password': password}, method='POST')
        admin.expect('/api/v1/auth/login', body={'username': 'bridge-admin', 'password': password}, method='POST')
        info = json.loads(admin.expect(PREFIX + 'api'))
        print('Login and upstream API passed', flush=True)
        assert info['version'].startswith('1.9.14'), 'wrong upstream version'
        for page in ['', 'add.html', 'config.html', 'log.html', 'net.html', 'links.html?src=synthetic', 'stream.html?src=synthetic']:
            assert b'<html' in admin.expect(PREFIX + page), 'missing official page'
        assert b'define' in admin.expect(PREFIX + 'vendor/monaco-editor/min/vs/loader.js')
        assert b'vis' in admin.expect(PREFIX + 'vendor/vis-network/standalone/umd/vis-network.min.js')
        with admin.request(PREFIX + 'config.html') as reply:
            assert reply.headers['Cache-Control'] == 'no-store'
            assert "frame-ancestors 'self'" in reply.headers['Content-Security-Policy']
        admin.expect(PREFIX + 'api/config', 403, body='streams: {}', method='POST', origin='https://other.invalid')
        admin.expect(PREFIX + '%2e%2e/api/config', 403)
        admin.expect('/api/v2/users', 201, body={'username': 'bridge-viewer', 'password': password, 'roles': ['viewer'], 'scopes': []}, method='POST')
        viewer = Client(base)
        viewer.expect('/api/v1/auth/login', body={'username': 'bridge-viewer', 'password': password}, method='POST')
        for page in ['', 'config.html', 'api/config', 'api/log', 'api/ws?src=synthetic']:
            viewer.expect(PREFIX + page, 403)
        print('Official UI/assets and RBAC/Origin passed', flush=True)
        config = 'streams:\n  synthetic: "ffmpeg:virtual?video=testsrc2&size=160x90#video=h264"\n'
        admin.expect(PREFIX + 'api/config', body=config, method='POST')
        admin.expect(PREFIX + 'api/restart', method='POST')
        for _ in range(40):
            try:
                assert b'synthetic' in admin.expect(PREFIX + 'api/streams')
                break
            except (OSError, AssertionError):
                time.sleep(.25)
        else:
            raise AssertionError('upstream Save & Restart did not recover')
        websocket_media(admin)
        print('WebSocket/MSE binary media passed', flush=True)
        with admin.request(PREFIX + 'api/stream.mp4?src=synthetic') as media:
            assert media.status == 200
            assert b'ftyp' in media.read(64), 'HTTP streaming did not deliver MP4 promptly'
        print('HTTP/MP4 streaming passed', flush=True)
        subprocess.run(['node', 'tests/go2rtc-image-probe.mjs'],
                       cwd=Path(__file__).resolve().parents[1] / 'web', check=True, timeout=60,
                       env={**os.environ, 'WEBOBS_GO2RTC_TEST_ORIGIN': base,
                            'WEBOBS_GO2RTC_TEST_PASSWORD': password})
        docker('exec', name, 'ffprobe', '-v', 'error', '-rtsp_transport', 'tcp',
               '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', 'rtsp://127.0.0.1:18554/synthetic')
        docker('restart', name)
        # Docker may allocate a different ephemeral published port on restart.
        base = 'http://' + docker('port', name, '8080/tcp').splitlines()[0]
        admin.base = base
        print('Product restarted; verifying persisted configuration', flush=True)
        for attempt in range(120):
            try:
                admin.expect('/api/v1/auth/login', body={'username': 'bridge-admin', 'password': password}, method='POST')
                assert admin.expect(PREFIX + 'api/config').decode() == config
                break
            except (OSError, AssertionError) as error:
                if attempt == 0:
                    print(f'Restart readiness pending: {error}', flush=True)
                time.sleep(.25)
        else:
            raise AssertionError('configuration did not persist across product restart')
        # A config edit cannot reopen the protected management boundary.
        malicious = config + 'api:\n  listen: ":1984"\n  base_path: /changed\nrtsp:\n  listen: ":8554"\n'
        admin.expect(PREFIX + 'api/config', body=malicious, method='POST')
        admin.expect(PREFIX + 'api/restart', method='POST')
        time.sleep(1)
        assert json.loads(admin.expect(PREFIX + 'api'))['rtsp']['listen'] == '127.0.0.1:18554'
        docker('stop', '--time', '15', name)
        assert docker('inspect', '-f', '{{.State.ExitCode}}', name) == '0', 'shutdown failed'
        print('PASS: single image, complete UI/local assets, login/RBAC/Origin, WS+HTTP media, RTSP, restart/persistence, shutdown')
    finally:
        if created:
            docker('rm', '--force', '--volumes', name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', default='webobs:go2rtc-dev')
    run(parser.parse_args().image)
