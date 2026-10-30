import { readdir, stat } from 'node:fs/promises';
import path from 'node:path';

// The packaged tree is the installed payload. Compressed NSIS download size is
// a different metric, so keep both instead of comparing them interchangeably.
export async function runtimeFootprint(installation) {
  const files = [];
  async function walk(prefix = '') {
    for (const item of await readdir(path.join(installation, prefix), { withFileTypes: true })) {
      const name = prefix ? `${prefix}/${item.name}` : item.name;
      if (item.isSymbolicLink()) throw new Error('Installed footprint cannot contain links');
      if (item.isDirectory()) await walk(name);
      else if (item.isFile()) files.push({ path: name, bytes: (await stat(path.join(installation, name))).size });
    }
  }
  await walk();
  const groups = {};
  for (const file of files) {
    const prefix = 'resources/runtime/';
    const name = file.path.startsWith(prefix) ? `runtime/${file.path.slice(prefix.length).split('/')[0]}` : 'electron-shell';
    const group = groups[name] ??= { bytes: 0, files: 0 };
    group.bytes += file.bytes; group.files++;
  }
  return { schema: 1, installedBytes: files.reduce((sum, file) => sum + file.bytes, 0), fileCount: files.length,
    groups, largestFiles: files.sort((a, b) => b.bytes - a.bytes).slice(0, 25) };
}
