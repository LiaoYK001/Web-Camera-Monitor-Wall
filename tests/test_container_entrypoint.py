#!/usr/bin/env python3
"""Execute the actual shell supervisor with isolated, synthetic service processes."""
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = Path(os.environ.get('WEBOBS_TEST_CONTAINER_ENTRYPOINT', ROOT / 'docker/entrypoint.sh'))


@unittest.skipUnless((ROOT / 'compose.yaml').is_file() and (ROOT / '.env.example').is_file(),
                     'Repository-level defaults check; the image build copies only this test file')
class DeploymentDefaultsTests(unittest.TestCase):
    """Source defaults only; not a container or installed-product qualification.

    The image build runs this module inside the container to exercise the supervisor
    contracts. Deployment defaults live in the repository (compose.yaml/.env.example),
    which the image does not carry, so that part is skipped there instead of failing.
    """

    def test_copied_environment_keeps_account_control_plane_enabled(self):
        example = dict(re.findall(r'^([A-Z_]+)=([^\r\n]*)$',
                                  (ROOT / '.env.example').read_text(encoding='utf-8'), re.MULTILINE))
        self.assertEqual(example.get('WEBOBS_CLUSTER_ENABLED'), 'true',
                         'Copying .env.example must not override authenticated Compose with false')
        self.assertEqual(example.get('WEBOBS_BIND_ADDRESS'), '127.0.0.1')

    def test_base_compose_keeps_authenticated_loopback_defaults(self):
        compose = (ROOT / 'compose.yaml').read_text(encoding='utf-8')
        self.assertIn('WEBOBS_CLUSTER_ENABLED: ${WEBOBS_CLUSTER_ENABLED:-true}', compose)
        self.assertIn('WEBOBS_COMPAT_BASIC_AUTH: "false"', compose)
        self.assertIn('WEBOBS_COMPOSITE_ENABLED: "false"', compose)
        for line in compose.split('    ports:', 1)[1].split('    stop_grace_period:', 1)[0].splitlines():
            if line.strip().startswith('-'):
                self.assertIn('${WEBOBS_BIND_ADDRESS:-127.0.0.1}', line)


@unittest.skipUnless(os.name == 'posix', 'Linux shell/process lifecycle contracts')
class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='webobs-entrypoint-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ('opt/obs/bin', 'opt/webobs/bin', 'config/webobs', 'tmp', 'shm', 'tools'):
            (self.root / directory).mkdir(parents=True)
        text = ENTRYPOINT.read_text()
        paths = {'/opt/': 'opt', '/config/': 'config', '/tmp/': 'tmp', '/dev/shm/': 'shm'}
        text = re.sub(r'/opt/|/config/|/tmp/|/dev/shm/',
                      lambda match: str(self.root / paths[match[0]]) + '/', text)
        self.script = self.root / 'entrypoint.sh'
        self.script.write_text(text)
        self.env = {**os.environ, 'PATH': str(self.root / 'tools') + ':' + os.environ['PATH'],
                    'FIXTURE_ROOT': str(self.root), 'WEBOBS_GO2RTC_ENABLED': 'true',
                    'WEBOBS_WEBRTC_ENABLED': 'false', 'WEBOBS_CAMERA_REGISTRY_ENABLED': 'false',
                    'WEBOBS_V2_CLIENT_CONTROL_ENABLED': 'false', 'WEBOBS_EVENTS_ENABLED': 'false',
                    'WEBOBS_CLUSTER_ENABLED': 'false', 'WEBOBS_NVR_ENABLED': 'false',
                    'WEBOBS_ARCHIVE_ENABLED': 'false', 'WEBOBS_ENCRYPTED_BACKUP_ENABLED': 'false',
                    'WEBOBS_COMPOSITE_ENABLED': 'false', 'WEBOBS_TLS_ENABLED': 'false',
                    'WEBOBS_OUTPUT': '', 'WEBOBS_RTSP_URL': '', 'WEBOBS_NODE_ROLE': 'standalone'}
        self.write('opt/webobs/bin/webobs-preupgrade-guard', '''import os,sys
from pathlib import Path
root=Path(os.environ['FIXTURE_ROOT']); config=root/'config/webobs'
pending=config/'.v2-m7-upgrade-pending.json'
if sys.argv[1]=='prepare':
 pending.write_text('{}')
 # A stale legacy path with the *actual* entrypoint PID reproduces the bug.
 fifo=root/'tmp'/('webobs-go2rtc-log.'+str(os.getppid()))
 if not fifo.exists() and not fifo.is_symlink():os.mkfifo(fifo)
elif sys.argv[1] in ('commit','rollback'):
 pending.unlink(missing_ok=True)
 (root/sys.argv[1]).touch()
''')
        service = '''#!/usr/bin/env python3
import os,signal,time
from pathlib import Path
root=Path(os.environ['FIXTURE_ROOT']); role=Path(__file__).name
signal.signal(signal.SIGTERM, (lambda *_:None) if os.getenv('IGNORE_TERM')==role else (lambda *_:exit(0)))
(root/(role+'.pid')).write_text(str(os.getpid()))
while True:time.sleep(.05)
'''
        self.write('opt/obs/bin/webobsd', service)
        self.write('opt/webobs/bin/webobs-go2rtc', service)
        self.write('opt/obs/bin/webobs-log-filter', '#!/bin/sh\nexec cat\n')
        self.write('tools/curl', '#!/bin/sh\n[ "${HOLD_READY:-false}" = false ]\n')

    def write(self, name, text):
        path = self.root / name
        path.write_text(text)
        path.chmod(0o755)

    def launch(self, **overrides):
        (self.root / 'commit').unlink(missing_ok=True)
        process = subprocess.Popen(['sh', str(self.script)], env={**self.env, **overrides},
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        def cleanup():
            # Our private process group includes only this synthetic fixture.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate(timeout=3)
        self.addCleanup(cleanup)
        return process

    def ready(self, process, role='webobsd'):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if (self.root / (role + '.pid')).exists() and (role != 'webobsd' or (self.root / 'commit').exists()):
                return
            self.assertIsNone(process.poll(), 'fixture exited before the requested service started')
            time.sleep(.02)
        self.fail('fixture startup timed out')

    def assert_stopped(self):
        self.assertFalse(list((self.root / 'shm').iterdir()), 'temporary runtime leaked')
        self.assertFalse((self.root / 'config/obs/plugin_config/obs-browser').exists())
        for path in self.root.glob('*.pid'):
            with self.assertRaises(ProcessLookupError, msg='owned service was left running'):
                os.kill(int(path.read_text()), 0)

    def test_stale_fifo_private_modes_normal_stop_and_restart(self):
        sentinel = self.root / 'config/webobs/keep'
        sentinel.write_text('persistent user data')
        for _ in range(2):
            process = self.launch()
            self.ready(process)
            directory, = (self.root / 'shm').iterdir()
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual((directory / 'go2rtc.log').stat().st_mode & 0o777, 0o600)
            self.assertTrue((self.root / 'tmp' / ('webobs-go2rtc-log.' + str(process.pid))).is_fifo())
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0)
            self.assert_stopped()
            self.assertEqual(sentinel.read_text(), 'persistent user data')
            for path in self.root.glob('*.pid'):
                path.unlink()

    def test_startup_failure_stops_started_services_and_rolls_back(self):
        # Fail a later service's FIFO creation after go2rtc has already started.
        self.env['WEBOBS_WEBRTC_ENABLED'] = 'true'
        self.env['WEBOBS_MEDIAMTX_CONFIG'] = str(self.root / 'config/webobs/keep')
        (self.root / 'config/webobs/keep').touch()
        self.write('tools/mkfifo', '''#!/bin/sh
case "$*" in *mediamtx*) exit 27;; esac
exec /usr/bin/mkfifo "$@"
''')
        process = self.launch()
        process.communicate(timeout=6)
        self.assertEqual(process.returncode, 27)
        self.assertTrue((self.root / 'rollback').exists())
        self.assert_stopped()

    def test_reader_that_never_reaches_eof_is_stopped(self):
        self.write('opt/obs/bin/webobs-log-filter', '''#!/bin/sh
echo $$ >"$FIXTURE_ROOT/filter.pid"
exec sleep 600
''')
        process = self.launch()
        self.ready(process)
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=6)
        self.assertEqual(process.returncode, 0)
        self.assert_stopped()

    def test_repeated_stop_requests_forward_one_core_signal(self):
        self.write('opt/obs/bin/webobsd', '''#!/usr/bin/env python3
import os,signal,time
from pathlib import Path
root=Path(os.environ['FIXTURE_ROOT']); count=root/'core-signals'
def stop(*_):
 n=int(count.read_text())+1 if count.exists() else 1
 count.write_text(str(n))
 if n>1:exit(143)
 time.sleep(.2)
 exit(0)
signal.signal(signal.SIGTERM,stop)
(root/'webobsd.pid').write_text(str(os.getpid()))
while True:time.sleep(.05)
''')
        process = self.launch()
        self.ready(process)
        process.send_signal(signal.SIGTERM)
        time.sleep(.03)
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0)
        self.assertEqual((self.root / 'core-signals').read_text(), '1')
        self.assert_stopped()

    def test_unavailable_runtime_space_fails_before_service_start(self):
        self.write('tools/mktemp', '#!/bin/sh\nexit 1\n')
        process = self.launch()
        _, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 3)
        self.assertIn(b'Cannot create private runtime directory', stderr)
        self.assertFalse(list(self.root.glob('*.pid')))
        self.assertTrue((self.root / 'rollback').exists())
        self.assert_stopped()

    def test_signal_during_startup_cancels_remaining_services(self):
        process = self.launch(HOLD_READY='true')
        self.ready(process, 'webobs-go2rtc')
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=5)
        self.assertEqual(process.returncode, 143)
        self.assertFalse((self.root / 'webobsd.pid').exists())
        self.assertTrue((self.root / 'rollback').exists())
        self.assert_stopped()

    def test_stop_after_core_launch_before_migration_commit_is_intentional(self):
        process = self.launch()
        deadline = time.monotonic() + 5
        while not (self.root / 'webobsd.pid').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue((self.root / 'webobsd.pid').exists())
        self.assertFalse((self.root / 'commit').exists())
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0)
        self.assertTrue((self.root / 'rollback').exists())
        self.assert_stopped()

    def test_nonresponsive_core_has_bounded_shutdown(self):
        process = self.launch(IGNORE_TERM='webobsd')
        self.ready(process)
        start = time.monotonic()
        process.send_signal(signal.SIGTERM)
        _, stderr = process.communicate(timeout=18)
        self.assertLess(time.monotonic() - start, 18)
        self.assertEqual(process.returncode, 3)
        self.assertIn(b'forcing termination', stderr)
        self.assert_stopped()

    def test_nonresponsive_service_has_bounded_shutdown(self):
        process = self.launch(IGNORE_TERM='webobs-go2rtc')
        self.ready(process)
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=10)
        self.assertEqual(process.returncode, 3)
        self.assert_stopped()

    def test_forced_startup_shutdown_defers_pending_rollback(self):
        process = self.launch(IGNORE_TERM='webobs-go2rtc', HOLD_READY='true')
        self.ready(process, 'webobs-go2rtc')
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=10)
        self.assertEqual(process.returncode, 3)
        self.assertTrue((self.root / 'config/webobs/.v2-m7-upgrade-pending.json').exists())
        self.assertFalse((self.root / 'rollback').exists(), 'rollback raced a forced service shutdown')
        self.assert_stopped()

    def test_stale_symlink_is_ignored_without_touching_target(self):
        target = self.root / 'config/webobs/keep'
        target.write_text('keep')
        process = self.launch(HOLD_READY='true')
        self.ready(process, 'webobs-go2rtc')
        legacy = self.root / 'tmp' / ('webobs-go2rtc-log.' + str(process.pid))
        legacy.unlink()
        legacy.symlink_to(target)
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=5)
        self.assertEqual(target.read_text(), 'keep')
        self.assertTrue(legacy.is_symlink())
        self.assert_stopped()


if __name__ == '__main__':
    unittest.main()
