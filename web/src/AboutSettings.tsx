import { useEffect, useState } from 'react';
import type { DesktopStatus } from './desktopRuntime';
import { checkPwaUpdate } from './pwaRuntime';

const repository = 'https://github.com/LiaoYK001/Web-Camera-Monitor-Wall';
const updateLabels: Record<string, string> = {
  idle: '可以检查正式版本更新', checking: '正在检查更新…', current: '已是最新正式版本',
  available: '发现新版本', downloading: '正在下载更新…', downloaded: '更新已下载，等待安装',
  preparing: '正在准备更新…', error: '更新未完成，可以重试', disabled: '开发测试包不连接正式更新源',
};

export default function AboutSettings() {
  const bridge = window.webobsDesktop;
  const [state, setState] = useState<DesktopStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => {
    if (!bridge) return;
    let active = true;
    void bridge.status().then(value => { if (active) setState(value); }).catch(() => { if (active) setError('无法读取客户端信息，请稍后重试。'); });
    const unsubscribe = bridge.onStatus(value => { if (active) setState(value); });
    return () => { active = false; unsubscribe(); };
  }, [bridge]);
  const run = async (action: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try { await action(); if (bridge) setState(await bridge.status()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '更新检查失败，请稍后重试。'); }
    finally { setBusy(false); }
  };
  const checkPage = async () => {
    let result: Awaited<ReturnType<typeof checkPwaUpdate>>;
    try { result = await checkPwaUpdate(); }
    catch { throw new Error('页面更新检查失败，请确认网络和服务器可用后重试。'); }
    setNotice(result === 'checked' ? '已检查当前服务器的页面更新。发现新版页面时会自动加载。' :
      result === 'unavailable' ? '页面更新尚未就绪，请稍后重试。' : '此浏览器需要受信任的 HTTPS 或本机安全地址才能检查页面更新。');
  };
  const version = bridge ? state?.app?.version : __WEBOBS_BUILD_VERSION__;
  const update = state?.update;
  const pending = busy || ['checking', 'downloading', 'downloaded', 'preparing', 'disabled'].includes(update?.phase || '');
  const lastChecked = update?.lastCheckedAt ? new Date(update.lastCheckedAt) : null;
  return <section className="about-settings" aria-label="关于与更新">
    <header className="about-heading"><img src="/webobs-icon.svg" width="56" height="56" alt="" /><div><span className="eyebrow">About WebOBS</span><h2>关于与更新</h2><p>WebOBS · Web Camera Monitor Wall</p></div>{version && <span className="about-channel">{version.includes('-') ? '开发版' : '正式版'}</span>}</header>
    <p>开源监控墙，统一管理摄像机、场景、多窗口投影与 go2rtc 视频源。</p>
    <dl className="about-facts">
      <div><dt>当前版本</dt><dd>{bridge && !state ? '正在读取…' : version || '客户端未报告，请查看 WebUI 构建信息'}</dd></div>
      <div><dt>运行方式</dt><dd>{bridge ? `Windows 客户端 · ${state?.app?.architecture || 'x64'}` : '浏览器 / PWA'}</dd></div>
      <div><dt>WebUI 构建</dt><dd>{__WEBOBS_BUILD_VERSION__}</dd></div>
      <div><dt>开源许可证</dt><dd><a href={`${repository}/blob/main/LICENSE`} target="_blank" rel="noopener noreferrer">GPL-2.0-or-later</a></dd></div>
    </dl>
    <div className="about-update" aria-busy={busy || update?.phase === 'checking'}>
      {bridge ? <>
        <div className="about-update-heading"><strong role="status">{state ? updateLabels[update?.phase || ''] || '更新状态暂不可用' : '正在读取更新状态…'}</strong><button type="button" disabled={pending} onClick={() => void run(() => state ? bridge.checkUpdate() : bridge.status())}>{update?.phase === 'checking' ? '正在检查…' : state ? '检查更新' : '重新读取更新状态'}</button></div>
        {update?.message && <p>{update.message}</p>}
        {lastChecked && !Number.isNaN(lastChecked.getTime()) && <small>最近成功检查：{lastChecked.toLocaleString()}</small>}
        {update?.version && ['available', 'downloading', 'downloaded', 'preparing'].includes(update.phase) && <p>可更新至 <strong>{update.version}</strong></p>}
        {update?.phase === 'available' && <button type="button" disabled={busy} onClick={() => void run(() => bridge.downloadUpdate())}>下载更新</button>}
        {update?.phase === 'downloading' && <div className="about-progress"><progress aria-label="更新下载进度" max="100" value={update.percent || 0} /><span>{update.percent || 0}%</span></div>}
        {update?.phase === 'downloaded' && <div className="about-install"><button className="primary-button" type="button" disabled={busy} onClick={() => void run(() => bridge.installUpdate())}>重启更新</button><span>可稍后安装；关闭或退出客户端不会自动安装。</span></div>}
        {update?.releaseNotes && <details><summary>新版本发布说明</summary><pre>{update.releaseNotes}</pre></details>}
        <p>正式安装版通过 GitHub Release 更新，安装前需确认。自动检查和下载可在上方客户端设置中调整。</p>
      </> : <>
        <div className="about-update-heading"><strong>页面更新</strong><button type="button" disabled={busy} onClick={() => void run(checkPage)}>{busy ? '正在检查…' : '检查页面更新'}</button></div>
        <p>页面随当前服务器更新。Docker / Podman 部署需由维护者更新镜像；Windows 客户端可通过正式安装包自动更新。</p>
      </>}
      {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
    </div>
    <nav className="about-links" aria-label="开源项目链接">
      {[[repository, 'GitHub 开源仓库'], [`${repository}/releases`, '版本发布与更新记录'], [`${repository}/issues`, '反馈问题'], [`${repository}/blob/main/README.md`, '使用说明']].map(([href, label]) => <a key={href} href={href} target="_blank" rel="noopener noreferrer">{label}<span aria-hidden="true"> ↗</span></a>)}
    </nav>
    <p className="about-repository">{repository}</p>
    <small>© 2026 LYKK231 与项目贡献者 · 感谢 OBS Studio、go2rtc 及其他开源组件。</small>
  </section>;
}
