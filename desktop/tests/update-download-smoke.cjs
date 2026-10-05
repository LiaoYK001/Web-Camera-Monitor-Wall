// Exercise the pinned real NSIS updater against an isolated local HTTP feed.
// HTTP and the small executable fixture are test-only; production uses GitHub HTTPS.
const { app } = require('electron');
const { NsisUpdater } = require('electron-updater');
const path = require('node:path');
const fs = require('node:fs/promises');
const http = require('node:http');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');

(async () => {
  const root=process.env.WEBOBS_UPDATE_SMOKE_ROOT;
  if(!root || !path.isAbsolute(root))throw new Error('Run through the isolated update smoke launcher');
  app.setPath('userData',path.join(root,'browser'));
  let server, controller, exitCode=0;
  try {
    await app.whenReady();
    const payload=crypto.randomBytes(65536), digest=crypto.createHash('sha512').update(payload).digest('base64');
    let badDigest=true, candidateVersion='4.0.1', blockmapRequests=0;
    server=http.createServer((request,response)=>{
      if(request.url.startsWith('/latest.yml')) {
        const checksum=badDigest?crypto.createHash('sha512').update('corrupt').digest('base64'):digest;
        response.end(`version: ${candidateVersion}\nfiles:\n  - url: WebOBS-${candidateVersion}-windows-x64-UNSIGNED.exe\n    size: ${payload.length}\n    sha512: ${checksum}\npath: WebOBS-${candidateVersion}-windows-x64-UNSIGNED.exe\nsha512: ${checksum}\n`);
      } else if(request.url.includes('.blockmap')) {
        blockmapRequests++;response.writeHead(404);response.end();
      } else if(request.url.startsWith(`/WebOBS-${candidateVersion}-windows-x64-UNSIGNED.exe`)) {
        response.writeHead(200,{'Content-Length':payload.length});response.end(payload);
      } else {response.writeHead(404);response.end();}
    });
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    const url=`http://127.0.0.1:${server.address().port}`;
    const config=path.join(root,'app-update.yml');
    await fs.writeFile(config,`provider: generic\nurl: ${url}\nupdaterCacheDirName: isolated-cache\n`);
    const adapter={version:'4.0.0',name:'WebOBS updater validation',isPackaged:true,userDataPath:root,baseCachePath:root,appUpdateConfigPath:config,whenReady:()=>app.whenReady(),onQuit:()=>{},quit:()=>{},relaunch:()=>{}};
    const updater=new NsisUpdater(null,adapter);
    const { ElectronHttpExecutor }=require(path.join(path.dirname(require.resolve('electron-updater/package.json')),'out','electronHttpExecutor.js'));
    updater.httpExecutor=new ElectronHttpExecutor();
    updater.setFeedURL({provider:'generic',url});
    updater.logger={info(){},warn(){},error(){},debug(){}};
    updater.disableDifferentialDownload=false;
    updater.verifyUpdateCodeSignature=async()=>{throw new Error('Unsigned updater must not invoke Authenticode');};
    const { UpdateController }=await import('../src/updates.mjs');
    controller=new UpdateController({updater,official:true,publisher:null,packaged:true,settings:{autoCheck:false,autoDownload:false},root,version:'4.0.0'});
    assert.equal(controller.enabled,true);assert.equal(updater.autoInstallOnAppQuit,false);
    await controller.check();assert.equal(controller.status().phase,'available');assert.equal(controller.status().kind,'patch');
    await controller.download();assert.equal(controller.status().phase,'error','Corrupted installer digest must fail');
    badDigest=false;
    await controller.check();await controller.download();
    assert.equal(controller.status().phase,'downloaded');
    const file=await controller.verifyDownloaded();
    assert.equal(crypto.createHash('sha512').update(await fs.readFile(file)).digest('base64'),digest);
    await fs.writeFile(file,'changed after download');
    await assert.rejects(controller.verifyDownloaded(),/SHA-512/);
    candidateVersion='4.0.2';
    await controller.check();assert.equal(controller.status().version,'4.0.2');
    await controller.download();assert.equal(controller.status().phase,'downloaded');
    await controller.verifyDownloaded();
    assert.ok(blockmapRequests>0,'Missing blockmaps must exercise differential-to-full fallback');
    candidateVersion='4.0.0';
    await controller.check();assert.equal(controller.status().phase,'current');assert.equal(controller.status().version,undefined);
    await new Promise(resolve=>server.close(resolve));server=null;
    await controller.check();assert.equal(controller.status().phase,'error');
    console.log('Real unsigned NSIS updater: v4 patch detection/download, missing-blockmap full fallback, corruption rejection, revalidation, no downgrade, offline retry and no install-on-quit passed. This is a protocol fixture, not an installed upgrade.');
  } catch(error) {console.error(error);exitCode=1;}
  finally {
    controller?.dispose();if(server)await new Promise(resolve=>server.close(resolve));
    app.exit(exitCode);
  }
})();
