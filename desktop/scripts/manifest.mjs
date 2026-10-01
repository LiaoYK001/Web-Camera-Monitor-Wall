import { writeFile, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { inventory, verifyRuntime, digestFile } from '../src/runtime-integrity.mjs';
import { dependencyLock } from './lock.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..','..');
const directory=path.join(root,'desktop','runtime');
const lock=await dependencyLock();
const version=process.env.WEBOBS_DESKTOP_VERSION || JSON.parse(await readFile(path.join(root,'desktop','package.json'),'utf8')).version;
const files=await inventory(directory);
const revision=execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim();
const manifest={schema:1,platform:'windows-x64',version,revision,obsCommit:lock.obsCommit,go2rtcCommit:lock.go2rtcCommit,files};
await writeFile(path.join(directory,'manifest.json'),JSON.stringify(manifest,null,2));
await verifyRuntime(directory);
const components=lock.artifacts.map(item=>({type:'library',name:item.id,version:item.version,hashes:[{alg:'SHA-256',content:item.sha256}],licenses:[{license:{id:item.license.startsWith('LicenseRef-')?'NOASSERTION':item.license}}],externalReferences:[{type:'distribution',url:item.url}]}));
components.push({type:'library',name:'OBS Studio',version:"32.1.2",properties:[{name:'git:commit',value:lock.obsCommit}],licenses:[{license:{id:'GPL-2.0-or-later'}}]});
const desktopPackage=JSON.parse(await readFile(path.join(root,'desktop','package.json'),'utf8'));
for(const [name,version] of Object.entries({...desktopPackage.dependencies,...desktopPackage.devDependencies}))components.push({type:'library',name,version,purl:`pkg:npm/${name}@${version}`});
try {
  const installed=await readFile(path.join(root,'build','desktop-windows','vcpkg-installed','vcpkg','status'),'utf8');
  for(const entry of installed.split(/\r?\n\r?\n/)) {
    const name=/^Package: (.+)$/m.exec(entry)?.[1],version=/^Version: (.+)$/m.exec(entry)?.[1];
    if(name && version)components.push({type:'library',name:`vcpkg:${name}`,version});
  }
} catch(error) { if(error.code!=='ENOENT')throw error; }
// npm dependency identities and integrity values are included without credentials.
const npmLock=await readFile(path.join(root,'desktop','pnpm-lock.yaml'),'utf8');
await writeFile(path.join(directory,'licenses','desktop-pnpm-lock.yaml'),npmLock);
await writeFile(path.join(root,'desktop','runtime-sbom.cdx.json'),JSON.stringify({bomFormat:'CycloneDX',specVersion:'1.6',version:1,metadata:{component:{type:'application',name:'WebOBS',version},properties:[{name:'webobs:revision',value:revision},{name:'webobs:obs-commit',value:lock.obsCommit}]},components},null,2));
// Manifest must include the copied lockfile as well.
manifest.files=await inventory(directory);await writeFile(path.join(directory,'manifest.json'),JSON.stringify(manifest,null,2));
console.log(`Staged and verified ${manifest.files.length} files; manifest SHA-256 ${await digestFile(path.join(directory,'manifest.json'))}`);
