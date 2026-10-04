"""Authenticated synthetic ONVIF device inside an isolated complete product container."""
import importlib.util
from http.server import HTTPServer
import json
import os
from pathlib import Path
import subprocess
import socket

os.environ['WEBOBS_TEST_CAMERA_REGISTRY']='/opt/webobs/bin/webobs-camera-registry'
os.environ['WEBOBS_TEST_NVR_SERVICE']='/opt/webobs/bin/webobs-nvrd'
spec=importlib.util.spec_from_file_location('control_fixture_contracts','/tmp/test_camera_registry.py')
contracts=importlib.util.module_from_spec(spec);spec.loader.exec_module(contracts)
image=Path('/tmp/device-control-fixture.jpg')
subprocess.run(['/usr/bin/ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i','color=c=blue:s=160x90','-frames:v','1',str(image)],
               check=True,timeout=15,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
class Handler(contracts.OnvifEmulatorHandler):
    require_http_digest=True
    def soap(self,body,status=200):
        marker=Path('/tmp/device-control-drop-next-move')
        if status==200 and '/ContinuousMove"' in self.headers.get('SOAPAction','') and marker.exists():
            marker.unlink();self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close();self.close_connection=True
            return
        return super().soap(body,status)
    def do_POST(self):
        super().do_POST()
        temporary=Path('/tmp/device-control-actions.tmp')
        temporary.write_text(json.dumps(self.action_log[-128:]))
        os.replace(temporary,'/tmp/device-control-actions.json')
    def do_GET(self):
        if self.path!='/snapshot.jpg':return super().do_GET()
        data=image.read_bytes();self.send_response(200);self.send_header('Content-Type','image/jpeg')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
HTTPServer(('127.0.0.1',19091),Handler).serve_forever()
