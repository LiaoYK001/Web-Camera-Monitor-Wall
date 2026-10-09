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
 let supervisor,browser,window,upstream,manifestRevision,frontendEntrySha256,frontendOverride,exit=0;const receipts=[];
 try{
  await app.whenReady();window=new BrowserWindow({show:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}});await window.loadURL('data:text/html,<title>Public online qualification</title>');
  const runtime=path.resolve(option('--runtime')||path.join(root,'desktop/runtime'));
  const frontend=option('--frontend')&&path.resolve(option('--frontend'));
  const external=option('--sources')&&JSON.parse(await fs.readFile(option('--sources'),'utf8'));
  if(external&&(!Array.isArray(external)||external.length<1||external.length>8||external.some(s=>!/^[-a-z0-9]{1,64}$/.test(s.name)||!['auto','yt-dlp','streamlink','direct'].includes(s.engine)||!/^https?:\/\//.test(s.address))))throw new Error('Supply 1-8 explicitly selected public sources');
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
  // Exercise the current production frontend with the actual authenticated native services.
  if(frontend)await page.route(base+'/**',async route=>{
   const u=new URL(route.request().url());if(u.pathname.startsWith('/api/'))return route.continue();
   const relative=u.pathname==='/'?'index.html':u.pathname.slice(1);const target=path.resolve(frontend,relative);
   if(!target.startsWith(frontend+path.sep))return route.continue();
   const body=await fs.readFile(target).catch(()=>null);if(!body)return route.continue();
   const ext=path.extname(target);await route.fulfill({body,contentType:ext==='.js'?'application/javascript':ext==='.css'?'text/css':ext==='.html'?'text/html':'application/octet-stream'});
  });
  for(const {name,address,engine} of external||[{name:'private-rtsp',address:rtspAddress,engine:'auto'}]){
   const start=Date.now();let phase='form';
   try{
    await page.goto(base+'/#go2rtc');const form=page.getByRole('region',{name:'网站与直播源'});
    await form.getByLabel('接入方式').selectOption(engine);await form.getByLabel('流名称',{exact:true}).fill(name);await form.getByLabel('视频网页或直播地址').fill(address);
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
    await management.close();receipts.push({name,address:external?address:'[private authenticated RTSP fixture]',engine,result:'passed',dimensions,seconds:Math.round((Date.now()-start)/1000),deviceImported:true,coldImport:true,studioPersisted:true});
   }catch(error){receipts.push({name,address:external?address:'[private authenticated RTSP fixture]',engine,result:'failed',phase,errorType:error.name,seconds:Math.round((Date.now()-start)/1000)});exit=1;await page.screenshot({path:path.join(temporary,name+'-failed.png')}).catch(()=>{});}
   console.log(JSON.stringify(receipts.at(-1)));
  }
  if(!exit&&receipts.length){
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
  }
 }catch(error){exit=1;console.error('Native source UI qualification failed: '+error.name);}
 finally{
  await browser?.close();await supervisor?.stop().catch(()=>{});if(upstream&&upstream.exitCode===null){upstream.stdin.end();await Promise.race([new Promise(resolve=>upstream.once('exit',resolve)),new Promise(resolve=>setTimeout(resolve,5000))]);if(upstream.exitCode===null)upstream.kill();}window?.destroy();
  if(option('--receipt'))await fs.writeFile(path.resolve(option('--receipt')),JSON.stringify({testedAt:new Date().toISOString(),result:exit?'failed':'passed',runtimeRevision:manifestRevision,frontendOverride,frontendEntrySha256,receipts},null,2));
  app.exit(exit);
 }
})().catch(() => { console.error('Native source UI harness failed'); app.exit(1); });
