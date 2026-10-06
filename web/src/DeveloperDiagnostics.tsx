import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { getControlConnections, subscribeControlConnections, reconnectControlConnections,
  type ControlConnectionPhase, type ControlConnectionReason } from './controlConnectionStatus';
import { isPageVisible } from './pageVisibility';
import { DIAGNOSTIC_LIMITS, injectedVersion, safeControl } from './diagnosticsRuntime';
import { captureSupportReport, downloadSupportReport } from './supportReport';

const phases: Record<ControlConnectionPhase, string> = { connecting: '连接中，等待场景', online: '场景同步正常', retrying: '等待自动重试', offline: '网络已断开', paused: '后台暂停重试' };
const reasons: Record<ControlConnectionReason, string> = { '': '无', network_offline: '设备离线', connection_timeout: '连接超时', snapshot_timeout: '未收到有效场景', transport_error: '连接失败', transport_closed: '连接已断开', constructor_failed: '无法创建连接', resume: '恢复前台或网络', manual: '手动重新连接' };
const time = (value: number | null) => value === null ? '尚无' : new Date(value).toLocaleTimeString();

function ControlDiagnostics() {
  const connections = useSyncExternalStore(subscribeControlConnections, getControlConnections);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const copy = async () => {
    setNotice(''); setError('');
    const diagnostic = { format: 'webobs-control-diagnostics-v1', build: injectedVersion(__WEBOBS_BUILD_VERSION__),
      client: window.webobsDesktop ? 'desktop-bridge' : typeof window.webobsAndroidForeground === 'boolean' ? 'android' : 'browser',
      capturedAt: Date.now(), networkOnline: navigator.onLine, foreground: isPageVisible(), connections: connections.map(safeControl) };
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
    <details><summary>诊断数据</summary><pre>{JSON.stringify({ format: 'webobs-control-diagnostics-v1', build: injectedVersion(__WEBOBS_BUILD_VERSION__), connections: connections.map(safeControl) }, null, 2)}</pre></details>
  </div>;
}
function SupportReport() {
  const [report, setReport] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const generation = useRef(0), pending = useRef(false);
  useEffect(() => () => { generation.current++; }, []);
  const generate = async () => {
    if (pending.current) return;
    pending.current = true; const owner = ++generation.current;
    setBusy(true); setError(''); setNotice(''); setReport('');
    try {
      const value = await captureSupportReport();
      if (generation.current !== owner) return;
      setReport(value); setNotice('支持报告已生成，仅保留在本页；尚未复制、下载或上传。');
    } catch {
      if (generation.current === owner) setError('无法生成有界支持报告，请稍后重试。');
    } finally {
      if (generation.current === owner) { pending.current = false; setBusy(false); }
    }
  };
  const copy = async () => {
    setNotice(''); setError('');
    try { await navigator.clipboard.writeText(report); setNotice('支持报告已复制。'); }
    catch { setError('剪贴板不可用，请从“支持报告内容”手动复制，或下载报告。'); }
  };
  return <section aria-label="安全支持报告">
    <h3>安全支持报告</h3>
    <p>用户主动生成当前窗口的结构化快照，最多 {DIAGNOSTIC_LIMITS.bytes / 1024} KiB。不上传，不读取日志、媒体或额外服务接口；可读取原生客户端提供的只读状态（最多等待 1.5 秒）。</p>
    <p>仅含固定状态、时间、计数和实际注入的版本。未提供的 APK、WebView、Electron、源码身份或服务重启原因/次数均标为 unavailable，不根据浏览器推测。未观察或超过 30 秒的缓存会标明；不代表实时健康检查。</p>
    <div className="control-diagnostics-actions">
      <button type="button" disabled={busy} onClick={() => void generate()}>{busy ? '正在生成支持报告…' : '生成支持报告'}</button>
      <button type="button" disabled={!report || busy} onClick={() => {
        setNotice(''); setError('');
        try { downloadSupportReport(report); setNotice('已请求浏览器下载；若客户端未提供下载，请复制报告。'); }
        catch { setError('下载不可用，请复制支持报告。'); }
      }}>下载支持报告</button>
      <button type="button" disabled={!report || busy} onClick={() => void copy()}>复制支持报告</button>
    </div>
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
    {report && <><p>快照生成后不会自动更新；复现问题后可重新生成。大小 {new TextEncoder().encode(report).byteLength} 字节。分享前请复核。</p>
      <label>支持报告内容<textarea aria-label="支持报告内容" readOnly value={report} rows={10} style={{ width: '100%', maxWidth: '100%', boxSizing: 'border-box', overflowWrap: 'anywhere' }} /></label></>}
  </section>;
}
export default function DeveloperDiagnostics() {
  const [enabled, setEnabled] = useState(false);
  return <section className="developer-diagnostics" aria-label="开发者诊断">
    <h2>开发者诊断</h2>
    <label className="settings-checkbox"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />显示当前窗口的场景同步诊断</label>
    <p>按需开启。仅展示状态、时间和计数，帮助定位断线或更新延迟；复制内容不包含摄像机地址、场景内容、账号或密钥。</p>
    {enabled && <><ControlDiagnostics /><SupportReport /></>}
  </section>;
}
