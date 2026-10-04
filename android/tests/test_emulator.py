#!/usr/bin/env python3
"""Actual APK/WebView smoke using an isolated complete product image and ADB reverse.

Requires an installed debug APK, web dependencies/dist, Docker, Node and ADB.
Never clears device data, changes LAN/firewall settings or uses camera credentials.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('go2rtc_probe', ROOT / 'tests/test_go2rtc_integration.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serial', required=True, help='Explicit ADB device; no implicit device selection')
    parser.add_argument('--adb', default=shutil.which('adb'))
    parser.add_argument('--docker', default=shutil.which('docker'))
    parser.add_argument('--image', default='webobs:security-fixes')
    parser.add_argument('--core', type=Path, help='Optional freshly compiled Linux webobsd, mounted read-only')
    parser.add_argument('--studio-identities', action='store_true', help='Also verify stable TAKE identities in the installed WebView')
    parser.add_argument('--online-sources', action='store_true', help='Also create/import/play website sources using a backend with bundled extractors')
    parser.add_argument('--device-controls', action='store_true', help='Also exercise authenticated synthetic ONVIF controls and snapshot decoding')
    args = parser.parse_args()
    assert args.adb and args.docker and (ROOT / 'web/dist/index.html').is_file()
    if args.core and not args.core.is_file():
        parser.error('--core must name an existing Linux webobsd binary')
    core_mount = ['--mount', f'type=bind,src={args.core.resolve()},dst=/opt/obs/bin/webobsd,readonly'] if args.core else []
    device_env = ['-e', 'WEBOBS_CAMERA_ALLOW_TEST_ENDPOINTS=true'] if args.device_controls else []
    name = 'webobs-android-test-' + uuid.uuid4().hex[:10]
    port = None
    created = False
    reversed_port = False

    def docker(*arguments):
        return subprocess.check_output([args.docker, *arguments], text=True, stderr=subprocess.STDOUT, timeout=60).strip()

    def adb(*arguments):
        subprocess.run([args.adb, '-s', args.serial, *arguments], check=True, timeout=30, stdout=subprocess.DEVNULL)

    try:
        docker('run', '--detach', '--name', name, '-p', '127.0.0.1::8080',
               '--mount', f'type=bind,src={ROOT / "web/dist"},dst=/opt/webobs/ui,readonly',
               '--mount', f'type=bind,src={ROOT / "cluster/cluster_service.py"},dst=/opt/webobs/bin/webobs-cluster,readonly',
               *core_mount, *device_env,
               '-e', 'WEBOBS_LISTEN_ADDRESS=0.0.0.0', '-e', 'WEBOBS_ALLOW_INSECURE_REMOTE=true',
               '-e', 'WEBOBS_GO2RTC_ENABLED=true', '-e', 'WEBOBS_WEBRTC_ENABLED=false',
               '-e', 'WEBOBS_COMPOSITE_ENABLED=false', '-e', 'WEBOBS_CLUSTER_ENABLED=true',
               '-e', 'WEBOBS_NVR_ENABLED=true',
               '-e', 'WEBOBS_COMPAT_BASIC_AUTH=false', '-e', 'WEBOBS_SESSION_COOKIE_SECURE=false',
               '-e', 'WEBOBS_REGISTRATION_ENABLED=true', args.image)
        created = True
        base = 'http://' + docker('port', name, '8080/tcp').splitlines()[0]
        client = probe.Client(base)
        for _ in range(120):
            try:
                client.expect('/api/v1/health')
                break
            except (OSError, AssertionError):
                time.sleep(.25)
        else:
            raise AssertionError('Isolated backend did not become healthy')
        password = uuid.uuid4().hex
        if args.online_sources:
            # Pipe only the repository-owned fixture program into this disposable backend.
            subprocess.run([args.docker,'exec','-i',name,'python3','-B','-'],input=(ROOT/'tests/prepare_online_source_fixture.py').read_bytes(),check=True,timeout=60)
        if args.device_controls:
            for file in ('test_camera_registry.py', 'prepare_device_control_fixture.py'):
                docker('cp', str(ROOT/'tests'/file), name+':/tmp/'+file)
            docker('exec', '--detach', name, 'python3', '-B', '/tmp/prepare_device_control_fixture.py')
        client.expect('/api/v1/auth/setup', 201, {'username': 'android-admin', 'password': password}, 'POST')
        client.expect('/api/v1/auth/login', body={'username': 'android-admin', 'password': password}, method='POST')
        config = 'streams:\n  synthetic: "ffmpeg:virtual?video=testsrc2&size=160x90#video=h264"\n'
        client.expect(probe.PREFIX + 'api/config', body=config, method='POST')
        client.expect(probe.PREFIX + 'api/restart', method='POST')
        for _ in range(60):
            try:
                assert b'synthetic' in client.expect(probe.PREFIX + 'api/streams')
                break
            except (OSError, AssertionError):
                time.sleep(.25)
        else:
            raise AssertionError('go2rtc restart did not recover')
        client.expect('/api/v1/nvr/config', body={'schemaVersion': 1, 'minFreeBytes': 0, 'cameras': [
            {'id': 'android-archive', 'name': 'Synthetic archive', 'policy': 'off',
             'mainUrl': 'rtsp://camera.invalid/live'}]}, method='PUT')
        # A stopped recorder's real H.264/AAC archive in this disposable image.
        # Never imports user recordings or enables a physical camera.
        stamp = int(time.time() * 1000) // 86400000 * 86400000 + 3600000
        docker('exec', name, 'python3', '-c', '''import pathlib,subprocess,sqlite3,uuid
root=pathlib.Path('/recordings/nvr');target=root/'android-archive.mp4'
subprocess.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i','color=c=blue:s=160x90:r=25','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','6','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart','-y',str(target)],check=True,timeout=20,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
db=sqlite3.connect(root/'catalog.sqlite3')
db.execute("INSERT INTO segments(id,camera_id,start_utc_ms,end_utc_ms,duration_ms,storage_key,kind,video_codec,audio_codec,size_bytes,integrity,locked,created_utc_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(uuid.uuid4().hex,'android-archive',STAMP,STAMP+6000,6000,target.name,'continuous','h264','aac',target.stat().st_size,'ok',0,STAMP))
db.commit()
'''.replace('STAMP', str(stamp)))
        port = base.rsplit(':', 1)[1]
        adb('reverse', 'tcp:' + port, 'tcp:' + port)
        reversed_port = True
        print('Isolated backend and authenticated go2rtc ready; probing actual Android WebView', flush=True)
        subprocess.run(['node', str(ROOT / 'android/tests/emulator-smoke.mjs')], cwd=ROOT, check=True, timeout=360 if args.online_sources else 240,
                       env={**os.environ, 'WEBOBS_ANDROID_SERIAL': args.serial, 'WEBOBS_ANDROID_ORIGIN': base,
                            'WEBOBS_ANDROID_PASSWORD': password, 'WEBOBS_ANDROID_ADB': args.adb,
                            'WEBOBS_ANDROID_STUDIO_IDENTITIES': '1' if args.studio_identities else '0',
                            'WEBOBS_ANDROID_ONLINE_SOURCES': '1' if args.online_sources else '0',
                            'WEBOBS_ANDROID_DEVICE_CONTROLS': '1' if args.device_controls else '0'})
    finally:
        try:
            if reversed_port:
                adb('reverse', '--remove', 'tcp:' + port)
        finally:
            if created:
                docker('rm', '--force', '--volumes', name)


if __name__ == '__main__':
    main()
