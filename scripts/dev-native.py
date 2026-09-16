#!/usr/bin/env python3
"""Native development supervisor. No Docker, root-owned project files or global runtime paths."""
import argparse
import ctypes.util
import fcntl
import hashlib
import os
from pathlib import Path
import platform
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path.home() / '.cache/webobs-dev' / hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
PACKAGES = "build-essential cmake ninja-build pkg-config git curl ca-certificates extra-cmake-modules libavcodec-dev libavformat-dev libavutil-dev libswresample-dev libswscale-dev libboost-dev libcurl4-openssl-dev libjansson-dev libssl-dev libsqlite3-dev libsimde-dev uthash-dev uuid-dev zlib1g-dev libx11-dev libx11-xcb-dev libxcb-randr0-dev libxcb-shm0-dev libxcb-xfixes0-dev libxcb-xinerama0-dev libxcomposite-dev libxinerama-dev libxkbcommon-dev libgl1-mesa-dev libegl1-mesa-dev libglvnd-dev libwayland-dev libdrm-dev libgbm-dev libglib2.0-dev libxcb-xinput-dev libxkbcommon-x11-dev libsodium23 libx264-dev libavfilter-dev libavdevice-dev libxcb-composite0-dev libva-dev libpci-dev libudev-dev libfreetype-dev libfontconfig1-dev ffmpeg python3".split()
processes = []
services = []
handles = []
stopping = threading.Event()

def say(message):
    print(f"[native] {message}", flush=True)

def shutdown(*_):
    stopping.set()
    for child in reversed(processes):
        if child.poll() is None:
            try: os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError: pass

def command(args, log=None, env=None):
    if stopping.is_set(): raise RuntimeError('启动已取消')
    stream = open(log, 'a') if log else None
    if stream: handles.append(stream)
    child = subprocess.Popen([str(arg) for arg in args], cwd=ROOT, env=env,
                             stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT if stream else None,
                             start_new_session=True)
    processes.append(child)
    code = child.wait()
    if code:
        if stopping.is_set(): raise InterruptedError()
        if log: print(Path(log).read_text(errors='replace')[-7000:], flush=True)
        raise RuntimeError(f"命令失败（{code}）：{args[0]}；日志：{log or '终端'}")

def check():
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise RuntimeError('原生后端当前支持 Linux x86_64（建议 Ubuntu 24.04）；Windows 请使用 WSL2 Ubuntu-24.04。')
    missing = [item for item in ['cmake', 'ninja', 'g++', 'pkg-config', 'git', 'curl', 'ffmpeg'] if not shutil.which(item)]
    if not ctypes.util.find_library('sodium'): missing.append('libsodium23')
    if shutil.which('pkg-config'):
        for package in ['libavformat', 'libavutil', 'libswscale', 'libswresample', 'jansson', 'libcurl', 'sqlite3', 'openssl', 'libdrm', 'x11', 'egl']:
            if subprocess.run(['pkg-config', '--exists', package]).returncode: missing.append(package)
    if missing: raise RuntimeError('缺少原生依赖：' + ', '.join(missing) + '。Windows 运行 dev.ps1 -Setup；Ubuntu 运行 bash scripts/dev.sh --setup。')
    version = subprocess.check_output(['cmake', '--version'], text=True).split()[2]
    if tuple(map(int, version.split('.')[:2])) < (3, 28): raise RuntimeError('需要 CMake >= 3.28；推荐 Ubuntu 24.04。')
    say(f'工具检查通过。源码：{ROOT}；原生缓存/数据：{CACHE}')

def ports_free():
    for port in [8080, 8091, 8092, 8093, 8094, 8095, 8190, 8554, 8889, 9997]:
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try: sock.bind(('127.0.0.1', port))
            except OSError: raise RuntimeError(f'后端端口 {port} 已占用。请先停止旧原生服务/本项目容器；脚本不会结束其他进程。')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try: sock.bind(('127.0.0.1', 8189))
        except OSError: raise RuntimeError('UDP 8189 已占用，请停止旧媒体服务。')

def start(name, args, env, health):
    logfile = CACHE / 'logs' / f'{name}.log'
    stream = open(logfile, 'a'); handles.append(stream)
    child = subprocess.Popen([str(arg) for arg in args], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                             stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    processes.append(child)
    services.append(child)
    for _ in range(100):
        if stopping.is_set() or child.poll() is not None: break
        try:
            with urllib.request.urlopen(health, timeout=1) as response:
                if response.status == 200:
                    say(f'[OK] {name} | 日志：{logfile}'); return
        except Exception: time.sleep(.1)
    print(logfile.read_text(errors='replace')[-4000:], flush=True)
    raise RuntimeError(f'{name} 未就绪；请查看 {logfile}')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--install-deps', action='store_true')
    # Explicit opt-in: without it the lightweight Direct-only native default is unchanged.
    parser.add_argument('--composite', action='store_true')
    parser.add_argument('--frontend-port', type=int, default=5173)
    args = parser.parse_args()
    if args.install_deps:
        release = platform.freedesktop_os_release()
        if release.get('ID') != 'ubuntu' or release.get('VERSION_ID') != '24.04':
            raise RuntimeError('自动安装仅支持 Ubuntu 24.04；其他 Linux 请按 docs/development.md 安装同等依赖。')
        prefix = [] if os.geteuid() == 0 else ['sudo']
        # Inherit terminal only for the explicit system dependency installation.
        subprocess.run([*prefix, 'apt-get', 'update'], check=True)
        subprocess.run([*prefix, 'apt-get', 'install', '-y', '--no-install-recommends', *PACKAGES], check=True)
        return
    if os.environ.get('WSL_DISTRO_NAME'):
        # CMake otherwise probes Windows PATH entries over slow WSL 9P mounts.
        os.environ['PATH'] = ':'.join(part for part in os.environ.get('PATH', '').split(':') if not part.startswith('/mnt/'))
    check()
    if args.composite:
        say('Composite 模式已启用：将构建 OBS 图形/媒体输入/编码与 WHIP 输出模块（首次较久）。')
    if args.check:
        if args.composite:
            say('Composite 依赖检查：需要 libx264/libjansson/libcurl 等；本机 GPU 能力由 scripts/hardware-probe.py 探测。')
        return
    os.umask(0o077)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    lock = open(CACHE.parent / 'native.lock', 'a')
    handles.append(lock)
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: raise RuntimeError('已有原生开发会话正在编译或运行，请先停止原会话。')
    ports_free()
    signal.signal(signal.SIGTERM, shutdown); signal.signal(signal.SIGINT, shutdown)
    def watch_parent():
        while os.read(sys.stdin.fileno(), 4096):
            pass
        shutdown()
    threading.Thread(target=watch_parent, daemon=True).start()
    for name in ['logs', 'data', 'data/keys', 'data/camera-secrets', 'data/notification-secrets', 'recordings', 'bin']:
        (CACHE / name).mkdir(parents=True, exist_ok=True)
    buildlog = CACHE / 'logs/build.log'
    obs = ROOT / 'obs/obs-studio'
    if not (obs / 'CMakeLists.txt').exists():
        say('[1/4] 初始化固定的 OBS 子模块')
        command(['git', 'submodule', 'update', '--init', '--recursive'], buildlog)
    # The build cache is keyed by feature combination so a Direct-only libobs
    # cache is never reused for the Composite plugin set.
    feature = '-composite' if args.composite else ''
    project_source = ROOT
    obs_build = CACHE / ('obs' + feature)
    core_build = CACHE / ('core' + feature)
    if os.environ.get('WSL_DISTRO_NAME') and str(ROOT).startswith('/mnt/'):
        # Compile from Linux storage while the developer continues editing Windows files.
        revision = subprocess.check_output(['git', '-C', str(obs), 'rev-parse', 'HEAD'], text=True).strip()
        local_obs = CACHE / ('obs-source-' + revision)
        ready = local_obs / '.webobs-extracted'
        if not ready.exists():
            say('缓存固定 OBS 源码到 Linux 文件系统，避免 WSL/NTFS 大量小文件访问。')
            archive = CACHE / 'obs-source.tar'
            command(['git', '-C', obs, 'archive', '--format=tar', '--output', archive, revision], buildlog)
            local_obs.mkdir(exist_ok=True)
            command(['tar', '-xf', archive, '-C', local_obs], buildlog)
            ready.touch()
            archive.unlink()
        if args.composite:
            # git archive excludes submodule contents, but the OBS plugin set
            # (for example check_obs_browser()) requires them, so copy the
            # checked-out submodule trees into the Linux-storage source.
            submodules = subprocess.check_output(
                ['git', '-C', str(ROOT / 'obs/obs-studio'), 'submodule', 'status', '--recursive'],
                text=True).splitlines()
            for line in submodules:
                parts = line.split()
                if len(parts) < 2: continue
                relative = parts[1]
                source = ROOT / 'obs/obs-studio' / relative
                if not source.is_dir(): continue
                destination = local_obs / relative
                if destination.exists(): shutil.rmtree(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, destination, symlinks=True)
        obs = local_obs
        obs_build = CACHE / ('obs-build-' + revision + feature)
        project_source = CACHE / 'source'
        project_source.mkdir(exist_ok=True)
        files = [ROOT / 'CMakeLists.txt', *(ROOT / 'core').rglob('*')]
        expected = set()
        for source in files:
            if not source.is_file(): continue
            relative = source.relative_to(ROOT)
            expected.add(relative)
            destination = project_source / relative
            content = source.read_bytes()
            if not destination.exists() or destination.read_bytes() != content:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
        for destination in project_source.rglob('*'):
            if destination.is_file() and destination.relative_to(project_source) not in expected:
                destination.unlink()
        core_build = CACHE / ('core-local' + feature)
    if os.environ.get('WEBOBS_DEV_OBS_SOURCE'):
        obs = Path(os.environ['WEBOBS_DEV_OBS_SOURCE']).resolve()
        obs_build = CACHE / ('obs-custom-' + hashlib.sha256(str(obs).encode()).hexdigest()[:12] + feature)
    jobs = str(min(os.cpu_count() or 2, 4))
    # obs-webrtc (the Composite WHIP output) needs libdatachannel, which has no
    # Ubuntu apt package, so build it from source into the local prefix.
    local_libs = CACHE / 'libs'
    prefix_flags = []
    if args.composite:
        if not list((local_libs / 'lib').glob('libdatachannel.so*')):
            say('构建 libdatachannel（obs-webrtc/WHIP 必需；Ubuntu 无 apt 包，首次较久）')
            dc_source = CACHE / 'libdatachannel'
            dc_build = CACHE / 'libdatachannel-build'
            if not (dc_source / 'CMakeLists.txt').exists():
                command(['git', 'clone', '--depth', '1', '--recurse-submodules', '--branch', 'v0.22.6',
                         'https://github.com/paullouisageneau/libdatachannel.git', dc_source], buildlog)
            command(['cmake', '-S', dc_source, '-B', dc_build, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
                     '-DNO_EXAMPLES=ON', '-DNO_TESTS=ON', '-DUSE_GNUTLS=OFF',
                     f'-DCMAKE_INSTALL_PREFIX={local_libs}'], buildlog)
            command(['cmake', '--build', dc_build, '--parallel', jobs, '--target', 'install'], buildlog)
        prefix_flags = [f'-DCMAKE_PREFIX_PATH={local_libs}']
    say(f'[1/4] 增量编译 OBS 核心（首次较久，不构建镜像）；日志：{buildlog}')
    # Composite needs the media-input, software-encoder and WHIP-output plugins;
    # the browser/CEF plugin is explicitly excluded so a pure camera scene never
    # depends on it.
    # -DBUILD_BROWSER is not an OBS option; ENABLE_BROWSER is.  SDK-only capture
    # plugins (aja/decklink/vlc/qsv/websocket/vst) are disabled so a pure camera
    # scene does not need their external SDKs.
    plugin_flags = (['-DENABLE_PLUGINS=ON', '-DENABLE_BROWSER=OFF', '-DENABLE_AJA=OFF',
                     '-DENABLE_DECKLINK=OFF', '-DENABLE_VLC=OFF', '-DENABLE_VST=OFF',
                     '-DENABLE_WEBSOCKET=OFF', '-DENABLE_QSV11=OFF', '-DENABLE_NVENC=OFF',
                     '-DENABLE_ALSA=OFF', '-DENABLE_PIPEWIRE=OFF', '-DENABLE_V4L2=OFF',
                     '-DENABLE_NEW_MPEGTS_OUTPUT=OFF', '-DENABLE_SPEEXDSP=OFF', '-DENABLE_RNNOISE=OFF']
                    if args.composite else ['-DENABLE_PLUGINS=OFF'])
    command(['cmake', '-S', obs, '-B', obs_build, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
             '-DOBS_VERSION_OVERRIDE=32.1.2', '-DENABLE_UI=OFF', '-DENABLE_FRONTEND=OFF',
             '-DENABLE_SCRIPTING=OFF', '-DENABLE_WAYLAND=OFF', '-DENABLE_PULSEAUDIO=OFF', *plugin_flags,
             *prefix_flags], buildlog)
    obs_targets = ['libobs', 'obs-ffmpeg', 'obs-x264', 'obs-webrtc'] if args.composite else ['libobs']
    command(['cmake', '--build', obs_build, '--target', *obs_targets, '--parallel', jobs], buildlog)
    if args.composite:
        plugins = [path.name for path in obs_build.rglob('*.so')]
        required = {'obs-ffmpeg': '媒体输入/编码', 'obs-x264': '软件编码', 'obs-webrtc': 'WHIP 输出'}
        missing = [name for name in required if not any(name in plugin for plugin in plugins)]
        if missing:
            raise RuntimeError('Composite 构建不完整，缺少模块：' + ', '.join(missing) +
                               '。纯摄像头场景至少需要 obs-ffmpeg 与 obs-x264；请查看 ' + str(buildlog))
        say('Composite 模块检查通过：' + ', '.join(required))
    say('[2/4] 增量编译项目 C++ 后端')
    command(['cmake', '-S', project_source, '-B', core_build, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Debug',
             f'-DWEBOBS_OBS_BUILD_DIR={obs_build}', f'-DWEBOBS_OBS_SOURCE_DIR={obs}',
             f'-DWEBOBS_OBS_PREFIX={obs_build / "rundir/Release"}', f'-DWEBOBS_WEB_ROOT={ROOT / "web/dist"}'], buildlog)
    command(['cmake', '--build', core_build, '--parallel', jobs], buildlog)
    command(['ctest', '--test-dir', core_build, '--output-on-failure'], buildlog)
    media = CACHE / 'bin/mediamtx'
    if not media.exists():
        say('[3/4] 下载并校验 MediaMTX 1.18.2（仅首次）')
        archive = CACHE / 'mediamtx.tar.gz'
        command(['curl', '--fail', '--location', '--retry', '3', '--retry-all-errors', '--connect-timeout', '20', '--max-time', '180', '-o', archive,
                 'https://github.com/bluenviron/mediamtx/releases/download/v1.18.2/mediamtx_v1.18.2_linux_amd64.tar.gz'], buildlog)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != '73ed27c292e05ceb4990dcb34531f01872dfff5374b7515c45a202e0abf47706':
            raise RuntimeError('MediaMTX 校验失败；未执行下载内容')
        command(['tar', '-xzf', archive, '-C', CACHE / 'bin', 'mediamtx'], buildlog)
    say('[4/4] 启动真实 Python 服务、媒体网关和 C++ API')
    transcoder = CACHE / 'bin/transcode-on-demand'
    transcoder.write_text((ROOT / 'gateway/transcode-on-demand.sh').read_text(), encoding='utf-8')
    transcoder.chmod(0o700)
    data = CACHE / 'data'
    # Runtime hardware probe: separate device/library/encoder/sample results,
    # exported as WEBOBS_NVIDIA_* so the C++ status and the transcoder agree.
    probe_script = ROOT / 'scripts/hardware-probe.py'
    if probe_script.exists():
        try:
            probe_output = subprocess.check_output([sys.executable, str(probe_script), '--env'],
                                                   text=True, timeout=180, cwd=ROOT)
            for line in probe_output.splitlines():
                if '=' in line:
                    name, _, value = line.partition('=')
                    os.environ[name.strip()] = value.strip()
            say('硬件探测完成：' + ' '.join(line for line in probe_output.splitlines()
                                          if line.startswith('WEBOBS_NVIDIA_ENCODE_SUPPORTED')
                                          or line.startswith('WEBOBS_NVIDIA_ACCELERATION')))
        except (subprocess.SubprocessError, OSError) as error:
            say(f'硬件探测失败，按软件回退处理：{error}')
            os.environ['WEBOBS_NVIDIA_ENCODE_SUPPORTED'] = 'false'
            os.environ['WEBOBS_NVIDIA_SAMPLE_PASSED'] = 'false'
    env = dict(os.environ)
    env.update({
        'LD_LIBRARY_PATH': str(obs_build / 'libobs') + ':' + str(obs_build / 'rundir/Release/lib'),
        'WEBOBS_SCENE_FILE': str(data / 'scene.json'), 'WEBOBS_SESSION_DATABASE': str(data / 'auth-sessions.db'),
        'WEBOBS_CAMERA_DATABASE': str(data / 'cameras.db'), 'WEBOBS_EVENT_DATABASE': str(data / 'events.db'),
        'WEBOBS_CLUSTER_DATABASE': str(data / 'cluster.sqlite3'), 'WEBOBS_V2_DATABASE': str(data / 'v2-clients.db'),
        'WEBOBS_V2_SIGNING_KEY': str(data / 'keys/client-grant-signing.key'),
        'WEBOBS_V2_SHARED_SCENES': str(data / 'shared-scenes-v2.json'),
        'WEBOBS_CAMERA_SECRET_ROOT': str(data / 'camera-secrets'), 'WEBOBS_SECRETS_ROOT': str(ROOT / 'secrets'),
        'WEBOBS_NOTIFICATION_SECRET_ROOT': str(data / 'notification-secrets'),
        'WEBOBS_NVR_CONFIG': str(data / 'nvr.json'), 'WEBOBS_NVR_STORAGE': str(CACHE / 'recordings'),
        'WEBOBS_NVR_DATABASE': str(CACHE / 'recordings/catalog.sqlite3'),
        'WEBOBS_CLUSTER_INTERNAL_TOKEN': os.urandom(32).hex(), 'WEBOBS_V2_INTERNAL_TOKEN': os.urandom(32).hex(),
        'WEBOBS_REGISTRATION_ENABLED': 'true', 'WEBOBS_COMPAT_BASIC_AUTH': 'true',
        'WEBOBS_AUTH_USERNAME_FILE': str(ROOT / 'secrets/webobs-dev-username.txt'),
        'WEBOBS_AUTH_PASSWORD_FILE': str(ROOT / 'secrets/webobs-dev-password.txt'),
        'WEBOBS_SESSION_COOKIE_SECURE': 'false', 'WEBOBS_LISTEN_ADDRESS': '127.0.0.1',
        'WEBOBS_HTTP_PORT': '8080', 'WEBOBS_ALLOW_INSECURE_REMOTE': 'false',
        'WEBOBS_WEBRTC_ENABLED': 'true', 'WEBOBS_COMPOSITE_ENABLED': 'true' if args.composite else 'false',
        'WEBOBS_NVR_ENABLED': 'true',
        'WEBOBS_TRANSCODER_PATH': str(transcoder),
        'WEBOBS_CAMERA_REGISTRY_ENABLED': 'true', 'WEBOBS_NODE_ROLE': 'standalone',
        'WEBOBS_CONTROL_ALLOWED_ORIGINS': ','.join(f'http://{host}:{port}' for host in ['127.0.0.1','localhost'] for port in [8080,args.frontend_port]),
        'MTX_WEBRTCLOCALUDPADDRESS': '127.0.0.1:8189',
        # WSL localhost forwarding carries TCP; provide ICE/TCP for Windows browsers.
        'MTX_WEBRTCLOCALTCPADDRESS': '127.0.0.1:8190',
    })
    # Prevent inherited production options from accidentally turning on Composite/recording.
    env.pop('WEBOBS_OUTPUT', None); env.pop('WEBOBS_RTSP_URL', None)
    start('mediamtx', [media, ROOT / 'gateway/mediamtx.yml'], env, 'http://127.0.0.1:9997/v3/config/global/get')
    for name, source, port in [('camera','camera/camera_registry.py',8092), ('events','events/event_service.py',8093),
                               ('clients','v2/client_control_service.py',8094), ('cluster','cluster/cluster_service.py',8095),
                               ('nvr','nvr/nvr_service.py',8091)]:
        start(name, [sys.executable, ROOT / source], env, f'http://127.0.0.1:{port}/health')
    start('core', [core_build / 'webobsd'], env, 'http://127.0.0.1:8080/api/v1/health')
    say(f'账号文件：{ROOT / "secrets"}；数据：{data}（独立于容器数据卷）')
    if args.composite:
        say('原生 Composite 已启用：来源 → OBS 合成 → H.264/Opus → MediaMTX → Program WHEP；启动器分别报告进程存活、引擎就绪与 Program 发布状态。')
    else:
        say('原生 Direct-only 模式：控制台/账号/设备/事件/NVR/Gateway 与按需转码可用；需要本地服务端合成时加 -Composite / --composite 重启。')
    say('WEBOBS_DEV_READY')
    while not stopping.wait(.5):
        for child in services:
            if child.poll() is not None: raise RuntimeError('开发服务异常退出，请查看 logs 目录')
    say('正在停止本次原生服务，保留数据库和编译缓存。')

if __name__ == '__main__':
    status = 0
    try: main()
    except InterruptedError:
        pass
    except Exception as error:
        print(f'[ERROR] {error}', file=sys.stderr, flush=True); status = 1
    finally:
        shutdown()
        for child in processes:
            try: child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try: os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
        for stream in handles: stream.close()
    sys.exit(status)
