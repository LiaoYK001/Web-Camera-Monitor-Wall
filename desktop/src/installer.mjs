import { spawn } from 'node:child_process';

// The controller supplies only a freshly verified, signed NSIS download.
// Wait for Windows to accept it before quitting: electron-updater's synchronous
// quitAndInstall return value precedes asynchronous spawn errors.
export function launchVerifiedInstaller(file, spawnInstaller = spawn) {
  return new Promise((resolve, reject) => {
    let child;
    try {
      child = spawnInstaller(file, ['--updated', '--force-run'], {
        detached: true, shell: false, stdio: 'ignore', windowsHide: false,
      });
    } catch (error) { reject(error); return; }
    child.once('error', reject);
    child.once('spawn', () => { child.unref(); resolve(); });
  });
}
