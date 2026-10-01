import { app, BrowserWindow, Tray, Menu, ipcMain, dialog, screen, session, nativeImage, powerMonitor, safeStorage, shell } from 'electron';
import electronUpdater from 'electron-updater';
import { readFile, writeFile, rename, rm, cp, stat, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { Supervisor } from './supervisor.mjs';
import { UpdateController } from './updates.mjs';
import { loadSettings, validateSettings, atomicJson } from './settings.mjs';
import { verifyRuntime, digestFile } from './runtime-integrity.mjs';
import { trustedFrame, projectorOptions } from './ipc-policy.mjs';
import { verifyPublisher } from './signature.mjs';

const source = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(process.env.LOCALAPPDATA || app.getPath('appData'),'WebOBS');
app.setPath('userData',root);app.setPath('sessionData',path.join(root,'browser'));
if(!app.requestSingleInstanceLock())app.quit();
else {
  let main, tray, supervisor, updates, settings, quitting=false, operating=false, recovery;
  const knownContents=new Set(), projectors=new Map(), work=new Map();
  const diagnosticUrl=pathToFileURL(path.join(source,'diagnostics.html')).href;
  const status=()=>({runtime:supervisor?.status() || {phase:'starting'},update:updates?.status() || {phase:'disabled'},settings,recovery:recovery?{from:recovery.from,to:recovery.to,hasInstaller:Boolean(recovery.previousInstaller),snapshot:recovery.snapshot}:null});
  const broadcast=()=>{for(const win of BrowserWindow.getAllWindows())if(!win.isDestroyed())win.webContents.send('webobs:desktop-status',status());};
  const securePreferences={preload:path.join(source,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true,webSecurity:true,partition:'persist:webobs-desktop'};
  function configureWindow(win,desktop=true) {
    if(desktop)knownContents.add(win.webContents.id);
    win.on('closed',()=>{knownContents.delete(win.webContents.id);work.delete(win.webContents.id);});
    win.webContents.on('will-navigate',(event,url)=>{try{if(new URL(url).origin!==supervisor?.origin && url!==diagnosticUrl)event.preventDefault();}catch{event.preventDefault();}});
    win.webContents.setWindowOpenHandler(({url})=>{
      try {
        const target=new URL(url);
        if(target.origin===supervisor?.origin && target.pathname==='/' && /^#projector(?:-composite)?(?:\?scene=[A-Za-z0-9%._-]+)?$/.test(target.hash)) {
          const mode=target.hash.startsWith('#projector-composite')?'composite':'direct';const sceneId=new URLSearchParams(target.hash.split('?')[1]||'').get('scene')||undefined;
          openProjector({mode,sceneId});return {action:'deny'};
        }
        if(target.origin===supervisor?.origin && target.pathname.startsWith('/api/v1/go2rtc/')) {
          const child=new BrowserWindow({width:1100,height:800,webPreferences:{...securePreferences,preload:undefined}});configureWindow(child,false);
          // The upstream editor has no product IPC. An open configuration window
          // conservatively blocks installation until its user saves and closes it.
          if(target.pathname.endsWith('/config.html'))work.set(child.webContents.id,{dirty:true,exporting:false});
          void child.loadURL(url);return {action:'deny'};
        }
        if(target.protocol==='https:' && !target.username && !target.password && ['github.com','www.electron.build','docs.webobs.org'].includes(target.hostname))void shell.openExternal(target.href);
      }catch{}
      return {action:'deny'};
    });
  }
  function showMain(){if(!main || main.isDestroyed())return;main.show();main.restore();main.focus();}
  function openProjector(options) {
    const displays=screen.getAllDisplays();projectorOptions(options,displays);
    const key=`${options.mode}:${options.sceneId||'program'}:${options.displayId??'window'}`;
    const existing=projectors.get(key);if(existing && !existing.isDestroyed()){existing.show();existing.focus();return {id:existing.id};}
    const display=displays.find(item=>item.id===options.displayId),bounds=display?.bounds;
    const win=new BrowserWindow({title:'WebOBS 场景投影',width:960,height:540,...(bounds?{x:bounds.x,y:bounds.y,width:bounds.width,height:bounds.height}:{}),
      fullscreen:Boolean(options.fullscreen),autoHideMenuBar:true,backgroundColor:'#000000',webPreferences:securePreferences});
    configureWindow(win);projectors.set(key,win);win.on('closed',()=>projectors.delete(key));
    win.webContents.on('before-input-event',(event,input)=>{if(input.key==='Escape' && win.isFullScreen()){event.preventDefault();win.setFullScreen(false);}});
    void win.loadURL(`${supervisor.origin}/${options.mode==='composite'?'#projector-composite':'#projector'}${options.sceneId?`?scene=${encodeURIComponent(options.sceneId)}`:''}`);
    return {id:win.id};
  }
  async function quit() {
    if(operating || quitting)return;
    const dirty=[...work.values()].some(item=>item.dirty || item.exporting);
    if(dirty){showMain();await dialog.showMessageBox(main,{type:'info',message:'先保存草稿或完成导出，再退出并停止服务。'});return;}
    operating=true;
    try{await supervisor?.stop();quitting=true;updates?.dispose();app.quit();}
    catch(error){await dialog.showMessageBox(main,{type:'error',message:error.message,detail:'服务已停止或被 Job Object 收束。查看日志后可重试退出。'});}
    finally{operating=false;}
  }
  app.on('second-instance',showMain);
  app.on('window-all-closed',()=>{});
  app.on('before-quit',event=>{if(!quitting){event.preventDefault();void quit();}});
  await app.whenReady();
  if(process.platform!=='win32' || process.arch!=='x64'){dialog.showErrorBox('WebOBS','阶段一桌面客户端仅支持 Windows 10/11 x64。');quitting=true;app.quit();}
  else {
    main=new BrowserWindow({title:'WebOBS',width:1440,height:950,minWidth:900,minHeight:600,backgroundColor:'#0b0d12',autoHideMenuBar:true,webPreferences:securePreferences});configureWindow(main);
    main.on('close',event=>{if(!quitting && settings?.minimizeToTray!==false){event.preventDefault();main.hide();}else if(!quitting){event.preventDefault();void quit();}});
    const trayIcon=nativeImage.createFromDataURL('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAHklEQVQ4T2P8/5/hPwMlgImBQjBqAMGogTEDmRkwAACMVgQdCmNoVQAAAABJRU5ErkJggg==');
    tray=new Tray(trayIcon);tray.setToolTip('WebOBS · 本机监控墙');tray.on('double-click',showMain);
    tray.setContextMenu(Menu.buildFromTemplate([{label:'显示主窗口',click:showMain},{label:'检查更新',click:()=>{showMain();void updates?.check();}},{type:'separator'},{label:'退出并停止服务',click:()=>void quit()}]));
    await main.loadFile(path.join(source,'diagnostics.html'));
    const desktopSession=session.fromPartition('persist:webobs-desktop');
    desktopSession.setPermissionRequestHandler((contents,permission,callback)=>{
      let trusted=false;try{trusted=knownContents.has(contents.id) && new URL(contents.getURL()).origin===supervisor?.origin;}catch{}
      callback(trusted && ['media','speaker-selection','fullscreen'].includes(permission));
    });
    desktopSession.setPermissionCheckHandler((contents,permission,origin)=>knownContents.has(contents?.id) && origin===supervisor?.origin && ['media','speaker-selection','fullscreen'].includes(permission));
    ipcMain.handle('webobs:desktop',async(event,operation,value)=>{
      if(!trustedFrame(event,supervisor?.origin,knownContents,diagnosticUrl))throw new Error('Untrusted desktop IPC sender');
      if(operation==='status')return status();
      if(operation==='settings')return settings;
      if(operation==='workspace.work'){
        if(!value || Object.keys(value).some(key=>!['dirty','exporting'].includes(key)) || typeof value.dirty!=='boolean' || typeof value.exporting!=='boolean')throw new Error('Invalid workspace state');
        work.set(event.sender.id,value);return null;
      }
      if(operation==='displays')return screen.getAllDisplays().map(display=>({id:display.id,label:display.label || `显示器 ${display.id}`,bounds:display.bounds,primary:screen.getPrimaryDisplay().id===display.id}));
      if(operation==='projector'){if(supervisor.state.phase!=='ready')throw new Error('Services are unavailable');return openProjector(value);}
      if(operation==='update.check')return updates?.check();
      if(operation==='update.download'){await updates?.download();return status();}
      if(operation==='update.install')return updates?.install();
      if(operating || updates?.installing)throw new Error('Another desktop operation is running');
      operating=true;
      try {
        if(operation==='settings.save'){
          if(value && 'recordingDirectory' in value)throw new Error('Use the directory picker');
          const next=validateSettings(value,settings);await atomicJson(path.join(root,'desktop.json'),next);settings=next;
          app.setLoginItemSettings({openAtLogin:settings.startAtLogin});if(updates)updates.settings=settings;broadcast();return settings;
        }
        if(operation==='recordings.choose'){
          const choice=await dialog.showOpenDialog(main,{title:'选择录像目录',defaultPath:supervisor.recordings,properties:['openDirectory','createDirectory']});
          if(choice.canceled)return settings;settings=validateSettings({recordingDirectory:choice.filePaths[0]},settings);await atomicJson(path.join(root,'desktop.json'),settings);broadcast();return settings;
        }
        if(operation==='services.restart'){
          if([...work.values()].some(item=>item.dirty || item.exporting))throw new Error('先保存草稿并完成导出');
          const result=await dialog.showMessageBox(main,{type:'question',buttons:['重启服务','取消'],defaultId:1,cancelId:1,message:'重启会短暂中断录像、媒体和投影。继续？'});
          if(result.response!==0)return status();await supervisor.stop();supervisor.settings=settings;supervisor.recordings=settings.recordingDirectory || path.join(app.getPath('videos'),'WebOBS');await supervisor.start();await main.loadURL(supervisor.origin);return status();
        }
        if(operation==='backup' || operation==='restore'){
          if([...work.values()].some(item=>item.dirty || item.exporting))throw new Error('先保存草稿并完成导出');
          const choice=operation==='restore'?await dialog.showOpenDialog(main,{title:'选择 WebOBS 加密备份（需原备份密钥）',properties:['openFile'],filters:[{name:'WebOBS backup',extensions:['wobk']}]}):null;
          if(choice?.canceled)return status();
          const result=await dialog.showMessageBox(main,{type:'question',buttons:[operation==='restore'?'备份当前数据并恢复':'停止任务并备份','取消'],defaultId:1,cancelId:1,message:operation==='restore'?'恢复将替换当前配置与账号，请确认备份及密钥来源。':'将暂时停止服务，创建加密备份，再恢复运行。'});
          if(result.response!==0)return status();
          // Keep the temporary key while the services are stopped for this explicitly requested operation.
          let key=safeStorage.decryptString(await readFile(path.join(root,'backup-key.dpapi')));
          if(operation==='restore') {
            const keySource=await dialog.showMessageBox(main,{type:'question',buttons:['选择原备份密钥文件','使用本机密钥','取消'],defaultId:2,cancelId:2,message:'从 Docker / WSL 导入需选择创建该备份时使用的 32 字节原始密钥文件。'});
            if(keySource.response===2)return status();
            if(keySource.response===0){const selectedKey=await dialog.showOpenDialog(main,{title:'选择原始备份密钥',properties:['openFile']});if(selectedKey.canceled)return status();const bytes=await readFile(selectedKey.filePaths[0]);if(bytes.length!==32)throw new Error('原备份密钥必须为 32 字节');key=bytes.toString('hex');}
          }
          await supervisor.stop();await writeFile(path.join(root,'run','backup.key'),Buffer.from(key,'hex'),{mode:0o600});
          try {
            await supervisor.snapshot();
            await supervisor.tool('backup/encrypted_backup.py',[operation==='backup'?'create':'restore',...(choice?[choice.filePaths[0]]:[])],300000);
            if(operation==='restore')await writeFile(path.join(root,'backup-key.dpapi'),safeStorage.encryptString(key),{mode:0o600});
          } finally {await rm(path.join(root,'run','backup.key'),{force:true});await supervisor.start();await main.loadURL(supervisor.origin);}
          return status();
        }
        if(operation==='recovery.restore'){
          if(!recovery?.snapshot)throw new Error('No matching pre-update snapshot');
          const result=await dialog.showMessageBox(main,{type:'warning',buttons:['恢复匹配数据快照','取消'],defaultId:1,cancelId:1,message:`恢复 ${recovery.from} 的数据？当前配置将另存。请先安装对应旧版本。`});
          if(result.response!==0)return status();if(app.getVersion()!==recovery.from)throw new Error('请先安装对应上一版本，再恢复其数据快照。');
          await supervisor.stop().catch(()=>{});const staging=path.join(root,`restore-${Date.now()}`);
          await supervisor.tool('desktop-tools/snapshot.py',['restore','--data',staging,'--recordings',supervisor.recordings,'--snapshot',recovery.snapshot],300000);
          const previousData=`${supervisor.data}.before-restore-${Date.now()}`;
          await rename(supervisor.data,previousData);
          try{await rename(staging,supervisor.data);}catch(error){await rename(previousData,supervisor.data);throw error;}
          await rm(path.join(root,'pending-update.json'),{force:true});recovery=null;await supervisor.start();await main.loadURL(supervisor.origin);return status();
        }
        if(operation==='recovery.installer'){
          if(!recovery?.previousInstaller)throw new Error('首个安装版本无缓存旧包，请从对应 GitHub Release 下载签名安装包。');
          const result=await dialog.showMessageBox(main,{type:'question',buttons:['打开上一版本安装包','取消'],defaultId:1,cancelId:1,message:'安装旧版本后重新打开恢复界面，再恢复匹配数据快照。'});
          if(result.response===0){
            const expected=path.join(root,'installers',`WebOBS-${recovery.from}-windows-x64.exe`);
            if(recovery.previousInstaller!==expected || !/^[a-f0-9]{64}$/.test(recovery.previousInstallerSha256) || await digestFile(expected)!==recovery.previousInstallerSha256)throw new Error('上一版本安装包路径或摘要不匹配，请从对应 Release 重新下载。');
            const distribution=JSON.parse(await readFile(path.join(source,'distribution.json'),'utf8'));
            if(!distribution.official || !distribution.publisher || await verifyPublisher([distribution.publisher],expected)!==null)throw new Error('上一版本安装包发布者签名验证失败。');
            const error=await shell.openPath(expected);if(error)throw new Error(error);
          }
          return status();
        }
        throw new Error('Unknown desktop operation');
      } finally {operating=false;broadcast();}
    });
    try {
      settings=await loadSettings(root);app.setLoginItemSettings({openAtLogin:settings.startAtLogin});const runtime=app.isPackaged?path.join(process.resourcesPath,'runtime'):path.resolve(source,'..','runtime');
      await verifyRuntime(runtime);
      supervisor=new Supervisor({runtime,root,videos:app.getPath('videos'),settings,version:app.getVersion(),safeStorage});supervisor.on('status',broadcast);
      try{recovery=JSON.parse(await readFile(path.join(root,'pending-update.json'),'utf8'));}catch(error){if(error.code!=='ENOENT')throw error;}
      if(recovery && ![recovery.to,recovery.from].includes(app.getVersion()))throw new Error('安装版本与升级快照不匹配，请从对应 Release 恢复。');
      if(recovery && app.getVersion()===recovery.from)throw new Error('检测到待恢复的数据快照，请先选择恢复匹配数据，再启动旧版本。');
      await supervisor.start();
      // A persistent desktop partition is shared by the wall and every projector.
      await desktopSession.clearStorageData({storages:['serviceworkers','cachestorage']});
      const distribution=JSON.parse(await readFile(path.join(source,'distribution.json'),'utf8'));
      const {autoUpdater}=electronUpdater;
      autoUpdater.verifyUpdateCodeSignature=verifyPublisher;
      updates=new UpdateController({updater:autoUpdater,official:distribution.official,publisher:distribution.publisher,packaged:app.isPackaged,settings,root,supervisor,version:app.getVersion(),
        windowWork:()=>[...work.values()],confirmStop:async()=>{const result=await dialog.showMessageBox(main,{type:'question',buttons:['停止任务并更新','稍后'],defaultId:1,cancelId:1,message:'更新需要正常停止当前录像和媒体发布。',detail:'已完成的录像与账号配置会保留，未保存草稿和正在导出的任务会阻止安装。'});return result.response===0;},
        verifySignature:verifyPublisher,beforeInstall:()=>{quitting=true;updates.dispose();}});
      updates.on('status',broadcast);updates.start();
      if(recovery){await atomicJson(path.join(root,'installed-version.json'),{version:app.getVersion(),installer:recovery.installer,installerSha256:recovery.installerSha256});await rm(path.join(root,'pending-update.json'),{force:true});recovery=null;}
      await main.loadURL(supervisor.origin);broadcast();
      powerMonitor.on('resume',()=>{void fetch(`${supervisor.origin}/api/v1/health`,{signal:AbortSignal.timeout(3000)}).then(response=>{if(!response.ok)throw new Error('Not ready');broadcast();}).catch(()=>{supervisor.announce('failed','休眠恢复后服务不可用，请保存草稿后点击重启服务。');});});
    } catch(error) {
      if(supervisor)supervisor.announce('failed',error.message);
      else await dialog.showMessageBox(main,{type:'error',message:'WebOBS 原生运行环境无法启动',detail:error.message});
      await main.loadFile(path.join(source,'diagnostics.html'));broadcast();
    }
  }
}
