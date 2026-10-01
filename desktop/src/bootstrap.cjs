// Catch entry-module failures before the normal diagnostics window can load.
const { app, dialog } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(process.env.LOCALAPPDATA || app.getPath('appData'), 'WebOBS');
app.setPath('userData', root);
app.setPath('sessionData', path.join(root, 'browser'));
const startupLog = path.join(root, 'logs', 'desktop-startup.log');
try { fs.mkdirSync(path.dirname(startupLog), {recursive:true}); fs.writeFileSync(startupLog,'Loading desktop entry\n',{mode:0o600}); } catch {}
app.once('ready', () => { try { fs.appendFileSync(startupLog,'Electron ready\n'); } catch {} });
module.exports = import('./main.mjs').catch(error => {
  const log = startupLog;
  try {
    fs.mkdirSync(path.dirname(log), { recursive: true });
    fs.writeFileSync(log, String(error.stack || error).slice(0, 64000), { mode: 0o600 });
  } catch {}
  console.error(error.stack || error);
  dialog.showErrorBox('WebOBS 无法启动', `请重新安装完整客户端；若仍失败，请查看：\n${log}\n\n${error.message}`);
  app.exit(1);
});
