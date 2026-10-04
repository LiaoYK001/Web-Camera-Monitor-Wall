#!/usr/bin/env python3
"""On-demand website resolution and private RTSP relay; no shell or saved signed URLs."""
import argparse
import base64
import importlib.metadata
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import signal
import ssl
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import getproxies, proxy_bypass


class SourceError(Exception):
    pass


def web_url(value, schemes=('http', 'https')):
    if not isinstance(value, str) or len(value.encode('utf-8')) > 8192 or re.search(r'[\s\x00-\x1f\x7f]', value):
        raise SourceError('invalid_url: use a single HTTP(S) webpage or live URL')
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in schemes or not parsed.hostname or parsed.username or parsed.password or not parsed.port and parsed.netloc.endswith(':'):
            raise ValueError()
        _ = parsed.port
    except ValueError:
        raise SourceError('invalid_url: use a single HTTP(S) webpage or live URL') from None
    return value


def page_url(encoded):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,2800}', encoded):
        raise SourceError('invalid_page: webpage address is too long or malformed')
    try:
        value = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True).decode('utf-8')
    except (ValueError, UnicodeError):
        raise SourceError('invalid_page: malformed webpage address') from None
    if len(value.encode('utf-8')) > 2048:
        raise SourceError('invalid_page: webpage address exceeds 2048 bytes')
    return web_url(value)


def output_url(value):
    port = os.environ.get('WEBOBS_GO2RTC_RTSP_PORT', '18554')
    if not port.isdecimal() or not 1 <= int(port) <= 65535 or not re.fullmatch(r'rtsp://127\.0\.0\.1:' + str(int(port)) + r'/[a-f0-9]{32}', value):
        raise SourceError('invalid_output: go2rtc loopback publish address required')
    return value


def cookie_file(name):
    if not name:
        return None
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name):
        raise SourceError('invalid_cookies: use a private cookie profile name')
    config = Path(os.environ.get('WEBOBS_GO2RTC_CONFIG', '/config/webobs/go2rtc/go2rtc.yaml'))
    root = config.parent / 'cookies'
    file = root / (name + '.txt')
    if root.is_symlink() or file.is_symlink() or not file.is_file() or file.stat().st_size > 1024 * 1024:
        raise SourceError('cookies_unavailable: place a Netscape cookie file in the private go2rtc cookies directory')
    if os.name != 'nt' and (file.stat().st_mode & 0o077):
        raise SourceError('cookies_permissions: private cookie files require mode 0600')
    return str(file)


def binary(name):
    key = 'WEBOBS_' + name.upper() + '_PATH'
    default = '/opt/webobs/bin/node' if name == 'node' else '/usr/bin/ffmpeg'
    value = Path(os.environ.get(key, default))
    if not value.is_absolute() or not value.is_file():
        raise SourceError('runtime_missing: install the complete WebOBS media runtime')
    return str(value)


def safe_headers(headers):
    # Extractor headers belong to the website; product session credentials never enter this tool.
    if not isinstance(headers, dict) or len(headers) > 32:
        raise SourceError('invalid_headers: website returned unsupported media headers')
    lines = []
    for name, value in headers.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,64}', name) or not isinstance(value, str) or re.search(r'[\x00-\x1f\x7f]', value):
            raise SourceError('invalid_headers: website returned unsafe media headers')
        if name.lower() in ('user-agent', 'referer', 'origin', 'cookie', 'authorization', 'accept'):
            lines.append(f'{name}: {value}\r\n')
    text = ''.join(lines)
    if len(text.encode('utf-8')) > 16384:
        raise SourceError('invalid_headers: website media headers exceed limit')
    return text


def input_proxy(url):
    parsed = urlsplit(url)
    # A private local source must never leave the machine through an inherited proxy.
    try:
        local = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        local = parsed.hostname == 'localhost'
    if local or proxy_bypass(parsed.netloc):
        return ''
    proxies = getproxies()
    value = proxies.get(parsed.scheme) or proxies.get('all') or ''
    if value:
        try:
            proxy = urlsplit(value)
            if len(value) > 2048 or re.search(r'[\s\x00-\x1f\x7f]', value) or proxy.scheme != 'http' or not proxy.hostname or proxy.path not in ('', '/') or proxy.query or proxy.fragment:
                raise ValueError()
            _ = proxy.port
        except ValueError:
            raise SourceError('proxy_unsupported: configure an HTTP CONNECT proxy or a direct media network') from None
    return value


def tls_options():
    # Both packaged TLS backends (GnuTLS / Windows Schannel) verify the URL host.
    # Do not pin verifyhost: HLS segments and redirects may use another CDN host.
    options = ['-tls_verify', '1']
    if os.name != 'nt':
        configured = os.environ.get('SSL_CERT_FILE')
        default = ssl.get_default_verify_paths().cafile
        if configured:
            bundle = Path(configured)
            if not bundle.is_absolute() or not bundle.is_file():
                raise SourceError('tls_trust_unavailable: configure an existing absolute backend CA bundle')
        elif default:
            bundle = Path(default)
        else:
            import certifi
            bundle = Path(certifi.where())
        options += ['-ca_file', str(bundle)]
    return options


class QuietLogger:
    def debug(self, *_): pass
    def info(self, *_): pass
    def warning(self, *_): pass
    def error(self, *_): pass


def resolve_ytdlp(url, height, cookies):
    from yt_dlp import YoutubeDL
    from yt_dlp.globals import plugin_dirs
    plugin_dirs.value = []  # Only the locked built-in extractors are loaded.
    options = dict(quiet=True, no_warnings=True, logger=QuietLogger(), noplaylist=True,
                   skip_download=True, cachedir=False, socket_timeout=15, retries=2,
                   extractor_retries=2, ffmpeg_location=binary('ffmpeg'),
                   js_runtimes={'node': {'path': binary('node')}}, remote_components=set(),
                   cookiefile=cookies, format=f'bv*[height<={height}][vcodec^=avc1]+ba[acodec^=mp4a]/b[height<={height}][vcodec^=avc1]/bv*[height<={height}]+ba/b[height<={height}]/b')
    try:
        with YoutubeDL(options) as extractor:
            info = extractor.extract_info(url, download=False)
            if not info or info.get('_type') in ('playlist', 'multi_video'):
                raise SourceError('single_video_required: choose one video or live broadcast')
            formats = info.get('requested_formats') or [info]
            if not 1 <= len(formats) <= 2:
                raise SourceError('unsupported_media: choose a single video or live broadcast')
            return [dict(url=web_url(item.get('url'), ('http', 'https', 'rtmp', 'rtmps')),
                         headers=item.get('http_headers') or {}, video=item.get('vcodec'), audio=item.get('acodec')) for item in formats]
    except SourceError:
        raise
    except Exception:
        raise SourceError('website_resolution_failed: check the webpage, network, private cookies and extractor version; DRM video is unsupported') from None


def resolve_streamlink(url, height, cookies):
    from streamlink import Streamlink
    import http.cookiejar
    session = Streamlink()
    logger = logging.getLogger('streamlink'); logger.addHandler(logging.NullHandler()); logger.propagate = False
    session.set_option('http-timeout', 15)
    session.set_option('stream-timeout', 15)
    if cookies:
        jar = http.cookiejar.MozillaCookieJar(cookies)
        jar.load(ignore_discard=True, ignore_expires=False)
        session.http.cookies.update(jar)
    try:
        streams = session.streams(url)
        choices = [(int(match[1]), name) for name in streams if (match := re.match(r'^(\d{3,4})p', name)) and int(match[1]) <= height]
        name = max(choices)[1] if choices else 'best'
        if name not in streams:
            raise SourceError('live_unavailable: check whether the broadcast is live, or try yt-dlp')
        stream = streams[name]
        media_url = web_url(stream.to_url())
        request = session.http.prepare_new_request(method='GET', url=media_url, headers=getattr(stream, 'args', {}).get('headers') or {})
        return [dict(url=media_url, headers=dict(request.headers), video=None, audio=None)]
    except SourceError:
        raise
    except Exception:
        raise SourceError('live_resolution_failed: check the broadcast, network and private cookies, or try yt-dlp') from None
    finally:
        session.http.close()


def ffmpeg_command(inputs, output, mode, height):
    command = [binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error']
    for item in inputs:
        command += ['-rw_timeout', '15000000', '-protocol_whitelist', 'http,https,httpproxy,tcp,tls,crypto,rtmp,rtmps,data']
        # Also protect HTTPS segments reached from an initial HTTP playlist.
        command += tls_options()
        if urlsplit(item['url']).scheme in ('http', 'https'):
            # FFmpeg does not use uppercase HTTPS_PROXY like the Python extractors.
            # Apply the selected proxy per input, including explicit NO_PROXY/local bypass.
            command += ['-http_proxy', input_proxy(item['url'])]
            command += ['-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_on_network_error', '1',
                        '-reconnect_on_http_error', '429,503', '-reconnect_delay_max', '3']
        headers = safe_headers(item['headers'])
        if headers:
            command += ['-headers', headers]
        command += ['-re', '-i', web_url(item['url'], ('http', 'https', 'rtmp', 'rtmps'))]
    video_index = next((i for i, item in enumerate(inputs) if item['video'] != 'none'), 0)
    audio_index = next((i for i, item in enumerate(inputs) if item['audio'] != 'none'), video_index)
    command += ['-map', f'{video_index}:v:0', '-map', f'{audio_index}:a:0?']
    video = inputs[video_index]['video'] or ''
    audio = inputs[audio_index]['audio'] or ''
    copy_video = mode == 'copy' or mode == 'auto' and video.startswith(('avc1', 'h264'))
    command += ['-c:v', 'copy'] if copy_video else ['-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency', '-pix_fmt', 'yuv420p', '-vf', f'scale=-2:min({height}\\,ih)', '-g', '50']
    command += ['-c:a', 'copy'] if mode == 'copy' or audio.startswith(('mp4a', 'aac')) else ['-c:a', 'aac', '-b:a', '128k']
    return command + ['-f', 'rtsp', '-rtsp_transport', 'tcp', output_url(output)]


def relay(command):
    # POSIX exec means the process go2rtc owns becomes FFmpeg: consumer stop cannot orphan a relay.
    # FFmpeg errors can include signed URLs/cookies; only fixed diagnostic messages are emitted.
    if os.name != 'nt':
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        with open(os.devnull, 'wb') as errors:
            os.dup2(errors.fileno(), 2)
        os.execv(command[0], command)
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    # The fixed Windows entry owns this process and all descendants in a nested Job Object.
    try:
        if child.wait() != 0:
            raise SourceError('relay_failed: test the source in go2rtc; try H264 conversion and check network access')
    finally:
        if child.poll() is None:
            child.terminate()
            try: child.wait(timeout=5)
            except subprocess.TimeoutExpired: child.kill(); child.wait()


def self_test():
    import yt_dlp, streamlink, yt_dlp_ejs, curl_cffi  # Validate bundled extensions as well as metadata.
    result = {name: importlib.metadata.version(name) for name in ('yt-dlp', 'streamlink', 'yt-dlp-ejs', 'curl-cffi')}
    result['node'] = subprocess.check_output([binary('node'), '--version'], timeout=15, text=True).strip()
    subprocess.run([binary('ffmpeg'), '-version'], check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description='WebOBS fixed website-to-go2rtc relay')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--engine', choices=('yt-dlp', 'streamlink'))
    parser.add_argument('--url64')
    parser.add_argument('--height', type=int, choices=(360, 480, 720, 1080, 1440, 2160), default=720)
    parser.add_argument('--video', choices=('auto', 'copy', 'h264'), default='auto')
    parser.add_argument('--cookies-name', default='')
    parser.add_argument('--output')
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test(); return
        if not args.engine or not args.url64 or not args.output:
            raise SourceError('missing_arguments: create the source with WebOBS website source settings')
        url, output, cookies = page_url(args.url64), output_url(args.output), cookie_file(args.cookies_name)
        resolve = resolve_ytdlp if args.engine == 'yt-dlp' else resolve_streamlink
        inputs = resolve(url, args.height, cookies)
        relay(ffmpeg_command(inputs, output, args.video, args.height))
    except SourceError as error:
        print('WebOBS online source: ' + str(error), file=sys.stderr, flush=True)
        raise SystemExit(2) from None
    except Exception:
        print('WebOBS online source: runtime_failed: check the complete runtime and private configuration', file=sys.stderr, flush=True)
        raise SystemExit(2) from None


if __name__ == '__main__':
    main()
