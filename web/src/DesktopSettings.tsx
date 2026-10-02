import { useEffect, useState } from 'react';
import { type DesktopStatus, type DesktopSettings as Settings } from './desktopRuntime';

export default function DesktopSettings() {
  const bridge = window.webobsDesktop;
  const [state, setState] = useState<DesktopStatus | null>(null);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => { if (!bridge) return; void bridge.status().then(setState).catch(reason => setError(String(reason))); return bridge.onStatus(setState); }, [bridge]);
  if (!bridge) return null;
  const run = async (action: () => Promise<unknown>) => { if (busy) return; setBusy(true); setError(''); try { await action(); setState(await bridge.status()); } catch (reason) { setError(reason instanceof Error ? reason.message : '桌面操作失败'); } finally { setBusy(false); } };
  const save = (values: Partial<Settings>) => void run(() => bridge.saveSettings(values));
  return <section className="desktop-settings" aria-label="Windows 客户端设置"><h2>Windows 客户端</h2>
    <p>服务：{state?.runtime.phase} · 更新：{state?.update.message || state?.update.phase}</p>
    {state?.runtime.detail && <p role="status">{state.runtime.detail}</p>}{error && <p role="alert">{error}</p>}
    {state && <fieldset disabled={busy}>
      {([['autoCheck', '自动检查正式版本更新（每 6 小时）'], ['autoDownload', '自动下载更新（安装前仍需确认）'], ['startAtLogin', '登录 Windows 时启动'], ['minimizeToTray', '关闭主窗口时保留在托盘'], ['lanEnabled', '开启局域网 HTTPS 共享']] as const).map(([key, label]) => <label key={key} className="settings-checkbox"><input type="checkbox" checked={state.settings[key]} onChange={event => save({ [key]: event.target.checked })} />{label}</label>)}
      <label>局域网 HTTPS 端口<input type="number" min="1024" max="65535" defaultValue={state.settings.lanPort} onBlur={event => { const port = event.currentTarget.valueAsNumber; if (Number.isInteger(port) && port >= 1024 && port <= 65535 && port !== state.settings.lanPort) save({ lanPort: port }); }} /></label>
      <p>录像目录：{state.settings.recordingDirectory || state.runtime.recordings || '用户 Videos / WebOBS'} <button type="button" onClick={() => void run(() => bridge.chooseRecordingDirectory())}>选择录像目录</button></p>
      <p>共享、端口和录像目录修改后需重启服务；已有录像留在原目录。重启会短暂中断媒体和录像。</p>
      <button type="button" onClick={() => void run(() => bridge.restartServices())}>应用并重启服务</button>
      <button type="button" onClick={() => void run(() => bridge.checkUpdate())}>检查更新</button>
      {state.update.phase === 'available' && <button type="button" onClick={() => void run(() => bridge.downloadUpdate())}>下载更新</button>}
      {state.update.phase === 'downloaded' && <><strong>新版本 {state.update.version}</strong><button type="button" onClick={() => void run(() => bridge.installUpdate())}>重启更新</button><span>选择稍后：继续使用当前版本，退出时不会自动安装。</span></>}
      {state.update.phase === 'downloading' && <progress max="100" value={state.update.percent || 0} />}
      {state.update.releaseNotes && <details><summary>发布说明</summary><pre>{state.update.releaseNotes}</pre></details>}
      <button type="button" onClick={() => void run(() => bridge.backup())}>创建完整配置备份</button><button type="button" onClick={() => void run(() => bridge.restore())}>从 Docker / WSL / 本机备份恢复</button>
      <p>恢复需备份的原始密钥，不会自动搬移或覆盖其他部署。默认卸载和更新保留本机用户数据。</p>
    </fieldset>}
    {state?.runtime.lan?.enabled && <article><h3>局域网访问与证书</h3>{state.runtime.lan.addresses?.map(address => <p key={address}><a href={address} target="_blank" rel="noreferrer">{address}</a></p>)}
      <code>{state.runtime.lan.certificate}</code><p style={{ whiteSpace: 'pre-line' }}>{state.runtime.lan.trustSteps}</p><details><summary>Windows 防火墙操作（管理员自行执行）</summary><p>只允许受信任私有网络，管理 API 继续经产品登录认证。关闭共享后可删除这些命名规则。</p><pre>{state.runtime.lan.firewallCommands?.join('\n')}</pre></details></article>}
  </section>;
}
