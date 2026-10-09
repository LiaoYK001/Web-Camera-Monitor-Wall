const path=require('node:path'),fs=require('node:fs/promises'),os=require('node:os'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'../..');
const option=name=>{const i=process.argv.indexOf(name);return i<0?undefined:process.argv[i+1]};
const {createRequire}=require('node:module');
const requireDesktop=createRequire(path.join(root,'desktop/package.json'));
const {app,safeStorage,BrowserWindow}=requireDesktop('electron');
const {chromium,expect}=createRequire(path.join(root,'web/package.json'))('@playwright/test');
app.on('window-all-closed',()=>{});
(async()=>{
 const temporary=process.env.WEBOBS_SOURCE_UI_ROOT;
 if(!temporary||!path.resolve(temporary).startsWith(path.join(os.tmpdir(),'webobs-source-ui-')))throw new Error('Use run-online-source-native.mjs with an isolated owned profile');
 app.setPath('userData',path.join(temporary,'WebOBS'));app.setPath('sessionData',path.join(temporary,'browser'));
 let supervisor,browser,window,upstream,manifestRevision,frontendEntrySha256,frontendOverride,restartVideo,failure,stage='initialization',exit=0;const receipts=[];
 try{
  await app.whenReady();window=new BrowserWindow({show:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}});await window.loadURL('data:text/html,<title>Public online qualification</title>');
  const runtime=path.resolve(option('--runtime')||path.join(root,'desktop/runtime'));
  const frontend=option('--frontend')&&path.resolve(option('--frontend'));
  const soakSeconds=Number(option('--soak-seconds')||0);
  if(!Number.isInteger(soakSeconds)||soakSeconds<0||soakSeconds>3600)throw new Error('Soak seconds must be an integer from 0 to 3600');
  const external=option('--sources')&&JSON.parse(await fs.readFile(option('--sources'),'utf8'));
  if(external&&(!Array.isArray(external)||external.length<1||external.length>8||external.some(s=>!/^[-a-z0-9]{1,64}$/.test(s.name)||!['auto','yt-dlp','streamlink','direct'].includes(s.engine)||(s.video&&!['auto','copy','h264'].includes(s.video))||!/^https?:\/\//.test(s.address))))throw new Error('Supply 1-8 explicitly selected public sources');
  const manifest=await (await import('../src/runtime-integrity.mjs')).verifyRuntime(runtime);manifestRevision=manifest.revision;
  frontendOverride=Boolean(frontend);
  frontendEntrySha256=crypto.createHash('sha256').update(await fs.readFile(path.join(frontend||path.join(runtime,'web'),'index.html'))).digest('hex');
  const net=require('node:net');const reserve=()=>new Promise(resolve=>{const listener=net.createServer();listener.listen(0,'127.0.0.1',()=>{const p=listener.address().port;listener.close(()=>resolve(p));});});
  const apiPort=await reserve(),rtspPort=await reserve(),password=crypto.randomBytes(24).toString('hex')+'@:/#?%';
  const fixtureUrl=new URL(`rtsp://127.0.0.1:${rtspPort}/fixture`);
  fixtureUrl.username='fixture';fixtureUrl.password=encodeURIComponent(password);
  const rtspAddress=fixtureUrl.href;
  const fixtureConfig=path.join(temporary,'fixture.json');await fs.writeFile(fixtureConfig,JSON.stringify({api:{listen:`127.0.0.1:${apiPort}`},rtsp:{listen:`127.0.0.1:${rtspPort}`,username:'fixture',password},webrtc:{listen:''},streams:{fixture:'ffmpeg:virtual?video=testsrc2&size=160x90#video=h264'}}));
  if(!external)upstream=require('node:child_process').spawn(path.join(runtime,'bin/webobs-job.exe'),['--console',path.join(runtime,'bin/go2rtc.exe'),'-config',fixtureConfig],{windowsHide:true,stdio:['pipe','ignore','ignore'],env:{...process.env,PATH:path.join(runtime,'bin')+path.delimiter+path.join(process.env.SystemRoot,'System32')}});
  if(upstream)await expect.poll(async()=>{try{return (await fetch(`http://127.0.0.1:${apiPort}/api/streams`)).status}catch{return 0}},{timeout:15000}).toBe(200);
  const {Supervisor}=await import('../src/supervisor.mjs');const {defaults}=await import('../src/settings.mjs');
  supervisor=new Supervisor({runtime,root:path.join(temporary,'WebOBS'),videos:path.join(temporary,'Videos'),settings:{...defaults},version:manifest.version,safeStorage});
  supervisor.on('status',s=>console.log('Startup: '+s.phase));await supervisor.start();
  browser=await chromium.launch();const context=await browser.newContext({serviceWorkers:'block'});const base=supervisor.origin;
  const data={username:'public-source-probe',password:crypto.randomBytes(24).toString('hex')};
  expect((await context.request.post(base+'/api/v1/auth/setup',{headers:{Origin:base},data})).status()).toBe(201);
  expect((await context.request.post(base+'/api/v1/auth/login',{headers:{Origin:base},data})).status()).toBe(200);
  const page=await context.newPage();page.setDefaultTimeout(15000);
  let socketBytes=0,socketFrames=0,socketErrors=0;const socketErrorCategories=new Set();
  page.on('websocket',socket=>socket.on('framereceived',event=>{
   if(Buffer.isBuffer(event.payload)){socketFrames++;socketBytes+=event.payload.length;}
   else {try{const value=JSON.parse(event.payload);if(value.type==='error'){
    socketErrors++;const text=JSON.stringify(value).toLowerCase();
    for(const category of ['timeout','no compatible codecs','exec','eof','401','403','404','refused','reset'])if(text.includes(category))socketErrorCategories.add(category);
   }}catch{}}
  }));
  // Exercise the current production frontend with the actual authenticated native services.
  if(frontend)await page.route(base+'/**',async route=>{
   const u=new URL(route.request().url());if(u.pathname.startsWith('/api/'))return route.continue();
   const relative=u.pathname==='/'?'index.html':u.pathname.slice(1);const target=path.resolve(frontend,relative);
   if(!target.startsWith(frontend+path.sep))return route.continue();
   const body=await fs.readFile(target).catch(()=>null);if(!body)return route.continue();
   const ext=path.extname(target);await route.fulfill({body,contentType:ext==='.js'?'application/javascript':ext==='.css'?'text/css':ext==='.html'?'text/html':'application/octet-stream'});
  });
  for(const {name,address,engine,video:videoMode} of external||[{name:'private-rtsp',address:rtspAddress,engine:'auto'}]){
   socketBytes=socketFrames=socketErrors=0;socketErrorCategories.clear();
   const start=Date.now();let phase='form';
   try{
    await page.goto(base+'/#go2rtc');const form=page.getByRole('region',{name:'网站与直播源'});
    await form.getByLabel('接入方式').selectOption(engine);await form.getByLabel('流名称',{exact:true}).fill(name);await form.getByLabel('视频网页或直播地址').fill(address);
    if(videoMode)await form.getByLabel('视频兼容策略').selectOption(videoMode);
    await form.getByRole('button',{name:'保存命名流并重启 go2rtc'}).click();await expect(form.getByRole('status')).toContainText('已保存并加载',{timeout:35000});
    phase='cold-import';
    const cold=page.locator('.go2rtc-stream-list > div').filter({has:page.getByText(name,{exact:true})});await cold.getByRole('button',{name:'检测并添加设备',exact:true}).click();
    await expect(cold.getByRole('button',{name:'已在设备目录',exact:true})).toBeVisible({timeout:60000});await expect.poll(async()=>{const cameras=(await (await context.request.get(base+'/api/v1/cameras')).json()).cameras;return cameras.find(c=>c.name===name)?.profiles.every(p=>p.probeState==='ready'&&p.width>0)},{timeout:30000}).toBe(true);console.log('Cold import and actual track probe completed');
    phase='decode';await page.goto(base+'/api/v1/go2rtc/stream.html?src='+name+'&mode=mse');
    const video=page.locator('video');await video.evaluate(v=>{v.muted=true;v.play().catch(()=>{});});
    await page.waitForFunction(()=>{const v=document.querySelector('video');return v?.readyState>=2&&v.videoWidth>0},null,{timeout:110000});
    const stamp=await video.evaluate(v=>v.currentTime);await expect.poll(()=>video.evaluate(v=>v.currentTime),{timeout:15000}).toBeGreaterThan(stamp+1);
    const dimensions=await video.evaluate(v=>[v.videoWidth,v.videoHeight]);phase='registry';
    // Keep the decoder open while a second page checks the registry and Studio.
    const management=await context.newPage();await management.route(base+'/**',async route=>route.continue());await management.goto(base+'/#go2rtc');
    const row=management.locator('.go2rtc-stream-list > div').filter({has:management.getByText(name,{exact:true})});
    await expect(row.getByRole('button',{name:'已在设备目录',exact:true})).toBeVisible({timeout:60000});
    const cameras=(await (await context.request.get(base+'/api/v1/cameras')).json()).cameras;const camera=cameras.find(c=>c.name===name);expect(camera?.profiles?.length).toBeGreaterThan(0);
    phase='studio';await management.goto(base+'/#studio');await management.getByRole('button',{name:'新建场景',exact:true}).click();
    const dialog=management.getByRole('dialog',{name:'新建场景',exact:true});await dialog.getByLabel('场景名称').fill(name);await dialog.getByRole('checkbox',{name,exact:true}).check();await dialog.getByRole('button',{name:'应用到草稿'}).click();await management.getByRole('button',{name:'保存并应用',exact:true}).click();
    await expect.poll(async()=>{const studio=await (await context.request.get(base+'/api/v1/studio')).json();return studio.scenes.some(s=>s.name===name&&s.sources.some(source=>source.cameraId===camera.id))},{timeout:20000}).toBe(true);
    await management.reload();await expect(management.getByRole('button',{name:'选择场景 '+name,exact:true})).toBeVisible();
    phase='take';await management.getByRole('button',{name:'TAKE',exact:true}).click();
    await expect.poll(async()=>{const studio=await (await context.request.get(base+'/api/v1/studio')).json();return studio.scenes.find(s=>s.id===studio.programSceneId)?.name},{timeout:20000}).toBe(name);
    phase='monitor-wall';await management.goto(base+'/#monitor');
    const wall=management.getByLabel(name+' 浏览器媒体画面',{exact:true});
    await expect.poll(()=>wall.evaluate(v=>v.readyState>=2&&v.videoWidth>0),{timeout:90000}).toBe(true);
    const wallStamp=await wall.evaluate(v=>v.currentTime);await expect.poll(()=>wall.evaluate(v=>v.currentTime),{timeout:15000}).toBeGreaterThan(wallStamp+1);
    let soak;
    if(soakSeconds){
     phase='monitor-soak';const started=Date.now();let samples=0;
     while(Date.now()-started<soakSeconds*1000){
      const frames=await wall.evaluate(v=>v.getVideoPlaybackQuality().totalVideoFrames);
      await page.waitForTimeout(Math.min(5000,Math.max(0,soakSeconds*1000-(Date.now()-started))));
      await expect.poll(()=>wall.evaluate(v=>v.getVideoPlaybackQuality().totalVideoFrames),{timeout:15000}).toBeGreaterThan(frames);
      samples++;if(samples%12===0)console.log('Monitor media soak: '+Math.round((Date.now()-started)/1000)+' seconds with decoded-frame progress');
     }
     soak={seconds:Math.round((Date.now()-started)/1000),progressSamples:samples};
    }
    console.log('Actual monitor wall decoded and advanced after TAKE');
    await management.close();receipts.push({name,address:external?address:'[private authenticated RTSP fixture]',engine,videoMode:videoMode||'auto',result:'passed',dimensions,seconds:Math.round((Date.now()-start)/1000),deviceImported:true,coldImport:true,studioPersisted:true,monitorWallDecoded:true,...(soak?{soak}:{})});
   }catch(error){
    const mediaDiagnostic=await page.locator('video').first().evaluate(v=>({readyState:v.readyState,networkState:v.networkState,errorCode:v.error?.code||null,decodedFrames:v.getVideoPlaybackQuality().totalVideoFrames,currentTime:v.currentTime,buffered:Array.from({length:Math.min(v.buffered.length,4)},(_,i)=>[v.buffered.start(i),v.buffered.end(i)])})).catch(()=>null);
    receipts.push({name,address:external?address:'[private authenticated RTSP fixture]',engine,videoMode:videoMode||'auto',result:'failed',phase,errorType:error.name,seconds:Math.round((Date.now()-start)/1000),mediaDiagnostic,socketBytes,socketFrames,socketErrors,socketErrorCategories:[...socketErrorCategories]});exit=1;await page.screenshot({path:path.join(temporary,name+'-failed.png')}).catch(()=>{});}
   console.log(JSON.stringify(receipts.at(-1)));
  }
  if(!exit&&receipts.length){
   stage='restart-persistence';
   await context.close();await supervisor.stop();await supervisor.start();
   const restored=await browser.newContext({serviceWorkers:'block'});
   expect((await restored.request.post(base+'/api/v1/auth/login',{headers:{Origin:base},data})).status()).toBe(200);
   const streams=await (await restored.request.get(base+'/api/v1/go2rtc/api/streams')).json();
   const cameras=(await (await restored.request.get(base+'/api/v1/cameras')).json()).cameras;
   const studio=await (await restored.request.get(base+'/api/v1/studio')).json();
   for(const receipt of receipts){
    expect(Object.hasOwn(streams,receipt.name)).toBe(true);
    const camera=cameras.find(c=>c.name===receipt.name);expect(camera).toBeTruthy();
    expect(studio.scenes.some(s=>s.name===receipt.name&&s.sources.some(source=>source.cameraId===camera.id))).toBe(true);
    receipt.restartPersistence=true;
   }
   console.log('Named streams, device identity and Studio retained after complete product restart');
   stage='restart-playback';const last=receipts.at(-1),monitor=await restored.newPage();await monitor.goto(base+'/#monitor');
   const wall=monitor.getByLabel(last.name+' 浏览器媒体画面',{exact:true});
   restartVideo=wall;
   await expect.poll(()=>wall.evaluate(v=>v.readyState>=2&&v.videoWidth>0),{timeout:110000}).toBe(true);
   const stamp=await wall.evaluate(v=>v.currentTime);await expect.poll(()=>wall.evaluate(v=>v.currentTime),{timeout:15000}).toBeGreaterThan(stamp+1);
   last.monitorWallAfterRestart=true;console.log('Actual Program monitor wall resumed after complete product restart');
  }
 }catch(error){exit=1;failure={phase:stage,errorType:error.name};
  if(restartVideo)failure.mediaDiagnostic=await restartVideo.evaluate(v=>({readyState:v.readyState,networkState:v.networkState,errorCode:v.error?.code||null,decodedFrames:v.getVideoPlaybackQuality().totalVideoFrames,currentTime:v.currentTime})).catch(()=>null);
  console.error('Native source UI qualification failed: '+stage+' / '+error.name);}
 finally{
  await browser?.close();await supervisor?.stop().catch(()=>{});if(upstream&&upstream.exitCode===null){upstream.stdin.end();await Promise.race([new Promise(resolve=>upstream.once('exit',resolve)),new Promise(resolve=>setTimeout(resolve,5000))]);if(upstream.exitCode===null)upstream.kill();}window?.destroy();
  if(option('--receipt'))await fs.writeFile(path.resolve(option('--receipt')),JSON.stringify({testedAt:new Date().toISOString(),result:exit?'failed':'passed',runtimeRevision:manifestRevision,frontendOverride,frontendEntrySha256,...(failure?{failure}:{}),receipts},null,2));
  app.exit(exit);
 }
})().catch(() => { console.error('Native source UI harness failed'); app.exit(1); });
