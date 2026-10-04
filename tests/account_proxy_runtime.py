"""Actual control binary with a delayed loopback account fixture; no user accounts."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request


class AccountHandler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length','0')))
        mode=self.server.mode
        if mode=='slow':time.sleep(3.4)
        elif mode=='timeout':time.sleep(11)
        status={'reject':401,'rate':429,'failed':503}.get(mode,201 if self.path=='/auth/setup' else 200)
        body=json.dumps({'username':'slow-fixture'}).encode()
        try:
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass


def exercise(binary, job=None):
    server=ThreadingHTTPServer(('127.0.0.1',0),AccountHandler);server.mode='slow'
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    with tempfile.TemporaryDirectory(prefix='webobs-auth-deadline-') as temp:
        private=Path(temp)
        with socket.socket() as lease:lease.bind(('127.0.0.1',0));port=lease.getsockname()[1]
        env={key:value for key,value in os.environ.items() if not key.startswith('WEBOBS_')}
        env.update(WEBOBS_HTTP_PORT=str(port),WEBOBS_LISTEN_ADDRESS='127.0.0.1',
                   WEBOBS_CLUSTER_INTERNAL_PORT=str(server.server_port),WEBOBS_CLUSTER_INTERNAL_TOKEN='a'*64,
                   WEBOBS_COMPAT_BASIC_AUTH='false',WEBOBS_SESSION_COOKIE_SECURE='false',
                   WEBOBS_SESSION_DATABASE=str(private/'sessions.db'),WEBOBS_SCENE_FILE=str(private/'scene.json'),
                   WEBOBS_WEBRTC_ENABLED='true',WEBOBS_COMPOSITE_ENABLED='false',WEBOBS_NVR_ENABLED='false',
                   WEBOBS_WHIP_URL='http://127.0.0.1:8889/fixture/whip',NO_PROXY='127.0.0.1,localhost')
        command=[str(binary),'--duration-seconds','60']
        if os.name=='nt':
            runtime=binary.parent.parent
            env['PATH']=os.pathsep.join(str(path) for path in (binary.parent,runtime/'obs/bin/64bit',Path(os.environ['SystemRoot'])/'System32'))
        if job:command=[str(job),'--console',*command]
        diagnostic=open(private/'control.log','wb')
        process=subprocess.Popen(command,env=env,stdin=subprocess.PIPE,stdout=diagnostic,stderr=subprocess.STDOUT,
                                 **({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}))
        origin=f'http://127.0.0.1:{port}'
        def request(path,origin_header=origin):
            value=urllib.request.Request(origin+path,data=b'{"username":"slow-fixture","password":"fixture-password-1234"}',
                                         headers={'Origin':origin_header,'Content-Type':'application/json'},method='POST')
            try:reply=urllib.request.urlopen(value,timeout=13)
            except urllib.error.HTTPError as error:reply=error
            with reply:return reply.status,reply.headers.get('Set-Cookie'),reply.read()
        try:
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                if process.poll() is not None:
                    raise AssertionError('Isolated control exited: '+(private/'control.log').read_text(errors='replace')[:500])
                try:
                    with urllib.request.urlopen(origin+'/api/v1/health',timeout=1) as reply:
                        if reply.status==200:break
                except OSError:time.sleep(.1)
            else:raise AssertionError('Isolated control binary did not start')
            if request('/api/v1/auth/login','https://untrusted.invalid')[0]!=403:raise AssertionError('Origin gate changed')
            if request('/api/v1/auth/setup')[0]!=201:raise AssertionError('Slow first account setup failed')
            status,cookie,_=request('/api/v1/auth/login')
            if status!=200 or not cookie:raise AssertionError('Valid login slower than three seconds failed')
            print('Actual control proxy accepted delayed setup/login and issued a session',flush=True)
            for mode,expected in (('reject',401),('rate',429),('failed',503),('timeout',503)):
                server.mode=mode;started=time.monotonic();status,cookie,body=request('/api/v1/auth/login')
                if status!=expected or cookie:raise AssertionError('Account failure status or session boundary changed')
                if expected==503 and b'authentication_unavailable' not in body:raise AssertionError('Outage was reported as a bad password')
                if time.monotonic()-started>12:raise AssertionError('Account operation exceeded its bound')
            print('Invalid credentials/rate limits retained; account outages/timeouts return bounded 503 without a session',flush=True)
        finally:
            if process.poll() is None:
                if job:process.stdin.write(b'shutdown\n');process.stdin.flush()
                elif os.name=='nt':process.terminate()
                else:os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            process.stdin.close();diagnostic.close();server.shutdown();server.server_close();worker.join(timeout=3)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--binary',type=Path,required=True);parser.add_argument('--job',type=Path)
    args=parser.parse_args();exercise(args.binary,args.job)
