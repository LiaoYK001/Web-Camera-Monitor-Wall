import { mkdtemp, rm } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const root = await mkdtemp(path.join(os.tmpdir(), 'webobs-source-ui-'));
try {
  process.exitCode = await new Promise((resolve, reject) => {
    const child = spawn(require('electron'), [fileURLToPath(new URL('./online-source-native.cjs', import.meta.url)), ...process.argv.slice(2)],
      { env: { ...process.env, WEBOBS_SOURCE_UI_ROOT: root }, windowsHide: true, stdio: 'inherit' });
    const timer = setTimeout(() => child.kill(), process.argv.includes('--sources') ? 15 * 60_000 : 4 * 60_000);
    child.once('error', error => { clearTimeout(timer); reject(error); });
    child.once('exit', code => { clearTimeout(timer); resolve(code ?? 1); });
  });
} finally {
  // Electron must exit before Windows releases its browser databases.
  if (process.exitCode === 0) await rm(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  else console.error(`Source UI check failed; private diagnostic profile retained: ${root}`);
}
