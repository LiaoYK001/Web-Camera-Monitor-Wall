import { readFile, stat, realpath } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { digestFile } from '../src/runtime-integrity.mjs';
import { stableVersion } from '../src/release-version.mjs';

const require = createRequire(await realpath(new URL('../node_modules/electron-updater/package.json', import.meta.url)));
const { load } = require('js-yaml');

export async function verifyUpdateMetadata(directory, version) {
  if (!stableVersion(version)) throw new Error('Stable update version required');
  const text = await readFile(path.join(directory, 'latest.yml'), 'utf8');
  if (Buffer.byteLength(text) > 65536) throw new Error('Update metadata is too large');
  const info = load(text);
  if (info?.version !== version || !Array.isArray(info.files) || info.files.length !== 1) throw new Error('Update metadata identity mismatch');
  const item = info.files[0];
  if (![ `WebOBS-${version}-windows-x64.exe`, `WebOBS-${version}-windows-x64-UNSIGNED.exe` ].includes(item.url) ||
      !Number.isSafeInteger(item.size) || item.size <= 0 || typeof item.sha512 !== 'string' || !/^[A-Za-z0-9+/]{86}==$/.test(item.sha512) ||
      info.path !== item.url || info.sha512 !== item.sha512 || info.packages) throw new Error('Invalid complete NSIS metadata');
  const installer = path.join(directory, item.url);
  if ((await stat(installer)).size !== item.size || await digestFile(installer, 'sha512', 'base64') !== item.sha512) throw new Error('Installer size or SHA-512 mismatch');
  return { installer: item.url, version, sha512: item.sha512, size: item.size };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  console.log(JSON.stringify(await verifyUpdateMetadata(process.argv[2], process.argv[3])));
}
