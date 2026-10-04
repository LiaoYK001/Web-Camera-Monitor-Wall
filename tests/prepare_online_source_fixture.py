"""Start a private synthetic website server inside a disposable complete product container."""
from pathlib import Path
import subprocess

root=Path('/tmp/webobs-online-fixture');root.mkdir(mode=0o700,exist_ok=True)
subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-t','60',
                '-c:v','libx264','-pix_fmt','yuv420p','-g','10','-movflags','+faststart','-y',str(root/'video.mp4')],check=True,timeout=30)
subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-i',str(root/'video.mp4'),'-c','copy','-hls_time','1','-hls_list_size','0','-y',str(root/'live.m3u8')],check=True,timeout=30)
(root/'index.html').write_text('<html><title>Synthetic website fixture</title><video src="video.mp4" controls></video></html>')
server=subprocess.Popen(['/usr/bin/python3','-B','-m','http.server','19090','--bind','127.0.0.1','--directory',str(root)],
                        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
(root/'server.pid').write_text(str(server.pid))
