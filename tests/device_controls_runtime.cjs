// Complete isolated product; supplied image must contain the matching camera service/WebUI.
const assert=require('node:assert/strict');
const path=require('node:path');
const crypto=require('node:crypto');
const {execFileSync}=require('node:child_process');
const {createRequire}=require('node:module');
const root=path.resolve(__dirname,'..');
const {chromium,expect}=createRequire(path.join(root,'web/package.json'))('@playwright/test');
const option=name=>{const index=process.argv.indexOf(name);return index<0?undefined:process.argv[index+1];};
const image=option('--image'),docker=option('--docker')||'docker';assert(image,'Supply the matching complete image');
const name='webobs-control-test-'+crypto.randomBytes(5).toString('hex');
const run=(...args)=>execFileSync(docker,args,{encoding:'utf8',windowsHide:true,timeout:60000}).trim();
let created=false,browser;
(async()=>{
  try{
    run('run','--detach','--name',name,'-p','127.0.0.1::8080',
      '-e','WEBOBS_CAMERA_ALLOW_TEST_ENDPOINTS=true','-e','WEBOBS_LISTEN_ADDRESS=0.0.0.0',
      '-e','WEBOBS_ALLOW_INSECURE_REMOTE=true','-e','WEBOBS_GO2RTC_ENABLED=true',
      '-e','WEBOBS_COMPOSITE_ENABLED=false','-e','WEBOBS_COMPAT_BASIC_AUTH=false','-e','WEBOBS_SESSION_COOKIE_SECURE=false',image);
    created=true;
    for(const file of ['test_camera_registry.py','prepare_device_control_fixture.py'])run('cp',path.join(root,'tests',file),name+':/tmp/'+file);
    run('exec','--detach',name,'python3','-B','/tmp/prepare_device_control_fixture.py');
    const base='http://'+run('port',name,'8080/tcp').split('\n')[0];
    await expect.poll(async()=>{try{return(await fetch(base+'/api/v1/health',{signal:AbortSignal.timeout(1000)})).status;}catch{return 0;}},{timeout:30000}).toBe(200);
    // Full Chromium provides native capture; the headless-shell embedder can reject it.
    browser=await chromium.launch({channel:'chromium',args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
    const context=await browser.newContext({serviceWorkers:'block',permissions:['microphone']});
    const account={username:'device-control-admin',password:crypto.randomBytes(24).toString('hex')};
    for(const [route,status]of [['setup',201],['login',200]])assert.equal((await context.request.post(base+'/api/v1/auth/'+route,{headers:{Origin:base},data:account})).status(),status);
    const page=await context.newPage();
    await page.addInitScript(()=>{
      window.deviceStreams=[];const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia=async constraints=>{const stream=await original(constraints);window.deviceStreams.push(stream);return stream;};
    });
    await require('./device_controls_webui.cjs').exerciseDeviceControls(page,base,true);
    const actions=JSON.parse(run('exec',name,'cat','/tmp/device-control-actions.json'));
    assert.equal(actions.filter(action=>action.includes('/ContinuousMove"')).length,1,'Rejected invalid duration must not reach SOAP');
    assert(actions.some(action=>action.includes('/Stop"')));
    const endpoint=base+'/api/v1/cameras/controlled-live-fixture/onvif/ptz';
    assert.equal((await fetch(endpoint,{method:'POST',headers:{Origin:base,'Content-Type':'application/json'},body:'{"operation":"stop"}'})).status,401);
    assert.equal((await context.request.post(endpoint,{headers:{Origin:'https://untrusted.invalid'},data:{operation:'stop'}})).status(),403);
    console.log('Unauthenticated/nonmatching-Origin control gates passed');
    const countStops=values=>values.filter(action=>action.includes('/Stop"')).length;
    const before=countStops(actions);
    run('exec',name,'touch','/tmp/device-control-drop-next-move');
    assert.equal((await context.request.post(endpoint,{headers:{Origin:base},data:{operation:'continuous',x:.25,durationMs:100}})).status(),502);
    await expect.poll(()=>countStops(JSON.parse(run('exec',name,'cat','/tmp/device-control-actions.json'))),{timeout:5000}).toBeGreaterThan(before);
    const after=JSON.parse(run('exec',name,'cat','/tmp/device-control-actions.json'));
    assert.equal(after.filter(action=>action.includes('/ContinuousMove"')).length,2,'Recovery must never repeat movement');
    const audit=await context.request.get(base+'/api/v1/cameras/controlled-live-fixture/operations');
    assert.equal(audit.status(),200);
    assert((await audit.json()).operations.some(value=>value.operation==='ptz.continuous'&&value.result==='unconfirmed'));
    console.log('Authenticated product: dropped SOAP movement response returns 502, requests stop, records an unconfirmed result and never repeats movement');
  }finally{await browser?.close();if(created)run('rm','--force','--volumes',name);}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
