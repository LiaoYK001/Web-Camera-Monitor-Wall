import { writeFile, readFile, realpath, readdir, mkdir, cp } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
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
const components=lock.artifacts.map(item=>({type:'library',name:item.id,version:item.version,hashes:[{alg:'SHA-256',content:item.sha256}],licenses:[item.license.includes(' OR ')?{expression:item.license}:{license:{id:item.license.startsWith('LicenseRef-')?'NOASSERTION':item.license}}],externalReferences:[{type:'distribution',url:item.url}]}));
components.push({type:'library',name:'OBS Studio',version:"32.1.2",properties:[{name:'git:commit',value:lock.obsCommit}],licenses:[{license:{id:'GPL-2.0-or-later'}}]});
const desktopPackage=JSON.parse(await readFile(path.join(root,'desktop','package.json'),'utf8'));
for(const [name,version] of Object.entries({...desktopPackage.dependencies,...desktopPackage.devDependencies}))components.push({type:'library',name,version,purl:`pkg:npm/${name}@${version}`});
for(const [project,receipt] of [['desktop','npm-licenses.json'],['web','web-npm-licenses.json']]) {
const npmLicenses=JSON.parse((await readFile(path.join(root,'desktop','.cache',receipt),'utf8')).replace(/^\uFEFF/,''));
const npmRoot=await realpath(path.join(root,project,'node_modules'));
for(const [license,packages] of Object.entries(npmLicenses))for(const item of packages) {
  for(const version of item.versions) {
    const existing=components.find(component=>component.name===item.name && component.version===version);
    if(existing)existing.licenses=[{expression:license}];
    else components.push({type:'library',name:item.name,version,purl:`pkg:npm/${item.name}@${version}`,licenses:[{expression:license}]});
  }
  for(const packagePath of item.paths) {
    const actual=await realpath(packagePath);
    if(!actual.startsWith(npmRoot+path.sep))throw new Error('npm license path escapes installed dependencies');
    const target=path.join(directory,'licenses',project+'-npm',encodeURIComponent(item.name));await mkdir(target,{recursive:true});
    for(const file of await readdir(actual))if(/^(license|copying|notice)([._-]|$)/i.test(file))await cp(path.join(actual,file),path.join(target,file),{recursive:true});
  }
}
await cp(path.join(root,project,'pnpm-lock.yaml'),path.join(directory,'licenses',project+'-pnpm-lock.yaml'));
}
for(const name of await readdir(path.join(directory,'go2rtc-www','vendor'))) {
  const item=JSON.parse(await readFile(path.join(directory,'go2rtc-www','vendor',name,'package.json'),'utf8'));
  const license=typeof item.license==='string'?item.license:item.licenses?.map(value=>value.type).join(' OR ');
  if(!license)throw new Error(`Missing bundled go2rtc vendor license: ${name}`);
  if(!components.some(component=>component.name===item.name && component.version===item.version))
    components.push({type:'library',name:item.name,version:item.version,purl:`pkg:npm/${item.name}@${item.version}`,licenses:[{expression:license}]});
}
// Electron 44 downloads its distribution lazily on the first require/CLI run.
const electronDist=path.dirname(createRequire(path.join(root,'desktop','package.json'))('electron'));
for(const file of ['LICENSE','LICENSES.chromium.html']) {
  const target=path.join(directory,'licenses','electron');await mkdir(target,{recursive:true});
  await cp(path.join(electronDist,file),path.join(target,file));
}
try {
  const installed=await readFile(path.join(root,'build','desktop-windows','vcpkg-installed','vcpkg','status'),'utf8');
  for(const entry of installed.split(/\r?\n\r?\n/)) {
    const name=/^Package: (.+)$/m.exec(entry)?.[1],version=/^Version: (.+)$/m.exec(entry)?.[1];
    if(name && version)components.push({type:'library',name:`vcpkg:${name}`,version});
  }
} catch(error) { if(error.code!=='ENOENT')throw error; }
// npm dependency identities and integrity values are included without credentials.
await writeFile(path.join(root,'desktop','runtime-sbom.cdx.json'),JSON.stringify({bomFormat:'CycloneDX',specVersion:'1.6',version:1,metadata:{component:{type:'application',name:'WebOBS',version},properties:[{name:'webobs:revision',value:revision},{name:'webobs:obs-commit',value:lock.obsCommit}]},components},null,2));
// Manifest must include the copied lockfile as well.
manifest.files=await inventory(directory);await writeFile(path.join(directory,'manifest.json'),JSON.stringify(manifest,null,2));
console.log(`Staged and verified ${manifest.files.length} files; manifest SHA-256 ${await digestFile(path.join(directory,'manifest.json'))}`);
