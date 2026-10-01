import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
export const requiredChecks = ['cleanOfflineInstall','login','cameraPlayback','go2rtcImport','multipleScenes','multipleProjectors','audioRestore',
  'weakNetworkToggle','recordingPlayback','trayExitJobCleanup','restartSleepResume','lanHttpsAuthentication','updateTwoInstalledVersions',
  'updateOffline','updateCorruptPackage','updateWrongSignature','updateDiskFull','updateFileLock','matchingSnapshotRecovery','linuxRegression','dockerPodmanRegression'];
export function qualificationReceipts(receipts, revision, version) {
  if(!Array.isArray(receipts))throw new Error('Qualification receipts must be an array');
  for(const platform of ['windows-10-x64','windows-11-x64']) {
    const receipt=receipts.find(item=>item.platform===platform);
    if(!receipt || receipt.schema!==1 || receipt.revision!==revision || receipt.version!==version ||
      !/^[a-f0-9]{64}$/.test(receipt.installerSha256 || '') || !receipt.operator || !receipt.evidenceUrl || !receipt.installedFrom || !receipt.updatedTo || receipt.installedFrom===receipt.updatedTo)
      throw new Error(`Missing actual installation evidence: ${platform}`);
    for(const check of requiredChecks)if(receipt.checks?.[check]!=='passed')throw new Error(`Unqualified Windows release: ${platform}/${check}`);
  }
}
if(process.argv[1]===fileURLToPath(import.meta.url)) {
  qualificationReceipts(JSON.parse(await readFile(process.argv[2],'utf8')),process.argv[3],process.argv[4]);
  console.log('Both Windows installation and media qualification receipts match this revision.');
}
