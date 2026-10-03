const assert = require('node:assert/strict');
const path = require('node:path');
const crypto = require('node:crypto');
const { promisify } = require('node:util');
const execFile = promisify(require('node:child_process').execFile);

async function exerciseNativeEvidence(supervisor, runtime, headers) {
  async function request(route, body, method='GET', expected=200) {
    const response=await fetch(supervisor.origin+route,{method,headers:{...headers,
      ...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});
    assert.equal(response.status,expected,`Native evidence route ${route}`);
    return response.json();
  }
  await request('/api/v1/nvr/config',{schemaVersion:1,minFreeBytes:0,cameras:[{
    id:'native-evidence-camera',name:'Synthetic evidence',policy:'off',mainUrl:'rtsp://camera.invalid/live',stream:'main',mode:'copy'}]},'PUT');
  const stamp=Date.now()-10000;
  const script=`import pathlib,subprocess,sqlite3,uuid,sys,struct,hashlib,json
root=pathlib.Path(sys.argv[1]);target=root/'synthetic-evidence.mp4'
subprocess.run([sys.argv[2],'-v','error','-nostdin','-f','lavfi','-i','color=c=blue:s=160x90:r=25','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-y',str(target)],check=True,timeout=20,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
with target.open('ab') as output:
 offset=output.tell();padding=(66<<20)+8;output.write(struct.pack('>I4s',padding,b'free'));output.truncate(offset+padding)
digest=hashlib.sha256()
with target.open('rb') as source:
 for block in iter(lambda:source.read(65536),b''):digest.update(block)
identity=uuid.uuid4().hex
db=sqlite3.connect(root/'catalog.sqlite3');db.execute("INSERT INTO segments(id,camera_id,start_utc_ms,end_utc_ms,duration_ms,storage_key,kind,video_codec,audio_codec,size_bytes,integrity,locked,created_utc_ms,sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(identity,'native-evidence-camera',${stamp},${stamp+3000},3000,target.name,'continuous','h264','aac',target.stat().st_size,'ok',0,${stamp},digest.hexdigest()));db.commit()
print(json.dumps({'id':identity,'sha256':digest.hexdigest(),'size':target.stat().st_size}))
`;
  const seeded=await execFile(path.join(runtime,'python','python.exe'),['-c',script,supervisor.recordings,path.join(runtime,'bin','ffmpeg.exe')],
    {env:supervisor.env,windowsHide:true,timeout:30000,maxBuffer:4096});
  const media=JSON.parse(seeded.stdout),route=supervisor.origin+'/api/v1/nvr/media/'+media.id;
  const head=await fetch(route,{method:'HEAD',headers,signal:AbortSignal.timeout(15000)});
  assert.equal(head.status,200);assert.equal(Number(head.headers.get('Content-Length')),media.size);
  assert.ok(media.size>64*1024*1024);
  const ranged=await fetch(route,{headers:{...headers,Range:'bytes=10-109','If-Range':head.headers.get('ETag')},signal:AbortSignal.timeout(15000)});
  assert.equal(ranged.status,206);assert.equal((await ranged.arrayBuffer()).byteLength,100);
  const notModified=await fetch(route,{headers:{...headers,'If-None-Match':head.headers.get('ETag')},signal:AbortSignal.timeout(15000)});
  assert.equal(notModified.status,304);
  const streamed=await fetch(route,{headers,signal:AbortSignal.timeout(45000)});
  assert.equal(streamed.status,200);
  const sourceDigest=crypto.createHash('sha256');let bytes=0;
  for await(const block of streamed.body){sourceDigest.update(block);bytes+=block.byteLength;}
  assert.equal(bytes,media.size);assert.equal(sourceDigest.digest('hex'),media.sha256);
  const value={cameraIds:['native-evidence-camera'],fromUtcMs:stamp+250,toUtcMs:stamp+2250,mode:'exact',lock:true,requestId:crypto.randomUUID()};
  let job=await request('/api/v1/nvr/exports/jobs',value,'POST',202);
  const repeated=await request('/api/v1/nvr/exports/jobs',value,'POST',202);assert.equal(repeated.id,job.id);
  for(let index=0;index<100 && ['queued','running','cancelling'].includes(job.state);index++) {
    await new Promise(resolve=>setTimeout(resolve,100));job=await request('/api/v1/nvr/exports/jobs/'+job.id);
  }
  assert.equal(job.state,'completed',job.error?.code);
  const result=job.result;assert.ok(result.files[0].tracks.some(track=>track.type==='audio'));
  const response=await fetch(supervisor.origin+result.files[0].downloadUrl,{headers});assert.equal(response.status,200);
  const digest=crypto.createHash('sha256').update(Buffer.from(await response.arrayBuffer())).digest('hex');
  assert.equal(digest,result.files[0].sha256);
  return async()=>{const restored=await request('/api/v1/nvr/exports/jobs/'+job.id);assert.equal(restored.state,'completed');assert.deepEqual(restored.result,result);};
}
module.exports={exerciseNativeEvidence};
