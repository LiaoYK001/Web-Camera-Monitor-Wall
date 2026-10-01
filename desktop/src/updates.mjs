import { EventEmitter } from 'node:events';
import { cp, mkdir, readFile, statfs, stat, rm } from 'node:fs/promises';
import path from 'node:path';
import { digestFile } from './runtime-integrity.mjs';
import { atomicJson } from './settings.mjs';

export function updateBlockers(windowWork, workload) {
  const reasons = [];
  if (windowWork.some(item => item.dirty)) reasons.push('有尚未保存的草稿');
  if (windowWork.some(item => item.exporting)) reasons.push('有正在进行的导出任务');
  if (workload?.exporting) reasons.push('后端仍有正在进行的证据导出或截图');
  if (!workload || typeof workload.recording !== 'boolean' || typeof workload.streaming !== 'boolean') reasons.push('无法确认录像和推流状态');
  return reasons;
}
export class UpdateController extends EventEmitter {
  constructor({ updater, official, publisher, packaged, settings, root, supervisor, windowWork, confirmStop, beforeInstall, verifySignature, version }) {
    super(); Object.assign(this,{ updater,official,publisher,packaged,settings,root,supervisor,windowWork,confirmStop,beforeInstall,verifySignature,version });
    this.enabled = official && packaged && typeof publisher === 'string' && publisher.length > 0;
    this.state = { phase: this.enabled ? 'idle':'disabled', message:this.enabled ? '' : '开发测试包不连接正式更新源。' };
    this.installing=false; this.checking=false;
    updater.autoInstallOnAppQuit=false; updater.autoDownload=false; updater.allowPrerelease=false; updater.allowDowngrade=false; updater.disableWebInstaller=true;
    updater.on('checking-for-update',()=>this.announce('checking'));
    updater.on('update-not-available',()=>this.announce('current'));
    updater.on('update-available',info=>{
      if (!/^\d+\.\d+\.\d+$/.test(info.version)) { this.announce('error','仅接受正式版本'); return; }
      this.info=info; this.announce('available','有新版本');
      if(this.settings.autoDownload) void this.download();
    });
    updater.on('download-progress',progress=>this.announce('downloading','正在下载',Math.round(progress.percent)));
    updater.on('update-downloaded',info=>{this.downloaded=info; this.announce('downloaded','下载完成，点击“重启更新”后才安装。');});
    updater.on('error',()=>this.announce('error','更新检测、下载、摘要或签名验证失败。当前版本继续运行，可稍后重试。'));
  }
  status() {
    const notes = this.info?.releaseNotes;
    return {...this.state,version:this.info?.version,releaseNotes:typeof notes==='string'?notes.slice(0,16000):Array.isArray(notes)?notes.map(item=>String(item.note||'')).join('\n').slice(0,16000):''};
  }
  announce(phase,message='',percent) { this.state={phase,message,percent}; this.emit('status',this.status()); }
  start() { this.timer=setInterval(()=>{if(this.settings.autoCheck)void this.check();},6*60*60*1000);this.timer.unref?.();if(this.settings.autoCheck)void this.check(); }
  dispose() { clearInterval(this.timer); }
  async check() {
    if(!this.enabled || this.checking || this.installing) return this.status();
    this.checking=true;
    try { await this.updater.checkForUpdates(); } catch { this.announce('error','检查更新失败，请确认网络后重试。'); }
    finally { this.checking=false; }
    return this.status();
  }
  async download() {
    if(!this.enabled || !this.info || this.installing || this.downloading) return;
    this.downloading=true;
    try {
      const files=this.info.files;
      if(!Array.isArray(files) || !files.length || files.some(item=>!item.sha512 || !Number.isSafeInteger(item.size) || item.size<=0)) throw new Error('Missing update digest or size');
      const total=files.reduce((sum,item)=>sum+item.size,0);
      const disk=await statfs(this.root);if(Number(disk.bavail)*Number(disk.bsize)<total*3+512*1024*1024)throw new Error('Insufficient disk space');
      this.announce('downloading'); await this.updater.downloadUpdate();
    } catch { this.announce('error','下载失败，附件不完整或磁盘空间不足。当前版本继续运行。'); }
    finally { this.downloading=false; }
  }
  async verifyDownloaded(file=this.downloaded?.downloadedFile) {
    if(!file || !(await stat(file)).isFile()) throw new Error('Downloaded installer missing');
    const item=this.info?.files?.find(item=>String(item.url).endsWith('.exe'));
    if(!item?.sha512 || await digestFile(file,'sha512','base64')!==item.sha512)throw new Error('Installer SHA-512 mismatch');
    if(await this.verifySignature([this.publisher],file)!==null)throw new Error('Installer publisher or Authenticode signature mismatch');
    return file;
  }
  async install() {
    if(!this.enabled || this.installing || this.state.phase!=='downloaded')return this.status();
    this.installing=true;
    let stopped=false, pending=false;
    try {
      await this.verifyDownloaded();
      const workload=await this.supervisor.workload();
      const blockers=updateBlockers(this.windowWork(),workload);
      if(blockers.length) {this.announce('downloaded',`${blockers.join('；')}。处理后再点击重启更新。`);return this.status();}
      if((workload.recording || workload.streaming) && !await this.confirmStop(workload))return this.status();
      // Close the race with a just-started export or edited draft while the dialog was open.
      if(updateBlockers(this.windowWork(),await this.supervisor.workload()).length)throw new Error('Workspace became busy');
      this.announce('preparing','正在正常停服和创建一致性快照');
      stopped=true; await this.supervisor.stop();
      const snapshot=await this.supervisor.snapshot(this.version);
      const installers=path.join(this.root,'installers');await mkdir(installers,{recursive:true});
      const nextInstaller=path.join(installers,`WebOBS-${this.info.version}-windows-x64.exe`);
      await cp(this.downloaded.downloadedFile,nextInstaller,{force:true});
      await this.verifyDownloaded(nextInstaller);
      let previous;
      try {previous=JSON.parse(await readFile(path.join(this.root,'installed-version.json'),'utf8'));}catch{}
      await atomicJson(path.join(this.root,'pending-update.json'),{schema:1,from:this.version,to:this.info.version,snapshot,previousInstaller:previous?.installer || null,installer:nextInstaller,installerSha256:await digestFile(nextInstaller),previousInstallerSha256:previous?.installerSha256 || null});
      pending=true;
      // Revalidate after the snapshot, including a package changed on disk during preparation.
      await this.verifyDownloaded();
      this.beforeInstall(); this.updater.quitAndInstall(false,true);
      return this.status();
    } catch {
      if(pending)await rm(path.join(this.root,'pending-update.json'),{force:true}).catch(()=>{});
      this.announce('error','更新准备或正常停服失败，未安装。正在恢复当前版本；请检查本机日志与磁盘空间。');
      if(stopped) {try {await this.supervisor.start();}catch{this.announce('error','当前服务恢复失败。请进入恢复界面查看诊断与数据快照。');}}
    } finally {this.installing=false;}
    return this.status();
  }
}
