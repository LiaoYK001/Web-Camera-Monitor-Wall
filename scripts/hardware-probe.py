#!/usr/bin/env python3
"""Runtime hardware capability probe / 运行时硬件能力探测.

Reports each capability separately instead of one "GPU enabled" flag:
device node, loadable library, registered encoder/decoder, and an actual
encode/decode sample with a timeout.  Results are cached by an environment
signature so every source does not re-run the probes.
"""
import argparse
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

SCHEMA = 3
DEFAULT_CACHE = Path(os.environ.get('WEBOBS_HW_PROBE_CACHE', str(Path.home() / '.cache/webobs-dev/hardware-probe.json')))
DEFAULT_TIMEOUT = float(os.environ.get('WEBOBS_HW_PROBE_TIMEOUT', '30'))
MAX_AGE_SECONDS = float(os.environ.get('WEBOBS_HW_PROBE_MAX_AGE', str(6 * 60 * 60)))

NVIDIA_NODES = ['/dev/dxg', '/dev/nvidia0', '/dev/nvidiactl']


def run(args, timeout=DEFAULT_TIMEOUT):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return result.returncode, (result.stdout or '') + (result.stderr or '')
    except subprocess.TimeoutExpired:
        return 124, 'timeout'
    except OSError as error:
        return 125, str(error)


def ffmpeg_version():
    code, output = run(['ffmpeg', '-hide_banner', '-version'], timeout=10)
    if code != 0:
        return ''
    match = re.search(r'ffmpeg version (\S+)', output)
    return match.group(1) if match else ''


def ffmpeg_list(kind):
    code, output = run(['ffmpeg', '-hide_banner', '-hide_banner', kind], timeout=15)
    if code != 0:
        return set()
    names = set()
    for line in output.splitlines():
        match = re.match(r'\s*[A-Z.]{6}\s+(\S+)', line)
        if match:
            names.add(match.group(1))
    return names


def driver_version():
    if not shutil.which('nvidia-smi'):
        return ''
    code, output = run(['nvidia-smi', '--query-gpu=driver_version', '--format=csv,noheader'], timeout=10)
    return output.strip().splitlines()[0].strip() if code == 0 and output.strip() else ''


def node_signature():
    return ','.join(f'{node}:{os.path.exists(node)}' for node in NVIDIA_NODES)


def cache_key(ffmpeg, driver, nodes):
    return hashlib.sha256(f'{SCHEMA}|{ffmpeg}|{driver}|{nodes}'.encode()).hexdigest()[:24]


def probe_nvenc_sample(encoder, timeout=DEFAULT_TIMEOUT):
    code, output = run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
        '-f', 'lavfi', '-i', 'testsrc=duration=1:size=640x360:rate=30',
        '-c:v', encoder, '-f', 'null', '-',
    ], timeout=timeout)
    return {'code': code, 'passed': code == 0, 'detail': output.strip()[:240]}


def probe_cuda_decode(codec, timeout=DEFAULT_TIMEOUT):
    """Encode a tiny clip with the software encoder, then try a CUDA decode."""
    decoder = {'h264': 'h264_cuvid', 'hevc': 'hevc_cuvid'}.get(codec)
    source = Path(tempfile.gettempdir()) / f'webobs-probe-{codec}.mp4'
    try:
        encode_code, encode_detail = run([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
            '-f', 'lavfi', '-i', 'testsrc=duration=1:size=640x360:rate=30',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source),
        ], timeout=timeout)
        if encode_code != 0:
            return {'code': encode_code, 'passed': False, 'detail': f'fixture encode failed: {encode_detail.strip()[:160]}'}
        code, output = run([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-hwaccel', 'cuda',
            '-i', str(source), '-f', 'null', '-',
        ], timeout=timeout)
        if code == 0 and decoder:
            listed = decoder in ffmpeg_list('-decoders')
            return {'code': code, 'passed': True, 'detail': 'hardware decode ok', 'decoder': decoder, 'decoderRegistered': listed}
        return {'code': code, 'passed': False, 'detail': output.strip()[:240]}
    finally:
        source.unlink(missing_ok=True)


def probe():
    ffmpeg = ffmpeg_version()
    driver = driver_version()
    nodes = node_signature()
    encoders = ffmpeg_list('-encoders')
    decoders = ffmpeg_list('-decoders')
    key = cache_key(ffmpeg, driver, nodes)

    device_present = any(os.path.exists(node) for node in NVIDIA_NODES)
    library_loaded = bool(ctypes.util.find_library('cuda')) or os.path.exists('/usr/lib/wsl/lib/libcuda.so.1')
    encode_registered = {'h264': 'h264_nvenc' in encoders, 'hevc': 'hevc_nvenc' in encoders}
    decode_registered = {'h264': 'h264_cuvid' in decoders, 'hevc': 'hevc_cuvid' in decoders}

    encode_sample = {'h264': {'passed': False}, 'hevc': {'passed': False}}
    decode_sample = {'h264': {'passed': False}, 'hevc': {'passed': False}}
    if device_present and library_loaded and shutil.which('ffmpeg'):
        if encode_registered['h264']:
            encode_sample['h264'] = probe_nvenc_sample('h264_nvenc')
        if encode_registered['hevc']:
            encode_sample['hevc'] = probe_nvenc_sample('hevc_nvenc')
        if decode_registered['h264']:
            decode_sample['h264'] = probe_cuda_decode('h264')
        if decode_registered['hevc']:
            decode_sample['hevc'] = probe_cuda_decode('hevc')

    encode_supported = any(encode_sample[codec]['passed'] for codec in encode_sample)
    decode_supported = any(decode_sample[codec]['passed'] for codec in decode_sample)
    reasons = []
    if not device_present:
        reasons.append('no_nvidia_device_node')
    if not library_loaded:
        reasons.append('libcuda_unavailable')
    if not any(encode_registered.values()):
        reasons.append('nvenc_encoder_not_registered')
    if device_present and library_loaded and not encode_supported:
        reasons.append('nvenc_sample_failed')
    if not decode_supported:
        reasons.append('cuda_decode_sample_failed')

    vaapi_devices = sorted(str(path) for path in Path('/dev/dri').glob('renderD*')) if Path('/dev/dri').exists() else []
    result = {
        'schemaVersion': SCHEMA,
        'generatedAt': int(time.time()),
        'cacheKey': key,
        'ffmpeg': {'version': ffmpeg, 'encoders': sorted(name for name in encoders if 'nvenc' in name or 'vaapi' in name or name == 'libx264')},
        'nvidia': {
            'devicePresent': device_present,
            'deviceNodes': [{'path': node, 'present': os.path.exists(node)} for node in NVIDIA_NODES],
            'libraryLoaded': library_loaded,
            'driverVersion': driver,
            'encoderRegistered': encode_registered,
            'decoderRegistered': decode_registered,
            'encodeSample': encode_sample,
            'decodeSample': decode_sample,
            'encodeSupported': encode_supported,
            'decodeSupported': decode_supported,
            # "hardware" only when decode and encode both sample-pass; software
            # decode + NVENC is reported as partial acceleration, never as full.
            'decodeBackend': 'cuda' if decode_supported else 'software',
            'samplePassed': encode_supported,
            'acceleration': 'full' if (encode_supported and decode_supported) else ('partial' if encode_supported else 'none'),
            'ready': device_present and library_loaded and encode_supported,
            'reasons': reasons,
        },
        'vaapi': {
            'devices': vaapi_devices,
            'devicePresent': bool(vaapi_devices),
            'encoderRegistered': 'h264_vaapi' in encoders,
            'decoderRegistered': 'h264_vaapi' in decoders,
        },
        'software': {'x264': 'libx264' in encoders},
    }
    return result


def env_lines(result):
    nvidia = result['nvidia']
    encode = nvidia['encodeSample']
    decode = nvidia['decodeSample']
    values = {
        'WEBOBS_NVIDIA_DEVICE_PRESENT': nvidia['devicePresent'],
        'WEBOBS_NVIDIA_LIBRARY_LOADED': nvidia['libraryLoaded'],
        'WEBOBS_NVIDIA_ENCODER_REGISTERED': any(nvidia['encoderRegistered'].values()),
        'WEBOBS_NVIDIA_ENCODE_SUPPORTED': nvidia['encodeSupported'],
        'WEBOBS_NVIDIA_DECODE_SUPPORTED': nvidia['decodeSupported'],
        'WEBOBS_NVIDIA_SAMPLE_PASSED': nvidia['samplePassed'],
        'WEBOBS_NVIDIA_H264_DECODE': bool(decode['h264']['passed']),
        'WEBOBS_NVIDIA_HEVC_DECODE': bool(decode['hevc']['passed']),
        'WEBOBS_NVIDIA_H264_ENCODE': bool(encode['h264']['passed']),
        'WEBOBS_NVIDIA_HEVC_ENCODE': bool(encode['hevc']['passed']),
        'WEBOBS_NVIDIA_DECODE_BACKEND': nvidia['decodeBackend'],
        'WEBOBS_NVIDIA_ACCELERATION': nvidia['acceleration'],
    }
    return [f'{name}={"true" if value is True else "false" if value is False else value}' for name, value in values.items()]


def load_cache(path, key):
    try:
        cached = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if cached.get('cacheKey') != key:
        return None
    if time.time() - float(cached.get('generatedAt', 0)) > MAX_AGE_SECONDS:
        return None
    return cached


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true', help='print the full probe result as JSON')
    parser.add_argument('--env', action='store_true', help='print WEBOBS_* environment assignments')
    parser.add_argument('--force', action='store_true', help='ignore the cached result')
    parser.add_argument('--cache', default=str(DEFAULT_CACHE))
    args = parser.parse_args()

    ffmpeg = ffmpeg_version()
    key = cache_key(ffmpeg, driver_version(), node_signature())
    path = Path(args.cache)
    result = None if args.force else load_cache(path, key)
    if result is None:
        result = probe()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        except OSError:
            pass
    if args.env:
        print('\n'.join(env_lines(result)))
    elif args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        nvidia = result['nvidia']
        print(f"nvidia device={nvidia['devicePresent']} library={nvidia['libraryLoaded']} "
              f"encode={nvidia['encodeSupported']} decode={nvidia['decodeSupported']} "
              f"acceleration={nvidia['acceleration']} reasons={','.join(nvidia['reasons']) or '-'}")


if __name__ == '__main__':
    main()
