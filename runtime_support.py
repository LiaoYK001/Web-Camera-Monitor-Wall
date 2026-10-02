"""Platform-neutral internal endpoints and supervisor-owned shutdown pipes."""
import os
import sys
import threading

PORT_NAMES = {8091: 'WEBOBS_NVR_INTERNAL_PORT', 8092: 'WEBOBS_CAMERA_INTERNAL_PORT',
              8093: 'WEBOBS_EVENTS_INTERNAL_PORT', 8094: 'WEBOBS_V2_INTERNAL_PORT',
              8095: 'WEBOBS_CLUSTER_INTERNAL_PORT', 8554: 'WEBOBS_MEDIAMTX_RTSP_PORT',
              8889: 'WEBOBS_MEDIAMTX_WEBRTC_PORT', 9997: 'WEBOBS_MEDIAMTX_API_PORT',
              11984: 'WEBOBS_GO2RTC_API_PORT', 18554: 'WEBOBS_GO2RTC_RTSP_PORT',
              18555: 'WEBOBS_GO2RTC_WEBRTC_PORT'}
STOP = threading.Event()

def service_port(legacy):
    port = int(os.environ.get(PORT_NAMES.get(legacy, ''), str(legacy)))
    if not 1024 <= port <= 65535:
        raise ValueError('invalid internal service port')
    return port

def service_http(legacy, suffix=''):
    return f'http://127.0.0.1:{service_port(legacy)}{suffix}'

def service_rtsp(legacy, suffix=''):
    return f'rtsp://127.0.0.1:{service_port(legacy)}{suffix}'

def install_owner_shutdown(callback):
    if os.environ.get('WEBOBS_OWNER_STDIN') != 'true':
        return
    def listen():
        line = sys.stdin.readline(64)
        if not line or line == 'shutdown\n':
            STOP.set()
            callback()
    threading.Thread(target=listen, name='owner-shutdown', daemon=True).start()

def serve_owned(server):
    install_owner_shutdown(server.shutdown)
    try:
        server.serve_forever(poll_interval=.2)
    finally:
        server.server_close()

def sync_directory(path):
    if os.name == 'nt':
        return  # Atomic rename plus fsync(file); Windows cannot fsync a CRT directory descriptor.
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

def protect_local_key(value, decrypt=False):
    """Windows grant keys are bound to the current user by DPAPI; Linux is unchanged."""
    if os.name != 'nt':
        return value
    import ctypes
    from ctypes import wintypes
    marker = b'WEBOBSDPAPI1'
    if decrypt and not value.startswith(marker):
        return value  # Explicitly restored Linux backups use the original key bytes.
    raw = value[len(marker):] if decrypt else value
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source = Blob(len(raw), buffer)
    output = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        result = ctypes.string_at(output.data, output.size)
        return result if decrypt else marker + result
    finally:
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))
