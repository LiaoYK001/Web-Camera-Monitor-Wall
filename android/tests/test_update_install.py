#!/usr/bin/env python3
"""Real DownloadManager and confirmed APK upgrades in an owned, separate MuMu package.

Uses a synthetic ADB-reversed feed/transport; never publishes, changes the existing
WebOBS package/data, grants its permissions, or installs an APK under its ID.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = 'io.github.liaoyk001.webobs.android.updatequalification'
RUNNER = PACKAGE + '.test/io.github.liaoyk001.webobs.android.UpdateQualification'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serial', required=True)
    parser.add_argument('--adb', required=True)
    parser.add_argument('--java-home', default='D:/zulu')
    parser.add_argument('--sdk', default=str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'WebOBS-Android/sdk'))
    parser.add_argument('--skip-build', type=Path, help='Reuse an existing owned qualification artifact directory')
    args = parser.parse_args()
    output = ROOT / 'build/android/update-qualification' / uuid.uuid4().hex
    if args.skip_build:
        output = args.skip_build.resolve()
        assert output.is_relative_to((ROOT / 'build/android/update-qualification').resolve())
    output.mkdir(parents=True, exist_ok=True)
    checks, created, reverse = [], [], None
    server = None
    ui_driver = None
    key_root = Path(tempfile.mkdtemp(prefix='webobs-update-test-key-')).resolve()
    key_parent = Path(tempfile.gettempdir()).resolve()
    assert key_root.parent == key_parent and not key_root.is_relative_to(ROOT)

    def adb(*parts, timeout=40):
        return subprocess.check_output([args.adb, '-s', args.serial, *map(str, parts)], timeout=timeout, stderr=subprocess.STDOUT).decode('utf-8', 'replace')

    def present(package):
        return bool(re.search(r'^package:' + re.escape(package) + r'$', adb('shell', 'pm', 'list', 'packages', package), re.M))

    for package in (PACKAGE, PACKAGE + '.test'):
        assert not present(package), 'Refuse existing qualification installation; preserve its data'
    env = dict(os.environ)
    env.update(WEBOBS_ANDROID_KEY_ALIAS='webobs-qualification', WEBOBS_ANDROID_STORE_PASSWORD=secrets.token_urlsafe(32), WEBOBS_ANDROID_KEY_PASSWORD=secrets.token_urlsafe(32))
    # PKCS12 uses a shared password; neither password appears in command arguments/output.
    env['WEBOBS_ANDROID_KEY_PASSWORD'] = env['WEBOBS_ANDROID_STORE_PASSWORD']
    try:
        if not args.skip_build:
            for name in ('original', 'other'):
                env['WEBOBS_ANDROID_KEYSTORE'] = str(key_root / (name + '.p12'))
                subprocess.run([str(Path(args.java_home) / 'bin/keytool.exe'), '-genkeypair', '-noprompt', '-storetype', 'PKCS12', '-keystore', env['WEBOBS_ANDROID_KEYSTORE'], '-alias', env['WEBOBS_ANDROID_KEY_ALIAS'], '-storepass:env', 'WEBOBS_ANDROID_STORE_PASSWORD', '-keypass:env', 'WEBOBS_ANDROID_KEY_PASSWORD', '-keyalg', 'RSA', '-keysize', '2048', '-validity', '14', '-dname', 'CN=WebOBS Update Qualification'], env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for kind, version in [('base', '4.0.0'), ('next', '4.0.1'), ('next2', '4.0.2'), ('wrong-key', '4.0.1'), ('wrong-package', '4.0.1')]:
                env['WEBOBS_ANDROID_KEYSTORE'] = str(key_root / ('other.p12' if kind == 'wrong-key' else 'original.p12'))
                with (output / (kind + '-build.txt')).open('w', encoding='utf-8') as log:
                    subprocess.run(['pwsh', '-NoProfile', '-File', str(ROOT / 'android/tests/build_update_qualification.ps1'), '-Version', version, '-Kind', kind, '-OutputDirectory', str(output), '-JavaHome', args.java_home, '-SdkRoot', args.sdk], env=env, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=240)
                print('Built isolated qualification APK:', kind, flush=True)
        artifacts = {name: (output / (name + '.apk')).read_bytes() for name in ('base', 'next', 'next2', 'wrong-key', 'wrong-package')}
        state = {'target': 'next', 'dirty': False, 'hold': False}
        release_slow = threading.Event(); release_slow.set()
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                route = self.path.split('?', 1)[0]
                if route == '/work': data = json.dumps({'dirty': state['dirty'], 'exporting': False}).encode()
                elif route == '/':
                    data = b'''<!doctype html><meta charset="utf-8"><title>Owned update qualification</title><p>APK update qualification</p><script>let work={dirty:false,exporting:false};window.webobsUpdateWork=()=>work;setInterval(()=>fetch('/work').then(r=>r.json()).then(v=>work=v),200);</script>'''
                elif route == '/missing': self.send_error(404); return
                elif route not in ('/base', '/next', '/wrong-key', '/wrong-package', '/corrupt', '/oversized', '/slow', '/transient'):
                    self.send_error(404); return
                else:
                    requests.append(dict(self.headers))
                    data = artifacts[route[1:]] if route[1:] in ('base', 'wrong-key', 'wrong-package') else artifacts[state['target']]
                    if route == '/corrupt': data = bytes([data[0] ^ 1]) + data[1:]
                    if route == '/oversized': data += b'x' * 65536
                self.send_response(200); self.send_header('Content-Length', str(len(data)))
                self.send_header('Content-Type', 'text/html' if route == '/' else 'application/json' if route == '/work' else 'application/vnd.android.package-archive'); self.end_headers()
                try:
                    if route == '/slow':
                        if state['hold']: release_slow.wait(30)
                        for offset in range(0, len(data), 4096): self.wfile.write(data[offset:offset+4096]); self.wfile.flush(); time.sleep(.1)
                    else: self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]; origin = f'http://127.0.0.1:{port}'
        assert not re.search(r'\btcp:' + str(port) + r'\b', adb('reverse', '--list')), 'Preserve existing reverse'
        adb('reverse', f'tcp:{port}', f'tcp:{port}'); reverse = port
        for package, apk in [(PACKAGE, 'base.apk'), (PACKAGE + '.test', 'instrumentation.apk')]:
            created.append(package); assert 'Success' in adb('install', str(output / apk), timeout=60)

        def instrument(mode, **extra):
            values = {'mode': mode, 'origin': origin, **extra}
            for name in ('base', 'next', 'wrong-key', 'wrong-package'):
                value = artifacts[state['target'] if name == 'next' else name]
                values[name + 'Hash'] = hashlib.sha256(value).hexdigest(); values[name + 'Size'] = str(len(value))
            options = [part for pair in values.items() for part in ('-e', *pair)]
            result = adb('shell', 'am', 'instrument', '-w', '-r', *options, RUNNER, timeout=180)
            (output / (mode + '-' + str(len(checks)) + '.txt')).write_text(result, encoding='utf-8')
            assert 'PASS:' in result and 'FAIL:' not in result and 'INSTRUMENTATION_CODE: 0' in result, result
            checks.append(mode); print('PASS:', mode, flush=True)

        def native(pattern, resource=False, tap=False):
            ui_driver.stdin.write(json.dumps({'pattern': pattern, 'resource': resource, 'tap': tap}, ensure_ascii=False) + '\n'); ui_driver.stdin.flush()
            result = json.loads(ui_driver.stdout.readline())
            if not result.get('ok'):
                ui_driver.stdin.write('{"capture":true}\n'); ui_driver.stdin.flush(); ui_driver.stdout.readline()
                ui_driver.stdin.write('{"inspect":true}\n'); ui_driver.stdin.flush()
                (output / 'native-selector.txt').write_text(ui_driver.stdout.readline(), encoding='utf-8')
            assert result.get('ok'), 'Native UI: ' + result.get('error', 'missing driver response')

        def find(pattern, resource=False): native(pattern, resource)
        def tap(pattern, resource=False): native(pattern, resource, True)

        def version():
            match = re.search(r'\bversionName=(\S+)', adb('shell', 'dumpsys', 'package', PACKAGE))
            return match.group(1)

        def about():
            adb('shell', 'am', 'force-stop', PACKAGE)
            adb('shell', 'am', 'start', '-W', '-n', PACKAGE + '/io.github.liaoyk001.webobs.android.MainActivity')
            tap(r'app_menu$', True); tap('关于与检查更新'); find('安装更新')

        instrument('cases')
        state['hold'] = True; release_slow.clear(); instrument('start-partial')
        adb('shell', 'am', 'force-stop', PACKAGE); state['hold'] = False; release_slow.set(); instrument('resume')
        ui_driver = subprocess.Popen(['node', str(ROOT / 'android/tests/update-ui-driver.mjs')], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=(output / 'ui-driver.txt').open('w', encoding='utf-8'), text=True, encoding='utf-8', env={**os.environ, 'WEBOBS_ANDROID_SERIAL': args.serial, 'WEBOBS_ANDROID_ADB': args.adb, 'WEBOBS_ANDROID_OUTPUT': str(output)})
        for target, expected in [('next', '4.0.1'), ('next2', '4.0.2')]:
            state['target'] = target; instrument('prepare', version=expected); about()
            if expected == '4.0.1':
                adb('shell', 'appops', 'set', PACKAGE, 'REQUEST_INSTALL_PACKAGES', 'deny')
                tap(r'update_install$', True); find('允许 WebOBS 安装更新'); tap('稍后')
                assert version() == '4.0.0'; checks.append('unknown-source permission denied without installation')
                adb('shell', 'appops', 'set', PACKAGE, 'REQUEST_INSTALL_PACKAGES', 'allow')
                state['dirty'] = True; time.sleep(1); tap(r'update_install$', True); find('请先处理当前工作'); tap('返回处理')
                assert version() == '4.0.0'; checks.append('reported draft blocks install')
                state['dirty'] = False; time.sleep(1)
            tap(r'update_install$', True); tap('校验并交给系统安装')
            tap(r'^(Install|Update|安装|更新)$')
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline and version() != expected: time.sleep(.3)
            assert version() == expected, 'System installer did not install the confirmed update'
            tap(r'^(Done|完成)$')
            checks.append('system installer confirmed ' + expected); instrument('retained', installed=expected)
        assert all(not any(key.lower() in ('cookie', 'authorization') for key in headers) for headers in requests), 'Native APK request forwarded credentials'
        checks.append('APK requests have no Cookie or Authorization')
        subprocess.run([args.adb, '-s', args.serial, 'shell', 'input', 'keyevent', 'KEYCODE_HOME'], check=True, stdout=subprocess.DEVNULL)
        receipt = {'schema': 1, 'date': datetime.now(timezone.utc).isoformat(), 'source': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(), 'workingTreeChanges': True, 'checks': checks, 'versions': ['4.0.0', '4.0.1', '4.0.2'], 'artifacts': {name: hashlib.sha256(value).hexdigest() for name, value in artifacts.items()}, 'feed': 'synthetic loopback, no publication', 'existingProductDataModified': False, 'platform': {'sdk': adb('shell', 'getprop', 'ro.build.version.sdk').strip(), 'abi': adb('shell', 'getprop', 'ro.product.cpu.abi').strip()}, 'qualified': 'owned isolated package only'}
        (output / 'result.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        print('PASS: actual two confirmed updates and data retention; receipt:', output / 'result.json', flush=True)
    finally:
        if ui_driver:
            ui_driver.stdin.close()
            try: ui_driver.wait(timeout=15)
            except subprocess.TimeoutExpired: ui_driver.terminate(); ui_driver.wait(timeout=10)
        for package in reversed(created):
            try: adb('uninstall', package)
            except (subprocess.SubprocessError, OSError): pass
        if reverse:
            try: adb('reverse', '--remove', 'tcp:' + str(reverse))
            except (subprocess.SubprocessError, OSError): pass
        if server: server.shutdown(); server.server_close()
        if key_root.exists() and key_root.parent == key_parent: shutil.rmtree(key_root)


if __name__ == '__main__': main()
