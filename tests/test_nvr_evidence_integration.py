"""Complete isolated product image: real MP4 export, proxy identity, RBAC and restart."""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('product_probe', ROOT / 'tests/test_go2rtc_integration.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--docker',default=shutil.which('docker'))
    parser.add_argument('--image',required=True)
    args=parser.parse_args();assert args.docker
    name='webobs-evidence-test-'+uuid.uuid4().hex[:10]
    created=False
    def docker(*arguments):
        return subprocess.check_output([args.docker,*arguments],text=True,stderr=subprocess.STDOUT,timeout=60).strip()
    try:
        docker('run','--detach','--name',name,'-p','127.0.0.1::8080',
            '-e','WEBOBS_LISTEN_ADDRESS=0.0.0.0','-e','WEBOBS_ALLOW_INSECURE_REMOTE=true',
            '-e','WEBOBS_GO2RTC_ENABLED=true','-e','WEBOBS_WEBRTC_ENABLED=false','-e','WEBOBS_COMPOSITE_ENABLED=false',
            '-e','WEBOBS_NVR_ENABLED=true','-e','WEBOBS_CLUSTER_ENABLED=true','-e','WEBOBS_COMPAT_BASIC_AUTH=false',
            '-e','WEBOBS_SESSION_COOKIE_SECURE=false','-e','WEBOBS_REGISTRATION_ENABLED=true',args.image)
        created=True
        base='http://'+docker('port',name,'8080/tcp').splitlines()[0]
        admin=probe.Client(base)
        def healthy():
            for _ in range(120):
                try:
                    with admin.opener.open(admin.base+'/api/v1/health',timeout=1) as response:
                        if response.status==200:return
                except (OSError,AssertionError):time.sleep(.25)
            raise AssertionError('Isolated product did not become healthy')
        healthy()
        admin.expect('/api/v1/nvr/exports/jobs',401)
        password=uuid.uuid4().hex
        admin.expect('/api/v1/auth/setup',201,{'username':'evidence-admin','password':password},'POST')
        admin.expect('/api/v1/auth/login',body={'username':'evidence-admin','password':password},method='POST')
        admin.expect('/api/v1/nvr/config',body={'schemaVersion':1,'minFreeBytes':0,'cameras':[
            {'id':camera,'name':camera,'policy':'off','mainUrl':'rtsp://camera.invalid/live','stream':'main','mode':'copy'}
            for camera in ['camera-a','camera-b']]},method='PUT')
        stamp=int(time.time()*1000)-10000
        # Seed only this disposable product's private catalog. No user recordings,
        # external cameras, raw logs or host-side database files are touched.
        script='''import pathlib,subprocess,sqlite3,uuid,time
root=pathlib.Path('/recordings/nvr')
db=sqlite3.connect(root/'catalog.sqlite3')
for camera in ['camera-a','camera-b']:
 target=root/(camera+'.mp4')
 subprocess.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i','color=c=blue:s=160x90:r=25','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-y',str(target)],check=True,timeout=20,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 db.execute("INSERT INTO segments(id,camera_id,start_utc_ms,end_utc_ms,duration_ms,storage_key,kind,video_codec,audio_codec,size_bytes,integrity,locked,created_utc_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(uuid.uuid4().hex,camera,STAMP,STAMP+3000,3000,target.name,'continuous','h264','aac',target.stat().st_size,'ok',0,int(time.time()*1000)))
db.commit()
'''.replace('STAMP',str(stamp))
        docker('exec',name,'python3','-c',script)
        for username,camera in [('evidence-one','camera-a'),('evidence-two','camera-b')]:
            admin.expect('/api/v2/users',201,{'username':username,'password':password,'roles':['operator','exporter'],
                'scopes':[{'kind':'camera','id':camera}]},'POST')
        one,two=probe.Client(base),probe.Client(base)
        one.expect('/api/v1/auth/login',body={'username':'evidence-one','password':password},method='POST')
        two.expect('/api/v1/auth/login',body={'username':'evidence-two','password':password},method='POST')
        request={'cameraIds':['camera-a'],'fromUtcMs':stamp+250,'toUtcMs':stamp+2250,'mode':'exact','lock':True,'requestId':uuid.uuid4().hex}
        one.expect('/api/v1/nvr/exports/jobs',403,request,'POST',origin='https://untrusted.invalid')
        one.expect('/api/v1/nvr/exports/jobs',403,{**request,'cameraIds':['camera-a','camera-b']},'POST')
        # Client-supplied principal must be replaced by the authenticated core.
        forged=urllib.request.Request(base+'/api/v1/nvr/exports/jobs',data=json.dumps(request).encode(),method='POST',
            headers={'Origin':base,'Content-Type':'application/json','X-WebObs-Nvr-Principal':'evidence-two'})
        with one.opener.open(forged,timeout=15) as response:
            assert response.status==202;job=json.load(response)
        repeated=json.loads(one.expect('/api/v1/nvr/exports/jobs',202,request,'POST'))
        assert repeated['id']==job['id'],'Idempotency lost through product proxy'
        one.expect('/api/v1/nvr/exports/jobs',409,{**request,'toUtcMs':stamp+2500},'POST')
        two.expect('/api/v1/nvr/exports/jobs/'+job['id'],404)
        two.expect('/api/v1/nvr/exports/jobs/'+job['id']+'/cancel',404,{},'POST')
        assert not json.loads(two.expect('/api/v1/nvr/exports/jobs'))['jobs']
        for _ in range(100):
            job=json.loads(one.expect('/api/v1/nvr/exports/jobs/'+job['id']))
            if job['state'] not in ['queued','running','cancelling']:break
            time.sleep(.1)
        assert job['state']=='completed',job['error']
        result=job['result'];file=result['files'][0]
        assert any(track['type']=='audio' for track in file['tracks'])
        payload=one.expect(file['downloadUrl']);assert hashlib.sha256(payload).hexdigest()==file['sha256']
        manifest=one.expect(result['manifestUrl']);assert hashlib.sha256(manifest).hexdigest()==result['manifestSha256']
        two.expect(file['downloadUrl'],404);admin.expect(file['downloadUrl'],404)
        # Lease release is a playback permission, not a recording-delete operation.
        viewer=admin.expect('/api/v2/users',201,{'username':'evidence-viewer','password':password,'roles':['viewer'],
            'scopes':[{'kind':'camera','id':'camera-a'}]},'POST')
        read=probe.Client(base);read.expect('/api/v1/auth/login',body={'username':'evidence-viewer','password':password},method='POST')
        lease=json.loads(read.expect('/api/v1/nvr/playback-leases',201,{'segmentId':json.loads(manifest)['sourceSegmentIds'][0],'ttlSeconds':30},'POST'))
        read.expect('/api/v1/nvr/playback-leases/'+lease['id'],body=None,method='DELETE')
        docker('restart','--time','45',name)
        # Docker can reassign an automatically published host port on restart.
        base='http://'+docker('port',name,'8080/tcp').splitlines()[0]
        admin.base=one.base=base
        healthy()
        restored=json.loads(one.expect('/api/v1/nvr/exports/jobs/'+job['id']))
        assert restored['state']=='completed' and restored['result']==result
        print('Product proxy identity, per-camera export scopes, owner-only status/cancel/download, idempotency, real H264/AAC/SHA-256, viewer lease release and restart persistence passed.')
    finally:
        if created:docker('rm','--force','--volumes',name)


if __name__=='__main__':main()
