import { EventEmitter } from 'node:events';
import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile, rm, stat } from 'node:fs/promises';
import path from 'node:path';
import { randomBytes } from 'node:crypto';
import { allocatePorts, bindPort } from './ports.mjs';
import { atomicJson } from './settings.mjs';
import { caddyConfiguration, lanAddresses, firewallInstructions } from './lan.mjs';

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
export function cleanEnvironment(environment) {
  return Object.fromEntries(Object.entries(environment).filter(([key]) => !/^(WEBOBS_|MTX_|GO2RTC_|PYTHON|PATH$|NODE_OPTIONS$|ELECTRON_RUN_AS_NODE$)/i.test(key)));
}
export class Supervisor extends EventEmitter {
  constructor({ runtime, root, videos, settings, version, safeStorage }) {
    super(); Object.assign(this, { runtime, root, videos, settings, version, safeStorage });
    this.children = []; this.state = { phase: 'stopped', services: [] }; this.stopping = false;
    this.data = path.join(root, 'config'); this.recordings = settings.recordingDirectory || path.join(videos, 'WebOBS');
  }
  status() { return { ...this.state, origin: this.origin, recordings: this.recordings,
    lan: this.lanInfo || { enabled: false } }; }
  announce(phase, detail = '') { this.state = { phase, detail, services: this.children.map(child => ({ name: child.name, running: child.process.exitCode === null && !child.exited })) }; this.emit('status', this.status()); }
  executable(name) { return path.join(this.runtime, 'bin', name + '.exe'); }
  python(script, ...args) { return [path.join(this.runtime, 'python', 'python.exe'), path.join(this.runtime, 'services', script), ...args]; }
  async tool(script, args = [], timeout = 120000) {
    const command = this.python(script, ...args);
    return new Promise((resolve,reject) => {
      const child = spawn(this.executable('webobs-job'), ['--stdio', ...command], { env: { ...(this.env || cleanEnvironment(process.env)), WEBOBS_OWNER_STDIN: 'false' }, windowsHide: true, stdio: ['pipe','pipe','pipe'] });
      let output = ''; const timer = setTimeout(() => { child.kill(); reject(new Error('Native tool timed out')); }, timeout);
      child.stdout.on('data', chunk => { if (output.length < 1024*1024) output += chunk.toString('utf8'); });
      child.stderr.resume();
      child.on('error', error => { clearTimeout(timer); reject(error); });
      child.on('exit', code => { clearTimeout(timer); if (code === 0) resolve(output); else reject(new Error(`Native tool failed (${code}): ${script}`)); });
    });
  }
  async prepare() {
    await mkdir(this.root, { recursive: true });
    await this.tool('desktop-tools/private_directory.py', [this.root]);
    for (const directory of [this.data, this.recordings, path.join(this.root,'logs'), path.join(this.root,'run'), path.join(this.root,'snapshots')]) await mkdir(directory, { recursive: true });
    await this.tool('desktop-tools/private_directory.py', [this.recordings]);
    this.ports = await allocatePorts(this.root, this.settings.lanEnabled);
    this.origin = `http://127.0.0.1:${this.ports.control}`;
    const config = (...names) => path.join(this.data, ...names);
    const run = (...names) => path.join(this.root, 'run', ...names);
    this.lanIPs = this.settings.lanEnabled ? lanAddresses() : [];
    if (this.settings.lanEnabled && !this.lanIPs.length) throw new Error('局域网共享已开启，但没有私有 IPv4 地址。连接局域网后重试，或关闭共享。');
    if (!this.safeStorage.isEncryptionAvailable()) throw new Error('Windows DPAPI 不可用，无法保护本机备份密钥。');
    const protectedKey = path.join(this.root,'backup-key.dpapi');
    let key;
    try { key = this.safeStorage.decryptString(await readFile(protectedKey)); }
    catch (error) {
      if (error.code !== 'ENOENT') throw new Error('本机 DPAPI 密钥无法解密。请使用原 Windows 账号或备份恢复。');
      key = randomBytes(32).toString('hex'); await writeFile(protectedKey, this.safeStorage.encryptString(key), { mode: 0o600 });
    }
    if (!/^[a-f0-9]{64}$/.test(key)) throw new Error('Invalid protected backup key');
    await writeFile(run('backup.key'), Buffer.from(key,'hex'), { mode: 0o600 });
    const localOrigins = [this.origin, ...this.lanIPs.map(ip => `https://${ip}:${this.settings.lanPort}`)];
    this.env = { ...cleanEnvironment(process.env),
      PATH: [path.join(this.runtime,'bin'),path.join(this.runtime,'obs','bin','64bit'),path.join(this.runtime,'python'),path.join(process.env.SystemRoot || 'C:\\Windows','System32')].join(path.delimiter),
      PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', WEBOBS_OWNER_STDIN: 'true',
      WEBOBS_HTTP_PORT: String(this.ports.control), WEBOBS_LISTEN_ADDRESS: '127.0.0.1', WEBOBS_ALLOW_INSECURE_REMOTE: 'false',
      WEBOBS_CONTROL_ALLOWED_ORIGINS: localOrigins.join(','), WEBOBS_PWA_MEDIA_ALLOWED_ORIGINS: localOrigins.filter(origin=>origin.startsWith('https://')).join(','),
      WEBOBS_WEB_ROOT: path.join(this.runtime,'web'), WEBOBS_OBS_PREFIX: path.join(this.runtime,'obs'),
      WEBOBS_SCENE_FILE: config('scene.json'), WEBOBS_STUDIO_FILE: config('studio.json'), WEBOBS_OBS_CONFIG_DIR: config('obs'),
      WEBOBS_SESSION_DATABASE: config('auth-sessions.db'), WEBOBS_CAMERA_DATABASE: config('cameras.db'), WEBOBS_EVENT_DATABASE: config('events.db'),
      WEBOBS_V2_DATABASE: config('v2-clients.db'), WEBOBS_CLUSTER_DATABASE: config('cluster.sqlite3'), WEBOBS_V2_SHARED_SCENES: config('shared-scenes-v2.json'),
      WEBOBS_V2_SIGNING_KEY: config('keys','client-grant-signing.key'), WEBOBS_CAMERA_SECRET_ROOT: config('camera-secrets'),
      WEBOBS_CAMERA_SECRET_WRITE_ROOT: config('camera-secrets'), WEBOBS_NOTIFICATION_SECRET_ROOT: config('notification-secrets'), WEBOBS_SECRETS_ROOT: config('secrets'),
      WEBOBS_NVR_CONFIG: config('nvr.json'), WEBOBS_NVR_STORAGE: this.recordings, WEBOBS_NVR_DATABASE: path.join(this.recordings,'catalog.sqlite3'),
      WEBOBS_NVR_CATALOG: path.join(this.recordings,'catalog.sqlite3'), WEBOBS_NVR_VOLUMES_ROOT: path.join(this.recordings,'volumes'),
      WEBOBS_NODE_STATE_DIR: config('node'), WEBOBS_NODE_ASSIGNMENTS_FILE: config('node','assignments.json'), WEBOBS_NODE_ROLE: 'standalone',
      WEBOBS_REGISTRATION_ENABLED: 'true', WEBOBS_COMPAT_BASIC_AUTH: 'false', WEBOBS_SESSION_COOKIE_SECURE: 'false',
      WEBOBS_CLUSTER_INTERNAL_TOKEN: randomBytes(32).toString('hex'), WEBOBS_V2_INTERNAL_TOKEN: randomBytes(32).toString('hex'),
      WEBOBS_NVR_ENABLED: 'true', WEBOBS_CAMERA_REGISTRY_ENABLED: 'true', WEBOBS_WEBRTC_ENABLED: 'true', WEBOBS_COMPOSITE_ENABLED: 'true',
      WEBOBS_WHIP_URL: `http://127.0.0.1:${this.ports.whep}/program/whip`, WEBOBS_RENDERER_SELECTED: 'd3d11',
      WEBOBS_FFMPEG_PATH: this.executable('ffmpeg'), WEBOBS_TRANSCODER_PATH: this.executable('webobs-transcoder'),
      WEBOBS_DETECTOR_WORKER: this.executable('webobs-detector-worker'), WEBOBS_DETECTOR_MODEL: path.join(this.runtime,'web','models','ssd_mobilenet_v1_12.onnx'),
      WEBOBS_ARCHIVE_COMMAND: this.executable('webobs-s3-archive'), WEBOBS_ARCHIVE_CONFIG: config('archive.json'),
      WEBOBS_ARCHIVE_QUEUE: config('archive-queue.sqlite3'), WEBOBS_NVR_STORAGE_ROOT: this.recordings,
      WEBOBS_RESTORE_CONFIRM: 'replace-config',
      WEBOBS_LIBSODIUM_LIBRARY: this.executable('libsodium').replace(/\.exe$/,'.dll'),
      WEBOBS_BACKUP_CONFIG_ROOT: this.data, WEBOBS_BACKUP_ROOT: path.join(this.root,'backups'), WEBOBS_BACKUP_KEY_FILE: run('backup.key'),
      WEBOBS_BACKUP_S3_CONFIG: config('archive.json'), WEBOBS_GO2RTC_ENABLED: 'true', WEBOBS_GO2RTC_BINARY: this.executable('go2rtc'),
      WEBOBS_GO2RTC_CONFIG: config('go2rtc','go2rtc.yaml'), WEBOBS_GO2RTC_TEMPLATE: path.join(this.runtime,'etc','go2rtc.yaml'),
      WEBOBS_GO2RTC_WEB_ROOT: path.join(this.runtime,'go2rtc-www'), WEBOBS_GO2RTC_WEBRTC_BIND: '127.0.0.1',
    };
    const names = { nvr:'NVR_INTERNAL',camera:'CAMERA_INTERNAL',events:'EVENTS_INTERNAL',clients:'V2_INTERNAL',cluster:'CLUSTER_INTERNAL',
      rtsp:'MEDIAMTX_RTSP',gatewayApi:'MEDIAMTX_API',whep:'MEDIAMTX_WEBRTC',go2rtcApi:'GO2RTC_API',go2rtcRtsp:'GO2RTC_RTSP',go2rtcWebrtc:'GO2RTC_WEBRTC' };
    for (const [key,name] of Object.entries(names)) this.env[`WEBOBS_${name}_PORT`] = String(this.ports[key]);
    const mtx = await readFile(path.join(this.runtime,'etc','mediamtx.yml'),'utf8');
    let mediaConfig = mtx.replace('127.0.0.1:9997',`127.0.0.1:${this.ports.gatewayApi}`).replace('127.0.0.1:8554',`127.0.0.1:${this.ports.rtsp}`)
      .replace('127.0.0.1:8889',`127.0.0.1:${this.ports.whep}`).replace('webrtcLocalUDPAddress: :8189',`webrtcLocalUDPAddress: ${this.settings.lanEnabled ? '0.0.0.0':'127.0.0.1'}:${this.ports.iceUdp}`)
      .replace("webrtcLocalTCPAddress: ''",`webrtcLocalTCPAddress: '${this.settings.lanEnabled ? '0.0.0.0':'127.0.0.1'}:${this.ports.iceTcp}'`)
      .replace('webrtcAdditionalHosts: [127.0.0.1]',`webrtcAdditionalHosts: [127.0.0.1${this.lanIPs.map(ip=>`, ${ip}`).join('')}]`);
    if (this.settings.lanEnabled) mediaConfig = mediaConfig.replace('ips: [127.0.0.1, ::1]', 'ips: [127.0.0.1, ::1, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16]');
    await writeFile(run('mediamtx.yml'),mediaConfig,{mode:0o600});
    if (this.settings.lanEnabled) {
      const lease = await bindPort(this.settings.lanPort, false, this.lanIPs[0]); await lease.release();
      await atomicJson(run('caddy.json'), caddyConfiguration(this.lanIPs,this.settings.lanPort,this.ports.control,path.join(this.root,'caddy')));
      this.lanInfo = { enabled:true, addresses:this.lanIPs.map(ip=>`https://${ip}:${this.settings.lanPort}`),
        certificate:path.join(this.root,'caddy','pki','authorities','local','root.crt'),
        trustSteps:'在本机和每个访问设备的当前用户“受信任的根证书颁发机构”中导入此 root.crt。确认来源为本机 WebOBS 后再信任。',
        firewallCommands:firewallInstructions(this.settings.lanPort,this.ports.iceTcp,this.ports.iceUdp,this.lanIPs) };
    }
    try {
      const probe = await this.tool('scripts/hardware-probe.py',['--env','--cache',run('hardware.json')],180000);
      for (const line of probe.split(/\r?\n/)) { const match = /^(WEBOBS_(?:NVIDIA|QSV)_[A-Z_]+)=(true|false|software|cuda|full|partial|none)$/.exec(line); if(match) this.env[match[1]]=match[2]; }
    } catch { this.env.WEBOBS_NVIDIA_SAMPLE_PASSED='false'; this.env.WEBOBS_NVIDIA_ENCODE_SUPPORTED='false'; }
  }
  async startService(name, command, health, mode = '--stdio', timeout = 30000) {
    this.announce('starting', name);
    const child = spawn(this.executable('webobs-job'), [mode,...command], { cwd:this.data, env:this.env, windowsHide:true, stdio:['pipe','pipe','pipe'] });
    let failure, exited = false;
    const entry = { name, process:child, exited:false, code:null }; this.children.push(entry);
    let logBytes = 0;
    const append = async chunk => {
      if (logBytes >= 4*1024*1024) return;
      logBytes += chunk.length;
      await writeFile(path.join(this.root,'logs',`${name}.log`),chunk,{ flag:'a',mode:0o600 }).catch(()=>{});
    };
    await writeFile(path.join(this.root,'logs',`${name}.log`),'',{mode:0o600});
    child.stdout.on('data',chunk=>void append(chunk)); child.stderr.on('data',chunk=>void append(chunk));
    child.stdin.on('error',error=>{ failure=error; });
    child.on('error',error=>{ failure=error; entry.exited=true; entry.code=-1; });
    child.on('exit', code => { exited = true; entry.exited = true; entry.code=code;
      if (!this.stopping && this.state.phase === 'ready') this.announce('failed',`${name} 已退出 (${code})。查看本机日志后重试启动。`); });
    const deadline = Date.now()+timeout;
    while(Date.now()<deadline) {
      if (failure || exited) throw new Error(`${name} 启动失败。检查 ${path.join(this.root,'logs',name+'.log')}。`);
      if (!health) { await delay(400); if (!exited && !failure) return; }
      else try { const response=await fetch(health,{signal:AbortSignal.timeout(1000)}); if(response.ok) { await response.arrayBuffer(); return; } } catch {}
      await delay(200);
    }
    throw new Error(`${name} 未通过健康检查。检查 ${path.join(this.root,'logs',name+'.log')}。`);
  }
  async start() {
    if(this.children.length) throw new Error('Services are already running');
    this.stopping=false; this.announce('starting','准备本机运行环境');
    try {
      await this.prepare();
      await this.startService('mediamtx',[this.executable('mediamtx'),path.join(this.root,'run','mediamtx.yml')],`http://127.0.0.1:${this.ports.gatewayApi}/v3/config/global/get`,'--console');
      await this.startService('go2rtc',this.python('go2rtc/runtime.py'),`http://127.0.0.1:${this.ports.go2rtcApi}/api/v1/go2rtc/api`);
      for(const [name,script,key] of [['camera','camera/camera_registry.py','camera'],['cluster','cluster/cluster_service.py','cluster'],['clients','v2/client_control_service.py','clients'],['events','events/event_service.py','events'],['nvr','nvr/nvr_service.py','nvr']])
        await this.startService(name,this.python(script),`http://127.0.0.1:${this.ports[key]}/health`);
      try { await stat(path.join(this.data,'archive.json')); await this.startService('archive',this.python('archive/s3_archive.py'),null); }
      catch(error) { if(error.code!=='ENOENT')throw error; }
      await this.startService('backup',this.python('backup/encrypted_backup.py','schedule'),null);
      // Core health is the control/engine boot check; /ready also includes camera health and Program publication.
      await this.startService('core',[this.executable('webobsd')],`${this.origin}/api/v1/health`,'--stdio',90000);
      if(this.settings.lanEnabled) await this.startService('caddy',[this.executable('caddy'),'run','--config',path.join(this.root,'run','caddy.json')],null,'--console');
      this.announce('ready');
    } catch(error) { await this.stop().catch(()=>{}); this.announce('failed',error.message); throw error; }
  }
  async stop() {
    this.stopping=true; this.announce('stopping');
    let failed=false;
    for(const entry of [...this.children].reverse()) {
      const child=entry.process;
      if(entry.exited || child.exitCode !== null) { if(entry.code !== 0) failed=true; continue; }
      const exit=new Promise(resolve=>child.once('exit',code=>resolve(code)));
      if(!child.stdin.destroyed)child.stdin.write('shutdown\n');
      else {failed=true;child.kill();}
      const code=await Promise.race([exit,delay(35000).then(()=>Symbol.for('timeout'))]);
      if(typeof code !== 'number' || code !== 0) { failed=true; if(!entry.exited) { child.kill(); await Promise.race([exit,delay(5000)]); } }
    }
    this.children=[];
    await rm(path.join(this.root,'run','backup.key'),{force:true});
    this.announce('stopped');
    if(failed) throw new Error('部分服务未正常关闭；更新安装已暂停。请检查日志并恢复当前版本。');
  }
  async snapshot(version = this.version) {
    if(this.children.length) throw new Error('Snapshot requires all writers to stop');
    const target=path.join(this.root,'snapshots',`${version}-${Date.now()}`);
    await this.tool('desktop-tools/snapshot.py',['create','--data',this.data,'--recordings',this.recordings,'--snapshot',target,'--version',version],300000);
    return target;
  }
  async workload() {
    const [nvr,paths] = await Promise.all([
      fetch(`http://127.0.0.1:${this.ports.nvr}/status`,{signal:AbortSignal.timeout(3000)}).then(r=>{if(!r.ok)throw new Error('NVR status unavailable');return r.json();}),
      fetch(`http://127.0.0.1:${this.ports.gatewayApi}/v3/paths/list`,{signal:AbortSignal.timeout(3000)}).then(r=>{if(!r.ok)throw new Error('Media status unavailable');return r.json();}),
    ]);
    return { exporting:nvr.activeExports > 0, recording:nvr.cameras.some(camera=>!['idle','off','stopped'].includes(camera.state)), streaming:paths.items.some(item=>item.ready),
      details:'当前录像或媒体发布仍在运行。继续将正常停止这些任务，创建数据快照后安装更新。' };
  }
}
