import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtemp, writeFile, mkdir, rm, readFile } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { requiredFiles, inventory, verifyRuntime, containedPath, digestFile } from '../src/runtime-integrity.mjs';
import { defaults, validateSettings, atomicJson } from '../src/settings.mjs';
import { bindPort } from '../src/ports.mjs';
import { privateIPv4, caddyConfiguration, firewallInstructions } from '../src/lan.mjs';
import { projectorOptions, trustedFrame } from '../src/ipc-policy.mjs';
import { UpdateController, updateBlockers } from '../src/updates.mjs';
import { dependencyLock } from '../scripts/lock.mjs';
import { cleanEnvironment } from '../src/supervisor.mjs';
import { qualificationReceipts } from '../scripts/qualification.mjs';
import { verifyPublisher } from '../src/signature.mjs';
import { launchVerifiedInstaller } from '../src/installer.mjs';

async function temporary(t) {const directory=await mkdtemp(path.join(os.tmpdir(),'webobs-desktop-'));t.after(()=>rm(directory,{recursive:true,force:true}));return directory;}
test('desktop defaults and settings reject unbounded or unknown IPC values',()=>{
  assert.equal(defaults.autoCheck,true);assert.equal(defaults.autoDownload,true);assert.equal(defaults.startAtLogin,false);assert.equal(defaults.lanEnabled,false);
  assert.throws(()=>validateSettings({autoCheck:'false'}));assert.throws(()=>validateSettings({command:'calc'}));assert.throws(()=>validateSettings({lanPort:80}));
  assert.equal(validateSettings({autoCheck:false}).autoCheck,false);
});
test('runtime inventory detects alteration, missing components and extra untracked binaries',async t=>{
  const root=await temporary(t);
  for(const file of requiredFiles){const target=containedPath(root,file);await mkdir(path.dirname(target),{recursive:true});await writeFile(target,'fixture');}
  await atomicJson(path.join(root,'manifest.json'),{schema:1,platform:'windows-x64',version:'3.1.0-dev.0',files:await inventory(root)});
  await verifyRuntime(root);
  await writeFile(path.join(root,'bin','go2rtc.exe'),'corrupt');await assert.rejects(verifyRuntime(root),/checksum/);
  await writeFile(path.join(root,'bin','go2rtc.exe'),'fixture');await writeFile(path.join(root,'bin','unexpected.dll'),'fixture');await assert.rejects(verifyRuntime(root),/Untracked/);
  for(const name of ['../escape','a/../escape','C:/secret','a\\b','/outside'])assert.throws(()=>containedPath(root,name));
});
test('occupied port is reported and its owner remains listening',async()=>{
  const owner=await bindPort(0);try{await assert.rejects(bindPort(owner.port),/unavailable/);await assert.rejects(bindPort(owner.port),/unavailable/);}finally{await owner.release();}
});
test('LAN config has no upstream management listener and only admits private hosts',()=>{
  assert.equal(privateIPv4('192.168.1.7'),true);assert.equal(privateIPv4('8.8.8.8'),false);assert.equal(privateIPv4('172.32.1.2'),false);
  const config=caddyConfiguration(['192.168.1.7'],18443,18080,'D:/data/caddy');
  assert.equal(config.admin.disabled,true);assert.deepEqual(config.apps.http.servers.lan.listen,['192.168.1.7:18443']);
  assert.equal(config.apps.pki.certificate_authorities.local.install_trust,false);
  assert.equal(config.apps.http.servers.lan.routes[0].handle[0].upstreams[0].dial,'127.0.0.1:18080');
  assert.throws(()=>caddyConfiguration(['8.8.8.8'],18443,18080,'x'));
  assert.ok(firewallInstructions(18443,18190,18189,['192.168.1.7']).every(line=>line.includes('-Profile Private')));
  const rules=firewallInstructions(18443,18190,18189,['192.168.1.7'],28555);
  assert.equal(rules.length,5);assert.ok(rules.every(line=>line.includes('-RemoteAddress LocalSubnet')));
  assert.ok(rules.filter(line=>line.includes('go2rtc')).every(line=>line.includes('-LocalPort 28555')));
});
test('IPC admits only known top frames, scene identifiers and available displays',()=>{
  const frame={url:'http://127.0.0.1:18080/'};const sender={id:1,mainFrame:frame};const event={sender,senderFrame:frame};
  assert.equal(trustedFrame(event,'http://127.0.0.1:18080',new Set([1])),true);
  assert.equal(trustedFrame({...event,senderFrame:{url:frame.url}},'http://127.0.0.1:18080',new Set([1])),false);
  frame.url='http://127.0.0.1:18080/api/v1/go2rtc/config.html';assert.equal(trustedFrame(event,'http://127.0.0.1:18080',new Set([1])),false);
  assert.throws(()=>projectorOptions({mode:'direct',sceneId:'../file'},[]));assert.throws(()=>projectorOptions({mode:'direct',displayId:999},[{id:1}]));
  assert.equal(projectorOptions({mode:'direct',sceneId:'scene-1',displayId:1,fullscreen:true},[{id:1}]).fullscreen,true);
});
test('runtime discards inherited service, Python and PATH overrides',()=>{
  assert.deepEqual(cleanEnvironment({SystemRoot:'C:/Windows',PATH:'evil',Path:'evil',WEBOBS_HTTP_PORT:'80',MTX_APIADDRESS:'0.0.0.0:9997',PYTHONPATH:'evil',NODE_OPTIONS:'--require evil',GH_TOKEN:'fixture',CSC_KEY_PASSWORD:'fixture'}),{SystemRoot:'C:/Windows'});
});
test('every dependency has an immutable HTTPS identity and digest',async()=>{assert.equal((await dependencyLock()).artifacts.length,14);});
test('Authenticode verification rejects missing, timed-out or mismatched verifiers',async t=>{
  const file=path.join(await temporary(t),"up'date.exe");
  const signature=async(status,publisher='Example publisher',verified=file)=>({stdout:JSON.stringify({status,publisher,path:verified}),stderr:''});
  assert.equal(await verifyPublisher(['Example publisher'],file,()=>signature('Valid')),null);
  assert.notEqual(await verifyPublisher(['Example publisher'],file,()=>signature('Valid','Wrong publisher')),null);
  assert.notEqual(await verifyPublisher(['Example publisher'],file,()=>signature('NotSigned')),null);
  await assert.rejects(verifyPublisher(['Example publisher'],file,async()=>{throw new Error('timeout');}),/timeout/);
  await assert.rejects(verifyPublisher(['Example publisher'],file,()=>signature('Valid','Example publisher',file+'.other')),/different file/);
  await assert.rejects(verifyPublisher(['Example publisher'],file,async()=>({stdout:'',stderr:'unavailable'})),/verifier failed/);
});
test('installer launch waits for the Windows spawn event and rejects asynchronous failure',async t=>{
  const child=new EventEmitter();let detached=false;child.unref=()=>{detached=true;};
  let accepted=false;
  const pending=launchVerifiedInstaller('D:/verified/update.exe',(file,args,options)=>{
    assert.deepEqual(args,['--updated','--force-run']);assert.equal(options.shell,false);return child;
  }).then(()=>{accepted=true;});
  await Promise.resolve();assert.equal(accepted,false);assert.equal(detached,false);
  child.emit('spawn');await pending;assert.equal(accepted,true);assert.equal(detached,true);
  await assert.rejects(launchVerifiedInstaller('D:/verified/update.exe',()=>{
    const failed=new EventEmitter();queueMicrotask(()=>failed.emit('error',new Error('file locked')));return failed;
  }),/file locked/);
  await assert.rejects(launchVerifiedInstaller(path.join(await temporary(t),'missing.exe')),error=>error.code==='ENOENT');
});
test('asynchronous installer rejection retains the current services and data',async t=>{
  let accepted=false;
  const f=await updaterFixture(t,{launchInstaller:async()=>{await Promise.resolve();throw new Error('file locked');},beforeInstall:()=>{accepted=true;}});
  await f.controller.install();assert.equal(accepted,false);assert.equal(f.updater.installs,undefined);
  assert.deepEqual(f.calls,['stop','snapshot','start']);
  await assert.rejects(readFile(path.join(f.root,'pending-update.json')),error=>error.code==='ENOENT');
});
test('build fixtures and incomplete Windows installation evidence cannot authorize release',()=>{assert.throws(()=>qualificationReceipts([],'revision','3.1.0'),/actual installation evidence/);assert.throws(()=>qualificationReceipts([{platform:'windows-10-x64',schema:1,revision:'revision',version:'3.1.0',installerSha256:'a'.repeat(64),operator:'test',evidenceUrl:'test',installedFrom:'3.0.0',updatedTo:'3.1.0',checks:{}}],'revision','3.1.0'),/Unqualified/);});

async function updaterFixture(t, overrides={}) {
  const root=await temporary(t),file=path.join(root,'new.exe');await writeFile(file,'installer-fixture');
  class FakeUpdater extends EventEmitter {async checkForUpdates(){} async downloadUpdate(){} quitAndInstall(){this.installs=(this.installs||0)+1;}}
  const updater=new FakeUpdater();const calls=[];
  const supervisor={async workload(){return {recording:false,streaming:false,exporting:false};},async stop(){calls.push('stop');},async snapshot(){calls.push('snapshot');return path.join(root,'snapshot');},async start(){calls.push('start');},...overrides.supervisor};
  const controller=new UpdateController({updater,official:true,publisher:'Example publisher',packaged:true,settings:{...defaults},root,supervisor,windowWork:()=>[],confirmStop:async()=>true,beforeInstall:()=>calls.push('install'),verifySignature:async()=>null,version:'3.1.0',...overrides,supervisor});
  controller.info={version:'3.2.0',files:[{url:'new.exe',size:17,sha512:await digestFile(file,'sha512','base64')}]};
  updater.emit('update-downloaded',{downloadedFile:file});
  return {controller,updater,calls,root,file};
}
test('updates never install on quit and development packages never query production',async t=>{
  const {controller,updater}=await updaterFixture(t,{official:false});assert.equal(controller.enabled,false);assert.equal(updater.autoInstallOnAppQuit,false);assert.equal(updater.allowPrerelease,false);await controller.install();assert.equal(updater.installs,undefined);
});
test('unpublished drafts and backend exports pause installation',async t=>{
  const f=await updaterFixture(t,{windowWork:()=>[{dirty:true,exporting:false}]});await f.controller.install();assert.deepEqual(f.calls,[]);assert.equal(f.updater.installs,undefined);assert.match(f.controller.state.message,/草稿/);
  assert.ok(updateBlockers([],{recording:false,streaming:false,exporting:true}).some(item=>item.includes('导出')));
  assert.ok(updateBlockers([],null).length);
});
test('active recording or streaming requires explicit confirmation',async t=>{
  const f=await updaterFixture(t,{supervisor:{async workload(){return {recording:true,streaming:true,exporting:false};}},confirmStop:async()=>false});await f.controller.install();assert.deepEqual(f.calls,[]);assert.equal(f.updater.installs,undefined);
});
test('checksum and wrong-publisher failures leave current services running',async t=>{
  const corrupt=await updaterFixture(t);await writeFile(corrupt.file,'broken');await corrupt.controller.install();assert.deepEqual(corrupt.calls,[]);assert.equal(corrupt.updater.installs,undefined);
  const wrong=await updaterFixture(t,{verifySignature:async()=> 'wrong publisher'});await wrong.controller.install();assert.deepEqual(wrong.calls,[]);assert.equal(wrong.updater.installs,undefined);
});
test('normal-stop failure aborts install and restarts current version',async t=>{
  const f=await updaterFixture(t,{supervisor:{async stop(){throw new Error('busy');}}});await f.controller.install();assert.equal(f.updater.installs,undefined);assert.deepEqual(f.calls,['start']);
});
test('installer launch rejection restores running services and removes pending recovery',async t=>{
  const f=await updaterFixture(t);
  f.updater.quitAndInstall=()=>f.updater.emit('error',new Error('installer is locked'));
  await f.controller.install();assert.deepEqual(f.calls,['stop','snapshot','install','start']);
  assert.equal(f.controller.state.phase,'error');
  await assert.rejects(readFile(path.join(f.root,'pending-update.json')),error=>error.code==='ENOENT');
});
test('changed installer during preparation never leaves an installable recovery marker',async t=>{
  const f=await updaterFixture(t);
  let verified=0; const original=f.controller.verifyDownloaded.bind(f.controller);
  f.controller.verifyDownloaded=async(file)=>{verified++;if(verified===3)throw new Error('changed package');return original(file);};
  await f.controller.install();assert.equal(f.updater.installs,undefined);assert.deepEqual(f.calls,['stop','snapshot','start']);
  await assert.rejects(readFile(path.join(f.root,'pending-update.json')),error=>error.code==='ENOENT');
});
test('explicit install stops writers before snapshot and records a recovery mapping',async t=>{
  const f=await updaterFixture(t);await f.controller.install();assert.deepEqual(f.calls,['stop','snapshot','install']);assert.equal(f.updater.installs,1);
  const recovery=JSON.parse(await readFile(path.join(f.root,'pending-update.json'),'utf8'));assert.equal(recovery.from,'3.1.0');assert.equal(recovery.to,'3.2.0');assert.equal(recovery.previousInstaller,null);
});
