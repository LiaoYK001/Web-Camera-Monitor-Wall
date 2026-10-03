"""Real core/NVR proxy checks using isolated synthetic H264 files, never cameras."""
import concurrent.futures
import hashlib
import json
import time
import urllib.error
import urllib.request
import uuid


def exercise_media_access(docker, name, admin, one, two, viewer, stamp):
    def response(client, path, method='GET', headers=None):
        request = urllib.request.Request(client.base + path, method=method,
            headers={'Origin': client.base, **(headers or {})})
        try:
            return client.opener.open(request, timeout=15)
        except urllib.error.HTTPError as error:
            return error

    a = json.loads(one.expect('/api/v1/nvr/segments'))['segments']
    b = json.loads(two.expect('/api/v1/nvr/segments'))['segments']
    assert {item['cameraId'] for item in a} == {'camera-a'}
    assert {item['cameraId'] for item in b} == {'camera-b'}
    assert [item['id'] for item in json.loads(one.expect('/api/v1/nvr/status'))['cameras']] == ['camera-a']
    a_id, b_id = a[0]['id'], b[0]['id']
    one.expect('/api/v1/nvr/segments?cameraId=camera-a&cameraId=camera-b', 403)
    one.expect(f'/api/v1/nvr/timeline?from={stamp}&to={stamp+3000}&cameraId=camera-a&cameraId=camera-b', 403)
    timeline = json.loads(one.expect(f'/api/v1/nvr/timeline?from={stamp}&to={stamp+3000}'))
    assert [item['cameraId'] for item in timeline['cameras']] == ['camera-a']
    for route in ['/media/', '/thumbnails/']:
        one.expect('/api/v1/nvr' + route + b_id, 403)
        with response(one, '/api/v1/nvr' + route + b_id, 'HEAD') as reply:
            assert reply.status == 403
            assert not reply.read()
    with response(one, '/api/v1/nvr/media/' + b_id, headers={'X-WebObs-Nvr-Principal': 'evidence-two'}) as reply:
        assert reply.status == 403, 'Forged media identity escaped the authentication gate'
    for method in ['GET', 'PUT']:
        viewer.expect('/api/v1/nvr/config', 403, {'schemaVersion': 1, 'cameras': []} if method == 'PUT' else None, method)
    one.expect('/api/v1/nvr/locks/' + b_id, 403, {'locked': True}, 'PUT')
    one.expect('/api/v1/nvr/events/camera-b', 403, {'active': True}, 'POST')
    one.expect('/api/v1/nvr/snapshots', 403, {'segmentId': b_id, 'offsetMs': 0}, 'POST')
    lease = json.loads(one.expect('/api/v1/nvr/playback-leases', 201, {'segmentId': a_id, 'ttlSeconds': 30}, 'POST'))
    two.expect('/api/v1/nvr/playback-leases/' + lease['id'], 404, method='DELETE')
    one.expect('/api/v1/nvr/playback-leases/' + lease['id'], method='DELETE')
    snapshot = json.loads(one.expect('/api/v1/nvr/snapshots', 201, {'segmentId': a_id, 'offsetMs': 0}, 'POST'))
    assert hashlib.sha256(one.expect(snapshot['downloadUrl'])).hexdigest() == snapshot['sha256']
    two.expect(snapshot['downloadUrl'], 404)
    admin.expect(snapshot['downloadUrl'], 404)
    one.expect('/api/v1/nvr/media/' + a_id, 403, origin='https://untrusted.invalid')
    one.expect('/api/v1/nvr/segments', 403, origin='https://untrusted.invalid')
    one.expect('/api/v1/nvr/media/' + a_id + '?ignored=1', 400)
    with response(one, '/api/v1/nvr/media/' + a_id, headers={'Range': 'bytes=' + '1' * 129 + '-'}) as reply:
        assert reply.status == 400

    # A real high-entropy lossless H264 MP4 exceeds the old 64 MiB bound.
    seed = '''import pathlib,subprocess,sqlite3,uuid,hashlib,json
root=pathlib.Path('/recordings/nvr');target=root/'large-synthetic.mp4'
subprocess.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i','nullsrc=size=1280x720:rate=25','-vf','noise=alls=100:allf=t','-t','3','-c:v','libx264','-preset','ultrafast','-qp','0','-movflags','+faststart','-y',str(target)],check=True,timeout=45,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
digest=hashlib.sha256()
with target.open('rb') as source:
 for block in iter(lambda:source.read(65536),b''):digest.update(block)
identity=uuid.uuid4().hex;size=target.stat().st_size
db=sqlite3.connect(root/'catalog.sqlite3')
db.execute("INSERT INTO segments(id,camera_id,start_utc_ms,end_utc_ms,duration_ms,storage_key,kind,video_codec,audio_codec,size_bytes,integrity,locked,created_utc_ms,sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(identity,'camera-a',STAMP-60000,STAMP-57000,3000,target.name,'continuous','h264','',size,'ok',0,STAMP,digest.hexdigest()));db.commit()
print(json.dumps({'id':identity,'size':size,'sha256':digest.hexdigest()}))
'''.replace('STAMP', str(stamp))
    large = json.loads(docker('exec', name, 'python3', '-c', seed))
    assert large['size'] > 64 << 20, 'Synthetic MP4 did not exceed old response limit'
    path = '/api/v1/nvr/media/' + large['id']
    with response(one, path, 'HEAD') as reply:
        assert reply.status == 200 and int(reply.headers['Content-Length']) == large['size']
        etag = reply.headers['ETag']
        assert not reply.read()
    with response(one, path, headers={'Range': 'bytes=10-109', 'If-Range': etag}) as reply:
        assert reply.status == 206 and len(reply.read()) == 100
        assert reply.headers['Content-Range'] == f"bytes 10-109/{large['size']}"
    with response(one, path, headers={'Range': 'bytes=-0'}) as reply:
        assert reply.status == 416 and reply.headers['Content-Range'] == f"bytes */{large['size']}"
    with response(one, path, headers={'If-None-Match': etag}) as reply:
        assert reply.status == 304

    def resident_kib():
        value = docker('exec', name, 'python3', '-c', '''import pathlib
for path in pathlib.Path('/proc').glob('[0-9]*/comm'):
 if path.read_text().strip()=='webobsd':
  print(next(line.split()[1] for line in path.with_name('status').read_text().splitlines() if line.startswith('VmRSS:')));break
''')
        return int(value)

    before = resident_kib()
    held = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            held = list(pool.map(lambda _: response(one, path), range(16)))
        for reply in held:
            assert reply.status == 200 and len(reply.read(1024)) == 1024
        time.sleep(.25)
        started = time.monotonic()
        for _ in range(5):
            admin.expect('/api/v1/health')
            admin.expect('/api/v1/studio')
        assert time.monotonic() - started < 3, 'Slow downloads stalled control requests'
        assert resident_kib() - before < 24 * 1024, 'Media buffers grew with file size'
        admin.expect('/api/v1/nvr/segments/' + large['id'], 409, method='DELETE')
    finally:
        for reply in held:
            reply.close()

    def download_hash(route):
        started = time.monotonic()
        with response(one, route) as reply:
            assert reply.status == 200
            first = reply.read(1024)
            assert time.monotonic() - started < 3, 'Delayed first media bytes'
            digest = hashlib.sha256(first)
            total = len(first)
            for block in iter(lambda: reply.read(65536), b''):
                digest.update(block)
                total += len(block)
        return total, digest.hexdigest()

    assert download_hash(path) == (large['size'], large['sha256'])
    job = json.loads(one.expect('/api/v1/nvr/exports/jobs', 202, {'cameraIds': ['camera-a'],
        'fromUtcMs': stamp-60000, 'toUtcMs': stamp-57000, 'mode': 'fast', 'lock': False,
        'requestId': uuid.uuid4().hex}, 'POST'))
    for _ in range(150):
        job = json.loads(one.expect('/api/v1/nvr/exports/jobs/' + job['id']))
        if job['state'] not in ['queued', 'running', 'cancelling']:
            break
        time.sleep(.1)
    assert job['state'] == 'completed', job.get('error')
    file = job['result']['files'][0]
    assert file['sizeBytes'] > 64 << 20
    assert download_hash(file['downloadUrl']) == (file['sizeBytes'], file['sha256'])
    # Disconnecting those readers must release pins, without waiting for TTL.
    admin.expect('/api/v1/nvr/segments/' + large['id'], method='DELETE')
    user = next(value for value in json.loads(admin.expect('/api/v2/users'))['users'] if value['username'] == 'evidence-one')
    def scopes(value):
        request = urllib.request.Request(admin.base + '/api/v2/users/' + user['id'], method='PATCH',
            data=json.dumps({'scopes': value}).encode(), headers={'Origin': admin.base,
                'Content-Type': 'application/json', 'If-Match': str(user['revision'])})
        with admin.opener.open(request, timeout=15) as reply:
            assert reply.status == 200
            user['revision'] = json.load(reply)['revision']
    original_scopes = user['scopes']
    try:
        scopes([])
        one.expect('/api/v1/nvr/media/' + a_id, 403)
        one.expect(snapshot['downloadUrl'], 403)
        assert not json.loads(one.expect('/api/v1/nvr/segments'))['segments']
    finally:
        scopes(original_scopes)
    one.expect(snapshot['downloadUrl'])
    print(f"Actual NVR media proxy: {large['size']//(1<<20)} MiB H264, HEAD/Range/ETag/resume, 16 slow readers with responsive control and bounded RSS, disconnect cleanup, camera scopes, lease and snapshot ownership passed.")

    return snapshot
