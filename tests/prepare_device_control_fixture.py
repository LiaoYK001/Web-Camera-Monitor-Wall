"""Authenticated synthetic ONVIF device inside an isolated complete product container."""
import importlib.util
from http.server import HTTPServer
import json
import os
from pathlib import Path
import subprocess
import socket
import threading

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
    ptz_configuration_token='private-fixture-ptz-config'
    motion_lock=threading.Lock()
    motion_generation=0
    @classmethod
    def motion(cls,generation,moving,reason):
        with cls.motion_lock:
            if generation!=cls.motion_generation:return
            temporary=Path('/tmp/device-control-motion.tmp')
            temporary.write_text(json.dumps({'moving':moving,'reason':reason}))
            os.replace(temporary,'/tmp/device-control-motion.json')
    def soap(self,body,status=200):
        action=self.headers.get('SOAPAction','')
        if status==200 and '/ContinuousMove"' in action:
            with self.motion_lock:
                type(self).motion_generation+=1;generation=self.motion_generation
            self.motion(generation,True,'moving')
            timeout=self.ptz_moves[-1]
            if timeout:
                timer=threading.Timer(float(timeout[2:-1]),self.motion,args=(generation,False,'device-timeout'))
                timer.daemon=True;timer.start()
        elif status==200 and '/Stop"' in action:
            self.motion(self.motion_generation,False,'backend-stop')
        marker=Path('/tmp/device-control-drop-next-move')
        if status==200 and '/ContinuousMove"' in action and marker.exists():
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
