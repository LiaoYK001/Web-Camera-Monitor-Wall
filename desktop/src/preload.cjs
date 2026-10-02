const { contextBridge, ipcRenderer } = require('electron');
const invoke = (operation, value) => ipcRenderer.invoke('webobs:desktop', operation, value);
contextBridge.exposeInMainWorld('webobsDesktop', Object.freeze({
  version: 1,
  status: () => invoke('status'),
  settings: () => invoke('settings'),
  saveSettings: changes => invoke('settings.save', changes),
  chooseRecordingDirectory: () => invoke('recordings.choose'),
  displays: () => invoke('displays'),
  projector: options => invoke('projector', options),
  checkUpdate: () => invoke('update.check'),
  downloadUpdate: () => invoke('update.download'),
  installUpdate: () => invoke('update.install'),
  restartServices: () => invoke('services.restart'),
  backup: () => invoke('backup'),
  restore: () => invoke('restore'),
  restorePrevious: () => invoke('recovery.restore'),
  openPreviousInstaller: () => invoke('recovery.installer'),
  reportWork: work => invoke('workspace.work', work),
  onStatus: callback => {
    if(typeof callback !== 'function') throw new TypeError('Expected a callback');
    const listener = (_event, value) => callback(value);
    ipcRenderer.on('webobs:desktop-status',listener);
    return () => ipcRenderer.removeListener('webobs:desktop-status',listener);
  },
}));
