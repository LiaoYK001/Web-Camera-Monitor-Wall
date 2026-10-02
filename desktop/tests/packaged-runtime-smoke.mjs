// Validate the fused ASAR and production dependencies from the actual packaged app.
// Killing the owner here deliberately tests Job cleanup, not a graceful user exit.
import { spawn, execFileSync } from 'node:child_process';
import { mkdir, readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { bindPort } from '../src/ports.mjs';

if(process.platform!=='win32')throw new Error('Requires an actual Windows package');
const desktop=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const version=process.env.WEBOBS_DESKTOP_VERSION || JSON.parse(await readFile(path.join(desktop,'package.json'),'utf8')).version;
const application=path.join(desktop,'out',version,'win-unpacked');
const root=await mkdtemp(path.join(os.tmpdir(),'webobs-packaged-smoke-'));
const data=path.join(root,'WebOBS'), recordings=path.join(root,'Videos','WebOBS');
const powershell=path.join(process.env.SystemRoot,'System32','WindowsPowerShell','v1.0','powershell.exe');
const query=Buffer.from('$ErrorActionPreference="Stop"; $ProgressPreference="SilentlyContinue"; @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($env:WEBOBS_SMOKE_APP,[StringComparison]::OrdinalIgnoreCase) } | Select-Object ProcessId,ParentProcessId) | ConvertTo-Json -Compress','utf16le').toString('base64');
function processes() {
  const output=execFileSync(powershell,['-NoProfile','-NonInteractive','-EncodedCommand',query],{env:{...process.env,WEBOBS_SMOKE_APP:application+path.sep},windowsHide:true,encoding:'utf8',timeout:15000}).trim();
  return output?[JSON.parse(output)].flat():[];
}
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let child, output='', stopped=false;
try {
  assert.deepEqual(processes(),[],'Another process is using this package; close it before validation');
  const lease=await bindPort(18080);await lease.release();
  await mkdir(recordings,{recursive:true});await mkdir(data,{recursive:true});
  // Keep media isolated while exercising the product's actual packaged entry.
  await writeFile(path.join(data,'desktop.json'),JSON.stringify({recordingDirectory:recordings}));
  child=spawn(path.join(application,'WebOBS.exe'),[],{cwd:root,env:{...process.env,LOCALAPPDATA:root,PATH:path.join(process.env.SystemRoot,'System32')},windowsHide:true,stdio:['ignore','pipe','pipe']});
  let failure;
  child.on('error',error=>{failure=error;});
  for(const stream of [child.stdout,child.stderr])stream.on('data',chunk=>{if(output.length<64000)output+=chunk.toString('utf8');});
  const origin='http://127.0.0.1:18080';let healthy=false;
  const deadline=Date.now()+120000;
  while(Date.now()<deadline) {
    if(failure)throw failure;if(child.exitCode!==null)throw new Error(`Packaged application exited (${child.exitCode})`);
    healthy=await fetch(origin+'/api/v1/health',{signal:AbortSignal.timeout(1000)}).then(response=>response.ok).catch(()=>false);
    if(healthy)break;await pause(300);
  }
  assert.ok(healthy,'Packaged native backend did not start');
  const page=await fetch(origin);assert.equal(page.status,200);assert.ok((await page.text()).includes('<html'));
  const credentials={username:'packaged-smoke-admin',password:crypto.randomBytes(24).toString('hex')};
  const request={method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:JSON.stringify(credentials)};
  assert.ok((await fetch(origin+'/api/v1/auth/setup',request)).ok);
  const login=await fetch(origin+'/api/v1/auth/login',request);assert.ok(login.ok);
  const headers={Origin:origin,Cookie:login.headers.getSetCookie().map(value=>value.split(';')[0]).join('; ')};
  for(const route of ['/api/v1/runtime/info','/api/v1/studio','/api/v1/go2rtc/api/streams']) {
    const response=await fetch(origin+route,{headers});assert.equal(response.status,200,route);await response.arrayBuffer();
  }
  // Never end an unrelated process: this is the exact child launched above.
  child.kill();
  const stopDeadline=Date.now()+45000;
  do {
    stopped=processes().length===0;
    if(!stopped)await pause(500);
  } while(!stopped && Date.now()<stopDeadline);
  assert.ok(stopped,'Packaged owner exit left descendants running');
  await assert.rejects(fetch(origin+'/api/v1/health',{signal:AbortSignal.timeout(1000)}));
  console.log('Actual packaged ASAR: clean PATH, first account, authenticated go2rtc and owner-crash Job cleanup passed. NSIS installation and camera qualification remain separate.');
} catch(error) {
  if(output)console.error(output);
  for(const name of ['desktop-startup','native-tools','core','clients']) {
    const log=await readFile(path.join(data,'logs',`${name}.log`),'utf8').catch(()=>'');if(log)console.error(`${name} diagnostic tail:\n${log.slice(-4000)}`);
  }
  throw error;
} finally {
  if(child && child.exitCode===null)child.kill();
  if(stopped && root.startsWith(path.resolve(os.tmpdir())+path.sep+'webobs-packaged-smoke-'))await rm(root,{recursive:true,force:true}).catch(()=>{});
}
