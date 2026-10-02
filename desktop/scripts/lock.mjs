import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
export async function dependencyLock() {
  const file=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..','dependencies.lock.json');
  const lock=JSON.parse(await readFile(file,'utf8'));
  if(lock.schemaVersion!==1 || lock.platform!=='windows-x64')throw new Error('Invalid dependency lock');
  const ids=new Set();
  for(const artifact of lock.artifacts) {
    const url=new URL(artifact.url);
    if(url.protocol!=='https:' || url.username || url.password || !/^[a-f0-9]{64}$/.test(artifact.sha256) || !artifact.version || !artifact.license || ids.has(artifact.id) || /\/latest\//.test(url.pathname))throw new Error('Unlocked or duplicate dependency');
    ids.add(artifact.id);
  }
  return lock;
}
if(process.argv[1]===fileURLToPath(import.meta.url))console.log(`Validated ${(await dependencyLock()).artifacts.length} pinned Windows dependencies`);
