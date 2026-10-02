import { mkdtemp, rm } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require=createRequire(import.meta.url);
const root=await mkdtemp(path.join(os.tmpdir(),'webobs-real-updater-'));
let code=1;
try {
  code=await new Promise((resolve,reject)=>{
    const child=spawn(require('electron'),[fileURLToPath(new URL('./update-download-smoke.cjs',import.meta.url))],
      {env:{...process.env,WEBOBS_UPDATE_SMOKE_ROOT:root},windowsHide:true,stdio:'inherit'});
    child.once('error',reject);child.once('exit',value=>resolve(value??1));
  });
} finally {await rm(root,{recursive:true,force:true,maxRetries:10,retryDelay:200});}
process.exitCode=code;
