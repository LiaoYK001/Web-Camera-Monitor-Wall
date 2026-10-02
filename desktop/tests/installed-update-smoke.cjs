// Real NSIS download/install and native service/data upgrade in an isolated profile.
// The local feed and silent installer launcher are test-only; production uses
// GitHub and the interactive installer after the user's explicit confirmation.
const { app, safeStorage }=require('electron');
const { NsisUpdater }=require('electron-updater');
const fs=require('node:fs/promises');
const { createReadStream }=require('node:fs');
const { spawn }=require('node:child_process');
const http=require('node:http');
const path=require('node:path');
const crypto=require('node:crypto');
const assert=require('node:assert/strict');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));

(async()=>{
  const root=process.env.WEBOBS_UPGRADE_SMOKE_ROOT, installation=process.env.WEBOBS_UPGRADE_SMOKE_INSTALL;
  const artifacts=process.env.WEBOBS_UPGRADE_SMOKE_ARTIFACTS, from=process.env.WEBOBS_UPGRADE_SMOKE_FROM;
  if(!root || !installation || !artifacts || !from)throw new Error('Use the isolated upgrade launcher');
  app.setPath('userData',path.join(root,'electron-harness'));
  let supervisor, controller, server, exitCode=0;
  try {
    await app.whenReady();
    const { Supervisor }=await import('../src/supervisor.mjs');
    const { UpdateController }=await import('../src/updates.mjs');
    const { defaults }=await import('../src/settings.mjs');
    const { verifyUpdateMetadata }=await import('../scripts/update-metadata.mjs');
    const { verifyRuntime }=await import('../src/runtime-integrity.mjs');
    const runtime=path.join(installation,'resources','runtime'), data=path.join(root,'profile','WebOBS');
    const target=process.env.WEBOBS_UPGRADE_SMOKE_VERSION;
    await verifyRuntime(runtime);
    const originalManifest=JSON.parse(await fs.readFile(path.join(runtime,'manifest.json'),'utf8'));
    assert.equal(originalManifest.version,from);
    const settings={...defaults,autoCheck:true,autoDownload:true,recordingDirectory:path.join(root,'Videos','WebOBS')};
    supervisor=new Supervisor({runtime,root:data,videos:path.join(root,'Videos'),settings,version:from,safeStorage});
    await supervisor.start();
    const origin=supervisor.origin;
    const credentials={username:'upgrade-smoke-admin',password:crypto.randomBytes(24).toString('hex')};
    const request={method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:JSON.stringify(credentials)};
    assert.equal((await fetch(origin+'/api/v1/auth/setup',request)).status,201);
    const login=await fetch(origin+'/api/v1/auth/login',request);assert.equal(login.status,200);
    const cookie=login.headers.getSetCookie().map(value=>value.split(';')[0]).join('; ');
    const before=await fetch(origin+'/api/v2/account/preferences/monitor-view',{headers:{Origin:origin,Cookie:cookie}});
    assert.equal(before.status,200);const preferences=await before.json();
    await fs.writeFile(path.join(data,'retained-upgrade.marker'),'preserve this data');
    const info=await verifyUpdateMetadata(artifacts,target);
    const metadata=await fs.readFile(path.join(artifacts,'latest.yml'));
    server=http.createServer((request,response)=>{
      if(request.url.startsWith('/latest.yml'))response.end(metadata);
      else if(request.url.split('?')[0]==='/'+info.installer){response.writeHead(200,{'Content-Length':info.size});createReadStream(path.join(artifacts,info.installer)).pipe(response);}
      else {response.writeHead(404);response.end();}
    });
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    const url=`http://127.0.0.1:${server.address().port}`, config=path.join(root,'app-update.yml');
    await fs.writeFile(config,`provider: generic\nurl: ${url}\nupdaterCacheDirName: upgrade-cache\n`);
    const adapter={version:from,name:'WebOBS upgrade validation',isPackaged:true,userDataPath:path.join(root,'updater'),baseCachePath:root,appUpdateConfigPath:config,whenReady:()=>app.whenReady(),onQuit:()=>{},quit:()=>{},relaunch:()=>{}};
    const updater=new NsisUpdater(null,adapter);
    const { ElectronHttpExecutor }=require(path.join(path.dirname(require.resolve('electron-updater/package.json')),'out','electronHttpExecutor.js'));
    updater.httpExecutor=new ElectronHttpExecutor();updater.setFeedURL({provider:'generic',url});
    updater.logger={info(){},warn(){},error(){},debug(){}};updater.disableDifferentialDownload=true;
    updater.verifyUpdateCodeSignature=async()=>{throw new Error('Unsigned update requested signing');};
    let installed=false;
    controller=new UpdateController({updater,official:true,publisher:null,packaged:true,settings,root:data,supervisor,version:from,
      windowWork:()=>[],confirmStop:async()=>true,beforeInstall:()=>{installed=true;},launchInstaller:file=>new Promise((resolve,reject)=>{
        const child=spawn(file,['/S',`/D=${installation}`],{windowsHide:true,windowsVerbatimArguments:true,stdio:'ignore'});
        child.once('error',reject);child.once('exit',code=>code===0?resolve():reject(new Error(`NSIS update failed (${code})`)));
      })});
    controller.start();
    const deadline=Date.now()+180000;
    while(controller.status().phase!=='downloaded' && Date.now()<deadline){if(controller.status().phase==='error')throw new Error(controller.status().message);await pause(200);}
    assert.equal(controller.status().phase,'downloaded');assert.equal(installed,false,'Download must not install');
    await controller.install();assert.equal(installed,true,controller.status().message);controller.dispose();
    const pending=JSON.parse(await fs.readFile(path.join(data,'pending-update.json'),'utf8'));
    assert.equal(pending.from,from);assert.equal(pending.to,target);assert.ok((await fs.stat(pending.snapshot)).isDirectory());
    await verifyRuntime(runtime);const upgraded=JSON.parse(await fs.readFile(path.join(runtime,'manifest.json'),'utf8'));assert.equal(upgraded.version,target);
    // Exercise the upgraded service payload without launching any user's desktop profile.
    supervisor=new Supervisor({runtime,root:data,videos:path.join(root,'Videos'),settings,version:target,safeStorage});await supervisor.start();
    assert.equal((await fetch(supervisor.origin+'/api/v1/auth/login',request)).status,200);
    const after=await fetch(supervisor.origin+'/api/v2/account/preferences/monitor-view',{headers:{Origin:supervisor.origin,Cookie:cookie}});
    assert.equal(after.status,200);assert.deepEqual(await after.json(),preferences);
    assert.equal(await fs.readFile(path.join(data,'retained-upgrade.marker'),'utf8'),'preserve this data');
    await supervisor.stop();
    await fs.writeFile(path.join(artifacts,'windows-update-smoke.json'),JSON.stringify({schema:1,from,version:target,revision:upgraded.revision,
      installerSha256:crypto.createHash('sha256').update(await fs.readFile(path.join(artifacts,info.installer))).digest('hex'),
      checks:{realUpdaterDownload:'passed',explicitInstall:'passed',nativeStopSnapshot:'passed',nsisUpgrade:'passed',accountDataRetention:'passed',postUpgradeHealth:'passed'},
      qualification:'host smoke with a local feed and silent test launcher; not GitHub delivery, GUI automation, clean-machine or camera qualification'},null,2));
    console.log('Two actual unsigned NSIS versions: real updater detection/download, explicit install, normal native stop, snapshot, upgrade health and account/data retention passed. Local feed/silent launch are test-only.');
  }catch(error){console.error(error);exitCode=1;}
  finally {controller?.dispose();if(supervisor)await supervisor.stop().catch(()=>{});if(server)await new Promise(resolve=>server.close(resolve));app.exit(exitCode);}
})();
