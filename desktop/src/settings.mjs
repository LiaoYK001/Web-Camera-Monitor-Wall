import { readFile, open, rename, mkdir, rm } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
export const defaults = Object.freeze({ autoCheck: true, autoDownload: true, startAtLogin: false, lanEnabled: false,
  lanPort: 18443, recordingDirectory: '', minimizeToTray: true });
export function validateSettings(input, current = defaults) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Invalid desktop settings');
  const next = { ...current };
  for (const [key, value] of Object.entries(input)) {
    if (!(key in defaults)) throw new Error('Unknown desktop setting');
    if (typeof defaults[key] === 'boolean' && typeof value !== 'boolean') throw new Error('Expected a boolean');
    if (key === 'lanPort' && (!Number.isInteger(value) || value < 1024 || value > 65535)) throw new Error('Invalid LAN port');
    if (key === 'recordingDirectory' && (typeof value !== 'string' || value.length > 240 || (value !== '' && !path.isAbsolute(value)))) throw new Error('Recording directory must be absolute');
    next[key] = value;
  }
  return next;
}
export async function atomicJson(file, data) {
  await mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.${randomUUID()}.tmp`;
  try {
    const handle = await open(temporary, 'wx', 0o600);
    try { await handle.writeFile(`${JSON.stringify(data, null, 2)}\n`); await handle.sync(); }
    finally { await handle.close(); }
    await rename(temporary, file);
  } finally { await rm(temporary, { force: true }); }
}
export async function loadSettings(root) {
  try { return validateSettings(JSON.parse(await readFile(path.join(root, 'desktop.json'), 'utf8'))); }
  catch (error) { if (error.code === 'ENOENT') return { ...defaults }; throw error; }
}
