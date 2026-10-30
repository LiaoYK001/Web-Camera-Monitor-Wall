#!/usr/bin/env python3
"""Real isolated image restart/crash recovery; never touches existing deployments."""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import time
import uuid

from test_go2rtc_integration import Client, PREFIX, websocket_media


def run(options):
    name = 'webobs-restart-test-' + uuid.uuid4().hex[:10]

    def docker(*args):
        result = subprocess.run([options.docker, *args], text=True, capture_output=True,
                                timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        # Do not dump container logs, inspect environments or private config.
        assert result.returncode == 0, 'Docker operation failed: ' + args[0]
        return (result.stdout + (result.stderr if args[0] == 'logs' else '')).strip()

    def state():
        return json.loads(docker('inspect', '--format', '{{json .State}}', name))

    def ready(client):
        client.base = 'http://' + docker('port', name, '8080/tcp').splitlines()[0]
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            assert state()['Running'], 'Product exited during restart'
            try:
                client.expect('/api/v1/health')
                client.expect(PREFIX + 'api', 401)
                return
            except (OSError, AssertionError):
                time.sleep(.2)
        raise AssertionError('Product readiness timed out')

    created = False
    owned_volumes = []
    try:
        command = ['run', '--detach', '--name', name, '-p', '127.0.0.1::8080',
                   '-e', 'WEBOBS_LISTEN_ADDRESS=0.0.0.0', '-e', 'WEBOBS_ALLOW_INSECURE_REMOTE=true',
                   '-e', 'WEBOBS_GO2RTC_ENABLED=true', '-e', 'WEBOBS_WEBRTC_ENABLED=true',
                   '-e', 'WEBOBS_COMPOSITE_ENABLED=' + ('true' if options.composite else 'false'),
                   '-e', 'WEBOBS_RENDERER=software', '-e', 'WEBOBS_NVR_ENABLED=true',
                   '-e', 'WEBOBS_CLUSTER_ENABLED=true', '-e', 'WEBOBS_COMPAT_BASIC_AUTH=false',
                   '-e', 'WEBOBS_SESSION_COOKIE_SECURE=false']
        if not options.expect_crash_failure:
            # Match the entrypoint's actual PID, then preserve the old FIFO
            # throughout every restart. Also leave an unrelated regular file.
            command += ['--entrypoint', '/usr/bin/tini', options.image, '--', 'sh', '-c',
                        'p=/tmp/webobs-go2rtc-log.$$; [ -e "$p" ] || mkfifo "$p"; '
                        'printf keep >/tmp/webobs-unrelated; exec /opt/webobs/entrypoint.sh']
        else:
            command.append(options.image)
        docker(*command)
        created = True
        anonymous = Client('')
        ready(anonymous)
        admin = Client(anonymous.base)
        account = {'username': 'restart-admin', 'password': secrets.token_hex(24)}
        admin.expect('/api/v1/auth/setup', 201, body=account, method='POST')
        admin.expect('/api/v1/auth/login', body=account, method='POST')
        config = 'streams:\n  synthetic: "ffmpeg:virtual?video=testsrc2&size=160x90#video=h264"\n'
        admin.expect(PREFIX + 'api/config', body=config, method='POST')
        admin.expect(PREFIX + 'api/restart', 202, method='POST')
        for _ in range(40):
            try:
                assert b'synthetic' in admin.expect(PREFIX + 'api/streams')
                break
            except (OSError, AssertionError):
                time.sleep(.25)
        else:
            raise AssertionError('Save & Restart did not recover')
        websocket_media(admin)
        docker('exec', name, 'python3', '-c',
               'from pathlib import Path;Path("/recordings/restart-keep").write_bytes(b"keep-recording");'
               'Path("/config/webobs/restart-keep").write_bytes(b"keep-private-config")')
        fingerprint = docker('exec', name, 'python3', '-c',
               'import hashlib,json;from pathlib import Path;'
               'print(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in '
               '[Path("/config/webobs/go2rtc/go2rtc.yaml"),Path("/config/webobs/restart-keep"),'
               'Path("/recordings/restart-keep")]}))')

        def runtime_directory():
            return docker('exec', name, 'python3', '-c',
                   'import stat;from pathlib import Path;'
                   'dirs=list(Path("/dev/shm").glob("webobs-runtime.*"));assert len(dirs)==1;d=dirs[0];'
                   'assert d.stat().st_mode&0o777==0o700;'
                   'pipes=list(d.glob("*.log"));assert len(pipes)>=7;'
                   'assert all(stat.S_ISFIFO(p.stat().st_mode) and p.stat().st_mode&0o777==0o600 for p in pipes);'
                   'assert Path("/tmp/webobs-unrelated").read_text()=="keep";print(d.name)')

        previous = '' if options.expect_crash_failure else runtime_directory()
        if options.expect_crash_failure:
            docker('kill', '--signal', 'KILL', name)
            docker('start', name)
            deadline = time.monotonic() + 15
            while state()['Running'] and time.monotonic() < deadline:
                time.sleep(.1)
            logs = docker('logs', name)
            assert not state()['Running']
            assert 'mkfifo:' in logs and 'File exists' in logs and 'already-complete' in logs
            print('REPRODUCED: unmodified v3.5 reaches login/media, SIGKILL leaves its FIFO, restart fails with already-complete + File exists', flush=True)
            return

        for phase in ['normal', 'forced', 'normal', 'forced', 'normal', 'forced']:
            if phase == 'normal':
                docker('stop', '--time', '20', name)
                assert state()['ExitCode'] == 0, 'Normal shutdown was not clean'
            else:
                docker('kill', '--signal', 'KILL', name)
                assert state()['ExitCode'] == 137
            docker('start', name)
            ready(anonymous)
            admin.base = anonymous.base
            # The existing signed session must work; then verify account login.
            assert admin.expect(PREFIX + 'api/config').decode() == config
            admin.expect('/api/v1/auth/login', body=account, method='POST')
            current = runtime_directory()
            assert current != previous, 'Runtime resources reused a prior startup path'
            previous = current
            actual = docker('exec', name, 'python3', '-c',
                   'import hashlib,json;from pathlib import Path;'
                   'print(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in '
                   '[Path("/config/webobs/go2rtc/go2rtc.yaml"),Path("/config/webobs/restart-keep"),'
                   'Path("/recordings/restart-keep")]}))')
            assert json.loads(actual) == json.loads(fingerprint), 'Persistent file changed'
            docker('exec', name, 'python3', '-c',
                   'import sqlite3;from pathlib import Path;'
                   'dbs=list(Path("/config/webobs").glob("*.sqlite3"));assert dbs;'
                   'assert all(sqlite3.connect(p).execute("pragma integrity_check").fetchone()[0]=="ok" for p in dbs)')
            websocket_media(admin)
            print(phase + ' restart: session/account, unchanged private config and recording, SQLite integrity, authenticated MSE playback passed', flush=True)
        # A service failure must stop the product, then allow the same container
        # to restart normally. Never kill a service belonging to another container.
        docker('exec', name, 'python3', '-c',
               'import os,signal\nfrom pathlib import Path\npids=[]\n'
               'for p in Path("/proc").iterdir():\n'
               ' if not p.name.isdigit() or p.name==str(os.getpid()):continue\n'
               ' try:args=(p/"cmdline").read_bytes().split(bytes([0]))\n'
               ' except (FileNotFoundError,PermissionError):continue\n'
               ' if b"/opt/webobs/bin/webobs-camera-registry" in args:pids.append(int(p.name))\n'
               'assert len(pids)==1\nos.kill(pids[0],signal.SIGKILL)')
        deadline = time.monotonic() + 20
        while state()['Running'] and time.monotonic() < deadline:
            time.sleep(.1)
        assert not state()['Running'] and state()['ExitCode'] == 3
        docker('start', name)
        ready(anonymous)
        admin.base = anonymous.base
        assert admin.expect(PREFIX + 'api/config').decode() == config
        websocket_media(admin)
        docker('stop', '--time', '20', name)
        assert state()['ExitCode'] == 0
        # Exercise the documented hotfix/upgrade recreation path as well.
        mounts = json.loads(docker('inspect', '--format', '{{json .Mounts}}', name))
        assert {m['Destination'] for m in mounts} == {'/config/webobs', '/recordings'}
        assert all(m['Type'] == 'volume' for m in mounts)
        owned_volumes = [m['Name'] for m in mounts]  # Created only by this random test container.
        docker('rm', name)
        created = False
        insert = command.index('--entrypoint')
        mount_args = []
        for mount in mounts:
            mount_args += ['--volume', mount['Name'] + ':' + mount['Destination']]
        command[insert:insert] = mount_args
        docker(*command)
        created = True
        ready(anonymous)
        admin.base = anonymous.base
        assert admin.expect(PREFIX + 'api/config').decode() == config
        admin.expect('/api/v1/auth/login', body=account, method='POST')
        websocket_media(admin)
        docker('stop', '--time', '20', name)
        assert state()['ExitCode'] == 0, 'Final shutdown exit: ' + str(state()['ExitCode'])
        print('PASS: service-crash recovery, recreation preserving the original volumes/account/config/media and normal shutdown; synthetic media, no physical power-cut qualification', flush=True)
    except BaseException:
        if created and options.artifacts:
            artifacts = Path(options.artifacts)
            artifacts.mkdir(parents=True, exist_ok=True)
            (artifacts / 'failed-container.log').write_text(docker('logs', name), encoding='utf-8')
            (artifacts / 'failed-state.json').write_text(json.dumps(state()), encoding='utf-8')
        raise
    finally:
        if created:
            docker('rm', '--force', '--volumes', name)
        for volume in owned_volumes:
            docker('volume', 'rm', volume)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True)
    parser.add_argument('--docker', default='docker')
    parser.add_argument('--expect-crash-failure', action='store_true', help='Reproduce the unmodified v3.5 failure')
    parser.add_argument('--composite', action='store_true', help='Also exercise software OBS/Xvfb restart')
    parser.add_argument('--artifacts', help='Private failure evidence directory; never commit it')
    run(parser.parse_args())
