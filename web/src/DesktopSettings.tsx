import { useRef, useState } from 'react';
import { useDesktopWork, type DesktopSettings as Settings } from './desktopRuntime';
import { useDesktopStatus } from './useDesktopStatus';
import { useDraftGuard } from './useDraftGuard';

export default function DesktopSettings() {
  const { bridge, state, loading, error: readError, refresh } = useDesktopStatus();
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [portEdit, setPortEdit] = useState<string | null>(null);
  const running = useRef(false);
  const portValue = portEdit ?? String(state?.settings.lanPort ?? '');
  const port = Number(portValue);
  const validPort = portValue.trim() !== '' && Number.isInteger(port) && port >= 1024 && port <= 65535;
  const dirty = Boolean(state && portEdit !== null && portValue !== String(state.settings.lanPort));
  // Native operations own their install lock; reporting them as exports would
  // make restart/backup reject their own request.
  useDesktopWork('desktop-settings', dirty);
  useDraftGuard(dirty, busy, '局域网端口尚未保存，离开会丢弃这项修改，继续？', setNotice);
  if (!bridge) return null;
  const run = async (action: () => Promise<unknown>, message = '', refreshAfter = true) => {
    if (running.current) return false;
    running.current = true; setBusy(true); setError(''); setNotice('');
    try { await action(); if (refreshAfter) await refresh(); setNotice(message); return true; }
    catch (reason) { setError(reason instanceof Error ? reason.message : '桌面操作失败，设置已保留，可重试'); return false; }
    finally { running.current = false; setBusy(false); }
  };
  const save = (values: Partial<Settings>) => void run(() => bridge.saveSettings(values), '客户端设置已保存');
  const savePort = async () => {
    if (!dirty || !validPort) return;
    if (await run(() => bridge.saveSettings({ lanPort: port }), '端口已保存，点击“应用并重启服务”后生效')) setPortEdit(null);
  };
  return <section className="desktop-settings" aria-label="Windows 客户端设置" aria-busy={busy || loading}><h2>Windows 客户端</h2>
    <p>服务：{state?.runtime.phase === 'ready' ? '就绪' : state?.runtime.detail || (loading ? '正在读取状态…' : '状态暂不可用')} · 版本信息与更新见下方“关于与更新”。</p>
    {state?.update.phase !== 'disabled' && state?.update.signed === false && <p>当前发行版未签名，更新使用 GitHub Release 和文件摘要校验；安装仍需确认。</p>}
    {state?.runtime.detail && <p role="status">{state.runtime.detail}</p>}{(error || readError) && <p role="alert">{error || readError}</p>}
    <p role="status">{busy ? '正在处理，请稍候…' : notice}</p>
    {readError && <button type="button" disabled={busy || loading} onClick={() => void run(refresh, '客户端状态已刷新', false)}>重新读取客户端状态</button>}
    {state && <fieldset className="desktop-controls" disabled={busy}><legend className="sr-only">客户端运行设置</legend>
      {([['autoCheck', '自动检查正式版本更新（每 6 小时）'], ['autoDownload', '自动下载更新（安装前仍需确认）'], ['startAtLogin', '登录 Windows 时启动'], ['minimizeToTray', '关闭主窗口时保留在托盘'], ['lanEnabled', '开启局域网 HTTPS 共享']] as const).map(([key, label]) => <label key={key} className="settings-checkbox"><input type="checkbox" checked={state.settings[key]} onChange={event => save({ [key]: event.target.checked })} />{label}</label>)}
      <form className="desktop-port-editor" aria-label="局域网端口设置" onSubmit={(event) => { event.preventDefault(); void savePort(); }}>
        <label>局域网 HTTPS 端口<input required type="number" min="1024" max="65535" step="1" aria-invalid={dirty && !validPort} aria-describedby="desktop-port-help" value={portValue} onChange={(event) => { setPortEdit(event.target.value === String(state.settings.lanPort) ? null : event.target.value); setNotice(''); }} /></label>
        <small id="desktop-port-help">{dirty && !validPort ? '请输入 1024–65535 的整数端口；当前输入尚未保存。' : `已保存端口：${state.settings.lanPort}。修改后点击“保存端口”。`}</small>
        <div><button type="submit" disabled={!dirty || !validPort}>保存端口</button><button type="button" disabled={!dirty} onClick={() => { setPortEdit(null); setError(''); setNotice('已撤销端口修改'); }}>撤销端口修改</button></div>
      </form>
      <p>录像目录：{state.settings.recordingDirectory || state.runtime.recordings || '用户 Videos / WebOBS'} <button type="button" onClick={() => void run(() => bridge.chooseRecordingDirectory())}>选择录像目录</button></p>
      <p>共享、端口和录像目录修改后需重启服务；已有录像留在原目录。重启会短暂中断媒体和录像。</p>
      {dirty && <p>请先保存或撤销端口修改，再应用并重启服务。</p>}
      <button type="button" disabled={dirty} onClick={() => void run(() => bridge.restartServices(), '服务状态已刷新')}>应用并重启服务</button>
      <button type="button" onClick={() => void run(() => bridge.backup())}>创建完整配置备份</button><button type="button" disabled={dirty} onClick={() => void run(() => bridge.restore())}>从 Docker / WSL / 本机备份恢复</button>
      <p>恢复需备份的原始密钥，不会自动搬移或覆盖其他部署。默认卸载和更新保留本机用户数据。</p>
    </fieldset>}
    {state?.runtime.lan?.enabled && <article><h3>局域网访问与证书</h3>{state.runtime.lan.addresses?.map(address => <p key={address}><a href={address} target="_blank" rel="noreferrer">{address}</a></p>)}
      <code>{state.runtime.lan.certificate}</code><p style={{ whiteSpace: 'pre-line' }}>{state.runtime.lan.trustSteps}</p><details><summary>Windows 防火墙操作（管理员自行执行）</summary><p>只允许受信任私有网络，管理 API 继续经产品登录认证。关闭共享后可删除这些命名规则。</p><pre>{state.runtime.lan.firewallCommands?.join('\n')}</pre></details></article>}
  </section>;
}
