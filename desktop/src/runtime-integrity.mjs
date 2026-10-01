import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { readFile, lstat, realpath, readdir } from 'node:fs/promises';
import path from 'node:path';

export const requiredFiles = ['bin/webobsd.exe', 'bin/webobs-job.exe', 'bin/webobs-transcoder.exe', 'bin/webobs-scene-tool.exe',
  'bin/ffmpeg.exe', 'bin/ffprobe.exe', 'bin/openssl.exe', 'bin/go2rtc.exe', 'bin/mediamtx.exe', 'bin/caddy.exe',
  'python/python.exe', 'obs/bin/64bit/obs.dll', 'obs/bin/64bit/libobs-d3d11.dll',
  'obs/obs-plugins/64bit/obs-ffmpeg.dll', 'obs/obs-plugins/64bit/obs-x264.dll', 'obs/obs-plugins/64bit/obs-webrtc.dll',
  'obs/obs-plugins/64bit/image-source.dll', 'obs/obs-plugins/64bit/obs-text.dll',
  'obs/obs-plugins/64bit/obs-browser.dll', 'obs/obs-plugins/64bit/obs-browser-page.exe',
  'bin/msvcp140.dll', 'bin/vcruntime140.dll', 'web/index.html', 'go2rtc-www/index.html',
  'services/runtime_support.py', 'services/desktop-tools/tool_dispatch.py', 'licenses/THIRD-PARTY-NOTICES.md'];
export function containedPath(root, name) {
  if (typeof name !== 'string' || !name || name.includes('\\') || name.includes(':') || path.posix.isAbsolute(name) || name.split('/').some(p => !p || p === '.' || p === '..'))
    throw new Error('Unsafe runtime path');
  const target = path.resolve(root, ...name.split('/'));
  if (!target.startsWith(path.resolve(root) + path.sep)) throw new Error('Runtime path escapes installation');
  return target;
}
export async function digestFile(file, algorithm = 'sha256', encoding = 'hex') {
  const digest = createHash(algorithm);
  for await (const chunk of createReadStream(file)) digest.update(chunk);
  return digest.digest(encoding);
}
export async function inventory(root, prefix = '') {
  const entries = [];
  for (const item of await readdir(path.join(root, prefix), { withFileTypes: true })) {
    const name = prefix ? `${prefix}/${item.name}` : item.name;
    if (item.isSymbolicLink()) throw new Error('Runtime links are prohibited');
    if (item.isDirectory()) entries.push(...await inventory(root, name));
    else if (item.isFile() && name !== 'manifest.json') entries.push({ path: name, sha256: await digestFile(containedPath(root, name)) });
  }
  return entries.sort((a,b) => a.path.localeCompare(b.path));
}
export async function verifyRuntime(root) {
  const canonicalRoot = await realpath(root);
  const manifest = JSON.parse(await readFile(path.join(root, 'manifest.json'), 'utf8'));
  if (manifest.schema !== 1 || manifest.platform !== 'windows-x64' || !Array.isArray(manifest.files) || manifest.files.length > 30000)
    throw new Error('Invalid Windows runtime manifest');
  const names = new Set();
  for (const item of manifest.files) {
    if (!/^[a-f0-9]{64}$/.test(item.sha256) || names.has(item.path)) throw new Error('Invalid or duplicate runtime digest');
    const file = containedPath(root, item.path), info = await lstat(file);
    if (!info.isFile() || info.isSymbolicLink() || !(await realpath(file)).startsWith(canonicalRoot + path.sep)) throw new Error('Runtime file is not a regular installed file');
    if (await digestFile(file) !== item.sha256) throw new Error(`Runtime checksum failed: ${item.path}`);
    names.add(item.path);
  }
  for (const name of requiredFiles) if (!names.has(name)) throw new Error(`Required native component missing: ${name}`);
  const actual = await inventory(root);
  const untracked=actual.filter(item=>!names.has(item.path));
  if (actual.length !== names.size || untracked.length) throw new Error(`Untracked runtime file; rebuild the complete package (${untracked.slice(0,8).map(item=>item.path).join(', ')})`);
  return manifest;
}
