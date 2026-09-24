import { spawn, spawnSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync, mkdirSync, unlinkSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import net from 'node:net';
import http from 'node:http';
import os from 'node:os';
import { createHash, randomBytes } from 'node:crypto';
const root = fileURLToPath(new URL('../', import.meta.url));
const web = path.join(root, 'web');
const win = process.platform === 'win32';
const options = { mode: 'native', api: 'http://127.0.0.1:8080', port: '5173', distro: 'Ubuntu-24.04', engine: 'docker', lanHost: '' };
const flags = new Set(['setup', 'check', 'build', 'help', 'stop', 'composite', 'soak', 'lan']);
const children = new Set();
let stopping = false;
let controlServer; let stateFile;
const log = (message) => console.log(`\n[WebOBS] ${message}`);
function detectLanIPv4() {
  // Prefer a non-internal IPv4 that is not link-local (169.254/16).
  for (const entries of Object.values(os.networkInterfaces())) {
    for (const entry of entries ?? []) {
      if (entry.family === 'IPv4' && !entry.internal && !entry.address.startsWith('169.254.')) return entry.address;
    }
  }
  return '';
}
function run(command, args, capture = false, cwd = root) {
  const result = spawnSync(command, args, { cwd, encoding: 'utf8', stdio: capture ? 'pipe' : 'inherit', windowsHide: true, ...(capture ? { timeout: 30000 } : {}) });
  if (result.error || result.status !== 0) throw new Error(`${command} 执行失败。${result.error?.message ?? (result.stderr ?? '').trim()}`);
  return (result.stdout ?? '').trim();
}
function launch(command, args, cwd = root, piped = false) {
  const child = spawn(command, args, { cwd, stdio: ['pipe', piped ? 'pipe' : 'inherit', 'inherit'], windowsHide: true });
  children.add(child);
  child.once('error', (error) => stop(1, error.message));
  child.once('exit', (code) => { children.delete(child); if (!stopping) stop(code ?? 1, '开发进程已退出'); });
  return child;
}
function stop(code = 0, message = '') {
  if (stopping) return;
  stopping = true;
  if (message) log(message);
  controlServer?.close();
  if (stateFile && existsSync(stateFile)) unlinkSync(stateFile);
  for (const child of children) {
    child.stdin?.end();
    // Closing stdin asks the Linux supervisor to stop only its own services.
    if (win && child.spawnfile !== 'wsl.exe') spawnSync('taskkill.exe', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true });
    else if (!win) child.kill('SIGTERM');
  }
  setTimeout(() => process.exit(code), 1500);
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
async function freePort(port) {
  await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', () => reject(new Error(`端口 ${port} 已被占用。请停止旧开发终端，或用 --port / -Port 指定其他前端端口；不会自动结束其他进程。`)));
    // LAN mode binds 0.0.0.0; probe that address so a conflicting listener is caught.
    const host = options.lan ? '0.0.0.0' : '127.0.0.1';
    server.listen(port, host, () => server.close(resolve));
  });
}
function pnpmArgs(args) {
  // Call the JS entry directly: avoid Windows .cmd quoting and shell injection.
  const location = run(win ? 'where.exe' : 'which', ['corepack'], true).split(/\r?\n/)[0];
  const directory = path.dirname(location);
  const candidates = [path.join(directory, 'node_modules/corepack/dist/corepack.js'), path.resolve(directory, '../lib/node_modules/corepack/dist/corepack.js')];
  if (!win) candidates.unshift(fileURLToPath(new URL('file://' + location)));
  const entry = candidates.find(existsSync);
  if (!entry) throw new Error('未找到 Corepack。请运行 npm install -g corepack 后重试。');
  return [entry, 'pnpm', ...args];
}
function credentials() {
  mkdirSync(path.join(root, 'secrets'), { recursive: true });
  for (const [name, value] of [['username', 'admin'], ['password', randomBytes(24).toString('base64')]]) {
    const file = path.join(root, `secrets/webobs-dev-${name}.txt`);
    if (!existsSync(file)) writeFileSync(file, value, { mode: 0o600 });
  }
}
try {
  const args = process.argv.slice(2);
  for (let i = 0; i < args.length; i++) {
    // Accept both --lan-host and --lanHost (dev.mjs options use camelCase).
    const key = args[i].replace(/^--/, '').replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    if (!args[i].startsWith('--') || (!flags.has(key) && !Object.hasOwn(options, key) && key !== 'builder')) throw new Error(`未知参数：${args[i]}`);
    if (flags.has(key)) options[key] = true;
    else { if (!args[i + 1] || args[i + 1].startsWith('--')) throw new Error(`参数 ${args[i]} 缺少值`); options[key] = args[++i]; }
  }
  if (options.help) {
    console.log(`WebOBS 本地开发\n\nWindows: .\\scripts\\dev.ps1 [-Setup] [-Check] [-Composite] [-Soak] [-Mode native|frontend|container] [-Api URL] [-Port 5173]\nLinux:   bash scripts/dev.sh [--setup] [--check] [--composite] [--soak] [--mode native|frontend|container] [--api URL] [--port 5173]\n\nLAN:     .\\scripts\\dev-lan-environment.ps1 [-LanHost IP] [-Port 5173] ...\n         bash scripts/dev-lan-environment.sh [--lan-host IP] [--port 5173] ...\n\nnative    默认：原生 C++/Python 后端 + Vite；Windows 后端运行在 WSL2。首次加 --setup / -Setup 安装 Ubuntu 24.04 依赖。\n--composite / -Composite\n          显式启用本地服务端合成（OBS 图形/媒体输入/编码与 WHIP 输出模块）。\n          首次使用：.\\scripts\\dev.ps1 -Setup -Composite；日常：.\\scripts\\dev.ps1 -Composite。\n          不带参数时保持轻量 native 默认行为（不构建合成模块）。\nfrontend  仅启动 Vite，连接 --api / -Api 指定的已有后端。\ncontainer 可选兼容模式；需要已启动 Docker/Podman，仅显式 --build / -Build 时构建镜像。\n--soak / -Soak\n          耐久/长稳模式：后端不监听父进程 stdin，父终端关闭也不会停止本次会话；\n          供 30 分钟验收与持续采样使用。退出用 Ctrl+C 或 SIGTERM。仅 native 模式生效。\n--lan     局域网开发模式（dev-lan-environment）：Vite 监听 0.0.0.0，/api 代理把\n          Host/Origin 改写回 127.0.0.1，后端仍只绑定本机回环（端口转发语义）。\n          局域网成员用 http://<本机IPv4>:<端口>/ 访问。仅限受信任局域网，不是公网部署。\n--lan-host 指定对外 IPv4（默认自动探测第一个非链路本地 IPv4）。\n--check   只检查环境，不安装、不构建、不启动。\n--distro  Windows WSL 发行版，默认 Ubuntu-24.04。\n--engine  docker 或 podman（仅 container）。--builder 为 Docker 构建器。\n\nCtrl+C 结束本次原生服务和前端；容器模式保留后端。详见 docs/development.md。`);
    process.exit(0);
  }
  if (!/^\d+$/.test(options.port) || Number(options.port) < 1024 || Number(options.port) > 65535) throw new Error('前端端口须为 1024–65535');
  if (options.stop) {
    const saved = path.join(root, 'build', `dev-session-${options.port}.json`);
    if (!existsSync(saved)) throw new Error('没有找到这个端口的开发会话。请在原启动终端 Ctrl+C；旧版脚本启动的服务需手动停止。');
    const state = JSON.parse(readFileSync(saved, 'utf8'));
    const response = await fetch(`http://127.0.0.1:${state.controlPort}/stop`, { method: 'POST', headers: { Authorization: state.token }, signal: AbortSignal.timeout(3000) });
    if (!response.ok) throw new Error('停止请求被拒绝；不会结束其他进程。');
    log('已请求停止本次开发会话（容器模式的后端保留运行）。'); process.exit(0);
  }
  if (Number(process.versions.node.split('.')[0]) < 24) throw new Error('需要 Node.js 24 或更新版本。');
  if (!['native', 'frontend', 'container'].includes(options.mode)) throw new Error('mode 必须是 native、frontend 或 container');
  if (!['docker', 'podman'].includes(options.engine)) throw new Error('engine 必须是 docker 或 podman');
  const api = new URL(options.api);
  if (!['http:', 'https:'].includes(api.protocol) || api.username || api.password) throw new Error('API 地址必须是无内嵌凭据的 HTTP(S) 地址');
  if (options.build && options.mode !== 'container') throw new Error('-Build / --build 仅用于 --mode container；原生模式启动时自动增量编译。');
  log(`模式：${options.mode}${options.lan ? ' | LAN 局域网共享' : ''} | Node ${process.versions.node} | 前端端口 ${options.port}`);
  if (options.lan) {
    const lanHost = options.lanHost || detectLanIPv4();
    if (!lanHost || !/^\d{1,3}(\.\d{1,3}){3}$/.test(lanHost)) {
      throw new Error('未能确定局域网 IPv4。请用 --lan-host / -LanHost 指定本机局域网地址。');
    }
    options.lanHost = lanHost;
    log(`LAN 端口转发：http://${lanHost}:${options.port}/  →  127.0.0.1:${options.port}\n  后端仍只监听 127.0.0.1:8080；/api 代理改写 Host/Origin 为回环。\n  [安全] 仅限受信任局域网联调，不要对公网暴露；防火墙请只放行 ${options.port}/tcp${options.mode === 'native' ? ' 与 8189/udp、8190/tcp（WebRTC）' : ''}。`);
    process.env.WEBOBS_LAN = '1';
    process.env.WEBOBS_LAN_HOST = lanHost;
  }
  const pnpm = pnpmArgs(['--version']);
  let pnpmVersion;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try { pnpmVersion = run(process.execPath, pnpm, true, web); break; }
    catch (error) {
      if (attempt === 3) throw new Error(`pnpm 准备失败。请检查网络/代理，在 web 目录运行 corepack pnpm --version 查看详情。${error.message.slice(0, 300)}`);
      log(`包管理器暂不可用，正在重试 ${attempt}/2（首次可能需要下载固定版本）`);
      await new Promise(resolve => setTimeout(resolve, attempt * 1000));
    }
  }
  log(`包管理器：pnpm ${pnpmVersion}`);
  let nativeCommand;
  if (options.mode === 'native') {
    if (options.api !== 'http://127.0.0.1:8080') throw new Error('原生后端固定监听 8080；自定义已有后端请使用 frontend 模式。');
    if (win) {
      let linuxRoot;
      try { linuxRoot = run('wsl.exe', ['-d', options.distro, '--exec', 'wslpath', '-a', root.replace(/\\/g, '/').replace(/\/$/, '')], true); }
      catch { throw new Error(`无法启动 WSL 发行版 ${options.distro}。请运行 wsl -l -v 检查名称；首次安装用 wsl --install -d Ubuntu-24.04，其他名称通过 -Distro 指定。`); }
      nativeCommand = ['wsl.exe', ['-d', options.distro, '--exec', 'bash', `${linuxRoot}/scripts/dev-native.sh`]];
    } else nativeCommand = ['bash', [path.join(root, 'scripts/dev-native.sh')]];
    if (options.setup && !options.check) {
      log('安装 Ubuntu 系统依赖（仅首次；Linux sudo 可能要求本机密码）');
      const setupArgs = ['--install-deps', ...(options.composite ? ['--composite'] : [])];
      if (win) run('wsl.exe', ['-d', options.distro, '-u', 'root', '--exec', 'bash', nativeCommand[1].at(-1), ...setupArgs]);
      else run(nativeCommand[0], [...nativeCommand[1], ...setupArgs]);
    }
    if (options.check) { run(nativeCommand[0], [...nativeCommand[1], '--check', ...(options.composite ? ['--composite'] : [])]); log('检查通过；未启动服务。'); process.exit(0); }
  } else if (options.mode === 'container') {
    try { run(options.engine, ['info'], true); }
    catch { throw new Error(`${options.engine} 引擎未启动或不可连接。Docker：启动 Docker Desktop 并等待引擎就绪；Podman：检查 podman machine start。日常无需容器时直接运行默认 native 模式。`); }
    run(options.engine, ['compose', 'version'], true);
  } else {
    try { const response = await fetch(new URL('/api/v1/health', api), { signal: AbortSignal.timeout(5000) }); if (!response.ok) throw new Error(); }
    catch { throw new Error(`后端 ${options.api} 不可达。启动已有后端，或改用默认 native 模式。`); }
  }
  if (options.check) { log('检查通过；未启动服务。'); process.exit(0); }
  await freePort(Number(options.port));
  const lock = createHash('sha256').update(readFileSync(path.join(web, 'pnpm-lock.yaml'))).update(readFileSync(path.join(web, 'package.json'))).update(process.platform).update(process.arch).digest('hex');
  const stamp = path.join(web, 'node_modules/.webobs-dev-dependencies');
  if (!existsSync(stamp) || readFileSync(stamp, 'utf8') !== lock) {
    log('安装/同步前端依赖（后续锁文件不变时跳过）');
    run(process.execPath, pnpmArgs(['install', '--frozen-lockfile']), false, web);
    writeFileSync(stamp, lock);
  }
  const token = randomBytes(32).toString('hex');
  controlServer = http.createServer((request, response) => {
    if (request.method !== 'POST' || request.url !== '/stop' || request.headers.authorization !== token) { response.writeHead(403).end(); return; }
    response.writeHead(200).end('stopping'); setTimeout(() => stop(), 50);
  });
  await new Promise((resolve, reject) => { controlServer.once('error', reject); controlServer.listen(0, '127.0.0.1', resolve); });
  mkdirSync(path.join(root, 'build'), { recursive: true });
  stateFile = path.join(root, 'build', `dev-session-${options.port}.json`);
  writeFileSync(stateFile, JSON.stringify({ controlPort: controlServer.address().port, token }), { mode: 0o600 });
  process.env.WEBOBS_API_PROXY_TARGET = options.api;
  const originHosts = options.lan
    ? ['127.0.0.1', 'localhost', options.lanHost]
    : ['127.0.0.1', 'localhost'];
  process.env.WEBOBS_DEV_ALLOWED_ORIGINS = originHosts.flatMap(host => [8080, options.port].map(port => `http://${host}:${port}`)).join(',');
  const viteHost = options.lan ? '0.0.0.0' : '127.0.0.1';
  const frontend = () => {
    const localUrl = `http://127.0.0.1:${options.port}`;
    const lanUrl = options.lan ? `http://${options.lanHost}:${options.port}` : '';
    log(`就绪： ${localUrl}${lanUrl ? `\n  局域网： ${lanUrl}（同事可访问）` : ''}\n  后端：${options.api}\n  Ctrl+C 停止本次开发进程。修改 C++/Python 后 Ctrl+C 再运行；前端自动热更新。`);
    launch(process.execPath, pnpmArgs(['dev', '--host', viteHost, '--port', options.port, '--strictPort']), web);
  };
  if (options.mode === 'native') {
    credentials();
    log('启动原生后端：首次编译较久；后续复用本机缓存，不使用镜像。');
    const backend = launch(nativeCommand[0], [...nativeCommand[1], '--frontend-port', options.port, ...(options.composite ? ['--composite'] : []), ...(options.soak ? ['--soak'] : [])], root, true);
    let output = ''; let started = false;
    backend.stdout.on('data', (chunk) => { process.stdout.write(chunk); output = (output + chunk).slice(-4096); if (!started && output.includes('WEBOBS_DEV_READY')) { started = true; frontend(); } });
  } else if (options.mode === 'container') {
    credentials();
    const compose = ['compose', '-f', 'compose.yaml', '-f', 'compose.dev.yaml'];
    if (options.build) run(options.engine, [...compose, 'build', ...(options.builder ? ['--builder', options.builder] : [])]);
    else { try { run(options.engine, ['image', 'inspect', 'webobs:dev'], true); } catch { throw new Error('本机没有 webobs:dev。需要容器时显式加 -Mode container -Build / --mode container --build；或使用默认原生模式。'); } }
    run(options.engine, [...compose, 'up', '-d', '--no-build', '--wait', '--wait-timeout', '120']); frontend();
  } else frontend();
} catch (error) { console.error(`\n[ERROR] ${error.message}\n帮助：Windows .\\scripts\\dev.ps1 -Help | Linux bash scripts/dev.sh --help`); stop(1); }
