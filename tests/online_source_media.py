"""Real extractors + FFmpeg + go2rtc against local synthetic MP4/HLS, never external-site qualification."""
import argparse
import base64
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        if self.server.drop_media and not self.server.dropped and self.path == '/video.mp4' and self.headers.get('Range') == 'bytes=0-':
            self.server.dropped = True
            self.connection.shutdown(socket.SHUT_RDWR); self.connection.close(); return
        super().do_GET()


def reserve_port():
    with socket.socket() as lease:
        lease.bind(('127.0.0.1', 0)); return lease.getsockname()[1]


def exercise(runtime=None, drop_media=False):
    win = os.name == 'nt'
    root = Path(runtime) if runtime else Path('/opt/webobs')
    ffmpeg = root/'bin/ffmpeg.exe' if win else Path('/usr/bin/ffmpeg')
    go2rtc = root/'bin'/('go2rtc.exe' if win else 'go2rtc')
    env = dict(os.environ)
    env.update(WEBOBS_GO2RTC_RTSP_PORT=str(reserve_port()),WEBOBS_FFMPEG_PATH=str(ffmpeg),
               WEBOBS_NODE_PATH=str(root/'bin'/('node.exe' if win else 'node')))
    if win:
        env['PATH']=str(root/'bin')+os.pathsep+str(Path(os.environ['SystemRoot'])/'System32')
    rtsp_port = int(env['WEBOBS_GO2RTC_RTSP_PORT']); api_port = reserve_port()
    with tempfile.TemporaryDirectory(prefix='webobs-online-media-') as temp:
        private = Path(temp)
        subprocess.run([str(ffmpeg),'-nostdin','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10',
                        '-t','12','-c:v','libx264','-pix_fmt','yuv420p','-g','10','-movflags','+faststart',str(private/'video.mp4')],check=True,timeout=30)
        subprocess.run([str(ffmpeg),'-nostdin','-hide_banner','-loglevel','error','-i',str(private/'video.mp4'),'-c','copy','-hls_time','1','-hls_list_size','0',str(private/'live.m3u8')],check=True,timeout=30)
        (private/'index.html').write_text('<html><title>Local website source fixture</title><video src="video.mp4" controls></video></html>')
        server = ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(private)))
        server.drop_media, server.dropped = drop_media, False
        worker = threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        media_base = f'http://127.0.0.1:{server.server_port}/'
        streams={}
        for engine, page in (('yt-dlp','index.html'),('streamlink','live.m3u8')):
            encoded=base64.urlsafe_b64encode((media_base+page).encode()).decode().rstrip('=')
            streams[engine]=f'exec:webobs-online-source --engine {engine} --url64 {encoded} --height 720 --video auto --output {{output}}#starttimeout=90'+('' if win else '#killsignal=15#killtimeout=5')
        config=private/'go2rtc.yaml';config.write_text(json.dumps({'api':{'listen':f'127.0.0.1:{api_port}'},'rtsp':{'listen':f'127.0.0.1:{rtsp_port}'},'webrtc':{'listen':''},'streams':streams}))
        env['WEBOBS_GO2RTC_CONFIG']=str(config)
        command=[str(go2rtc),'-config',str(config)]
        if win:command=[str(root/'bin/webobs-job.exe'),'--console',*command]
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env,
                                 **({'creationflags':subprocess.CREATE_NO_WINDOW} if win else {'start_new_session':True}))
        try:
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{api_port}/api/streams',timeout=1) as response:
                        if response.status==200:break
                except OSError:time.sleep(.1)
            else:raise RuntimeError('synthetic go2rtc did not become healthy')
            for engine in streams:
                # Consume actual RTSP frames with the real decoder, twice to verify on-demand reconnect.
                for _ in range(2):
                    probe=subprocess.run([str(ffmpeg),'-nostdin','-hide_banner','-loglevel','error','-rtsp_transport','tcp','-i',f'rtsp://127.0.0.1:{rtsp_port}/{engine}',
                                          '-frames:v','10','-an','-f','null','-'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,env=env,timeout=100)
                    if probe.returncode:raise RuntimeError(engine+' synthetic RTSP decoding failed')
                print(engine+' resolved local media and decoded RTSP frames after reconnect',flush=True)
            # Closed consumers must release every on-demand producer.
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                with urllib.request.urlopen(f'http://127.0.0.1:{api_port}/api/streams',timeout=2) as response:state=json.load(response)
                if all(not any(producer.get('medias') for producer in entry.get('producers',[])) for entry in state.values()):break
                time.sleep(.2)
            else:raise RuntimeError('website producers remained active after consumers closed')
            print('Website producers stopped after consumers closed',flush=True)
            if drop_media:
                if not server.dropped:raise RuntimeError('media disconnect fault was not exercised')
                print('Actual initial HTTP disconnect recovered and decoded media',flush=True)
        finally:
            if process.poll() is None:
                if win:process.stdin.write(b'shutdown\n');process.stdin.flush()
                else:os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=35)
                except subprocess.TimeoutExpired:
                    if win:process.kill()
                    else:os.killpg(process.pid,signal.SIGKILL)
                    process.wait(timeout=10)
            process.stdin.close();server.shutdown();server.server_close();worker.join(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--runtime',type=Path);parser.add_argument('--drop-first-media-request',action='store_true');args=parser.parse_args();exercise(args.runtime,args.drop_first_media_request)
