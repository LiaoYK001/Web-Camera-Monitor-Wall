import { useState, useSyncExternalStore } from 'react';
import { getControlConnections, subscribeControlConnections, reconnectControlConnections,
  type ControlConnectionPhase, type ControlConnectionReason } from './controlConnectionStatus';
import { isPageVisible } from './pageVisibility';

const phases: Record<ControlConnectionPhase, string> = { connecting: '连接中，等待场景', online: '场景同步正常', retrying: '等待自动重试', offline: '网络已断开', paused: '后台暂停重试' };
const reasons: Record<ControlConnectionReason, string> = { '': '无', network_offline: '设备离线', connection_timeout: '连接超时', snapshot_timeout: '未收到有效场景', transport_error: '连接失败', transport_closed: '连接已断开', constructor_failed: '无法创建连接', resume: '恢复前台或网络', manual: '手动重新连接' };
const time = (value: number | null) => value === null ? '尚无' : new Date(value).toLocaleTimeString();

function ControlDiagnostics() {
  const connections = useSyncExternalStore(subscribeControlConnections, getControlConnections);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const copy = async () => {
    setNotice(''); setError('');
    const diagnostic = { format: 'webobs-control-diagnostics-v1', build: __WEBOBS_BUILD_VERSION__,
      client: window.webobsDesktop ? 'windows' : typeof window.webobsAndroidForeground === 'boolean' ? 'android' : 'browser',
      capturedAt: Date.now(), networkOnline: navigator.onLine, foreground: isPageVisible(), connections };
    try { await navigator.clipboard.writeText(JSON.stringify(diagnostic, null, 2)); setNotice('已复制当前窗口的诊断计数'); }
    catch { setError('剪贴板不可用，可展开“诊断数据”手动复制。'); }
  };
  return <div className="control-diagnostics">
    <p>WebUI {__WEBOBS_BUILD_VERSION__} · 当前窗口 {connections.length} 个场景同步连接。此处的同步状态与视频播放状态分别检测。</p>
    {connections.map((connection) => <article key={connection.id}>
      <h3>连接 {connection.id} · {phases[connection.phase]}</h3>
      <dl><div><dt>连接尝试 / 失败</dt><dd>{connection.attempts} / {connection.failures}</dd></div>
        <div><dt>有效 / 拒绝消息</dt><dd>{connection.messages} / {connection.rejectedMessages}</dd></div>
        <div><dt>最近场景</dt><dd>{time(connection.lastSnapshotAt)}</dd></div>
        <div><dt>下次重试</dt><dd>{time(connection.nextRetryAt)}</dd></div>
        <div><dt>最近原因</dt><dd>{reasons[connection.reason]}</dd></div></dl>
    </article>)}
    {!connections.length && <p>当前窗口没有场景同步连接。</p>}
    <div className="control-diagnostics-actions"><button type="button" disabled={!connections.some((connection) => connection.phase === 'online' || connection.phase === 'retrying')} onClick={() => { reconnectControlConnections(); setNotice('已请求重新连接场景同步'); setError(''); }}>重新连接场景同步</button>
      <button type="button" onClick={() => void copy()}>复制诊断计数</button></div>
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
    <details><summary>诊断数据</summary><pre>{JSON.stringify({ format: 'webobs-control-diagnostics-v1', build: __WEBOBS_BUILD_VERSION__, connections }, null, 2)}</pre></details>
  </div>;
}
export default function DeveloperDiagnostics() {
  const [enabled, setEnabled] = useState(false);
  return <section className="developer-diagnostics" aria-label="开发者诊断">
    <h2>开发者诊断</h2>
    <label className="settings-checkbox"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />显示当前窗口的场景同步诊断</label>
    <p>按需开启。仅展示状态、时间和计数，帮助定位断线或更新延迟；复制内容不包含摄像机地址、场景内容、账号或密钥。</p>
    {enabled && <ControlDiagnostics />}
  </section>;
}
