"""Real bundled FFmpeg must reject untrusted TLS peers before sending HTTP requests."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        self.server.requests += 1
        if self.headers.get('Cookie') == 'website-fixture=private':
            self.server.cookies += 1
        super().do_GET()


def exercise(runtime=None):
    win = os.name == 'nt'
    root = Path(runtime) if runtime else Path('/opt/webobs')
    ffmpeg = root/'bin/ffmpeg.exe' if win else Path('/usr/bin/ffmpeg')
    openssl = root/'bin/openssl.exe' if win else Path('/usr/bin/openssl')
    relay = root/'services/go2rtc/online_source.py' if win else root/'online-source/online_source.py'
    spec = importlib.util.spec_from_file_location('bundled_tls_relay', relay)
    source = importlib.util.module_from_spec(spec)
    # The installed runtime is immutable. The test runner itself may omit Python -B.
    with patch.object(sys,'dont_write_bytecode',True):
        spec.loader.exec_module(source)
    with tempfile.TemporaryDirectory(prefix='webobs-source-tls-') as temp:
        private = Path(temp); cert = private/'certificate.pem'; key = private/'key.pem'
        config = private/'openssl.cnf'; config.write_text('[req]\ndistinguished_name=dn\n[dn]\n',encoding='ascii')
        env = dict(os.environ, WEBOBS_FFMPEG_PATH=str(ffmpeg), WEBOBS_GO2RTC_RTSP_PORT='18554')
        subprocess.run([str(openssl),'req','-config',str(config),'-x509','-newkey','rsa:2048','-nodes','-days','1',
                        '-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost',
                        '-keyout',str(key),'-out',str(cert)],check=True,env=env,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
        subprocess.run([str(ffmpeg),'-nostdin','-hide_banner','-loglevel','error','-f','lavfi',
                        '-i','testsrc2=size=160x90:rate=5','-t','1','-c:v','libx264',
                        '-movflags','+faststart',str(private/'video.mp4')],check=True,env=env,timeout=30)
        server = ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(private)))
        server.requests = server.cookies = 0
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert,key)
        server.socket = context.wrap_socket(server.socket,server_side=True)
        worker = threading.Thread(target=server.serve_forever,daemon=True); worker.start()
        def decode(host, trust=False):
            current = dict(env)
            current.pop('SSL_CERT_FILE',None)
            if trust:current['SSL_CERT_FILE']=str(cert)
            inputs=[dict(url=f'https://{host}:{server.server_port}/video.mp4',
                         headers={'User-Agent':'WebOBS website fixture'},video='h264',audio='none')]
            with patch.dict(os.environ,current,clear=True):
                command=source.ffmpeg_command(inputs,'rtsp://127.0.0.1:18554/'+'a'*32,'auto',720)
            # Exercise the exact product input options, using a local decoder instead of RTSP output.
            command=command[:command.index('-map')]+['-frames:v','1','-an','-f','null','-']
            return subprocess.run(command,env=current,stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL,timeout=30).returncode
        try:
            if decode('localhost') == 0 or server.requests or server.cookies:
                raise AssertionError('Untrusted HTTPS peer received website credentials or decoded media')
            print('Actual bundled FFmpeg rejected untrusted TLS before sending an HTTP request',flush=True)
            if not win:
                if decode('localhost',True) != 0 or not server.requests:
                    raise AssertionError('Trusted localhost TLS did not decode media')
                requests=server.requests
                if decode('127.0.0.1',True) == 0 or server.requests != requests:
                    raise AssertionError('TLS hostname mismatch sent website credentials or decoded media')
                print('Explicit backend CA decoded media; mismatched hostname rejected before HTTP',flush=True)
            # Windows deliberately never installs fixture CAs into the user's trust store.
        finally:
            server.shutdown();server.server_close();worker.join(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--runtime',type=Path)
    exercise(parser.parse_args().runtime)
