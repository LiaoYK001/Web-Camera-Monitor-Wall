const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const assert=require('node:assert/strict');
const {createRequire}=require('node:module');
const repo=path.resolve(__dirname,'../..');
const root=fs.realpathSync(process.argv[2]);
assert(root.startsWith(path.join(repo,'build','u-')) && /^u-[a-f0-9]{8}$/.test(path.basename(root)));
assert(!fs.lstatSync(root).isSymbolicLink());
const archive=path.join(root,'客户端 安装','resources','app.asar');
const destination=path.join(root,'previous-app');
assert(!fs.existsSync(destination));
const builderRequire=createRequire(require.resolve('electron-builder/package.json'));
const libraryRequire=createRequire(builderRequire.resolve('app-builder-lib/package.json'));
const asar=libraryRequire('@electron/asar');
const entries=asar.listPackage(archive);
assert(entries.length<30000);
for(const entry of entries){
 const name=entry.replaceAll('\\','/').replace(/^\//,'');
 assert(name && !name.includes(':') && !name.includes('\0') && !name.split('/').some(part=>!part || part==='.' || part==='..'));
 const item=asar.statFile(archive,entry.substring(1),true);
 if(item.link){const link=item.link.replaceAll('\\','/');assert(!path.posix.isAbsolute(link) && !link.split('/').includes('..'));}
}
const packageInfo=JSON.parse(asar.extractFile(archive,'package.json'));
assert.equal(packageInfo.version,process.argv[3]);
asar.extractAll(archive,destination);
const result={schema:1,packageVersion:packageInfo.version,archiveSha256:crypto.createHash('sha256').update(fs.readFileSync(archive)).digest('hex'),entries:entries.length,extractor:'locked @electron/asar 3.4.1 in a separate Node process; exits before the Electron harness; no archive handle kept during NSIS upgrade'};
fs.writeFileSync(path.join(root,'previous-app-extraction.json'),JSON.stringify(result,null,2));
console.log('Previous release code/dependencies extracted and identified; independent reader will exit before upgrade.');

