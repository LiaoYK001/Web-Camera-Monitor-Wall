#!/usr/bin/env python3
"""Supervise the complete upstream binary; keep its writable config private."""
import sys as _runtime_sys
from pathlib import Path as _RuntimePath
_runtime_sys.path.insert(0, str(_RuntimePath(__file__).resolve().parents[1]))
from runtime_support import service_port, service_http, service_rtsp, install_owner_shutdown, serve_owned, STOP, sync_directory

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import urllib.request

stopping = threading.Event()
child = None
# The authenticated product proxy maps POST api/restart to api/exit?code=75.
RESTART_EXIT_CODE = 75


def prepare_config(path: Path, template: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError('go2rtc configuration must not be a symbolic link')
    path.parent.chmod(0o700)
    try:
        with path.open('x', encoding='utf-8') as output:
            output.write(template.read_text(encoding='utf-8'))
    except FileExistsError:
        pass  # Upgrades and restarts must preserve the user's configuration.
    path.chmod(0o600)


def runtime_overlay(static_dir: Path) -> str:
    # A saved YAML edit must not remove authentication by opening a management
    # port, or change the fixed route expected by the product proxy.
    overlay = {
        'api': {'listen': f'127.0.0.1:{service_port(11984)}', 'base_path': '/api/v1/go2rtc',
                'static_dir': str(static_dir), 'username': '', 'password': '',
                'origin': '', 'tls_listen': '', 'unix_listen': ''},
        'rtsp': {'listen': f'127.0.0.1:{service_port(18554)}'},
        'webrtc': {'listen': f"{os.environ.get('WEBOBS_GO2RTC_WEBRTC_BIND', '127.0.0.1' if os.name == 'nt' else '')}:{service_port(18555)}"},
    }
    hosts = os.environ.get('WEBOBS_GO2RTC_WEBRTC_HOSTS', '')
    if hosts:
        overlay['webrtc']['candidates'] = [f'{host.strip()}:{service_port(18555)}' for host in hosts.split(',') if host.strip()]
    return json.dumps(overlay)


def stop_child() -> None:
    if child is None:
        return
    try:
        if os.name == 'nt':
            # Each generation owns a nested Job, including any FFmpeg children.
            # Closing/killing its host also cleans descendants after api/exit.
            if child.poll() is None and child.stdin is not None:
                child.stdin.write(b'shutdown\n')
                child.stdin.flush()
        else: os.killpg(child.pid, signal.SIGTERM)
    except OSError:
        if child.poll() is None:
            raise


def shutdown(*_args) -> None:
    stopping.set()
    stop_child()


def supervise(binary: Path, config: Path, template: Path, static_dir: Path) -> int:
    global child
    prepare_config(config, template)
    if not (static_dir / 'index.html').is_file():
        raise ValueError('go2rtc WebUI assets are missing; run pnpm go2rtc:ui in web/')
    # Linux uses a process group; Windows descendants belong to the desktop Job.
    os.umask(0o077)
    attempts = 0
    while not stopping.is_set():
        command = [str(binary), '-config', str(config), '-config', runtime_overlay(static_dir)]
        if os.name == 'nt':
            command = [str(binary.with_name('webobs-job.exe')), '--console', *command]
        child = subprocess.Popen(command, cwd=config.parent,
                                 stdin=subprocess.PIPE if os.name == 'nt' else subprocess.DEVNULL,
                                 start_new_session=os.name != 'nt',
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        ready = False
        for _ in range(100):
            if stopping.is_set() or child.poll() is not None:
                break
            try:
                with urllib.request.urlopen(service_http(11984, '/api/v1/go2rtc/api'), timeout=.3) as reply:
                    ready = reply.status == 200
            except (OSError, ValueError):
                pass
            if ready:
                break
            stopping.wait(.1)
        if ready:
            print('go2rtc ready', flush=True)
        else:
            stop_child()
        while ready and child.poll() is None and not stopping.wait(.2):
            pass
        stop_child()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                if os.name == 'nt': child.kill()
                else: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
        if child.stdin is not None:
            child.stdin.close()
        if stopping.is_set():
            return 0
        if child.returncode == RESTART_EXIT_CODE:
            print('go2rtc configuration restart requested', flush=True)
            continue
        # Deliberate reloads do not consume or reset the bounded crash budget.
        # The pinned binary only exits with 75 when api/exit explicitly asks it
        # to. A fast Save can arrive before our readiness poll observes it.
        attempts += 1
        if attempts >= 5:
            print('go2rtc repeatedly exited; supervisor stopped', file=sys.stderr, flush=True)
            return 1
        print('go2rtc exited; restarting', file=sys.stderr, flush=True)
        stopping.wait(min(2 ** attempts, 10))
    return 0


if __name__ == '__main__':
    install_owner_shutdown(shutdown)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    try:
        sys.exit(supervise(
            Path(os.environ.get('WEBOBS_GO2RTC_BINARY', '/opt/webobs/bin/go2rtc')).resolve(),
            Path(os.environ.get('WEBOBS_GO2RTC_CONFIG', '/config/webobs/go2rtc/go2rtc.yaml')).absolute(),
            Path(os.environ.get('WEBOBS_GO2RTC_TEMPLATE', '/opt/webobs/etc/go2rtc.yaml')),
            Path(os.environ.get('WEBOBS_GO2RTC_WEB_ROOT', '/opt/webobs/go2rtc-www')).resolve()))
    except (OSError, ValueError):
        # Do not publish the contents of private paths/configuration in logs.
        print('go2rtc startup failed; check binary, assets and private configuration', file=sys.stderr)
        sys.exit(1)
