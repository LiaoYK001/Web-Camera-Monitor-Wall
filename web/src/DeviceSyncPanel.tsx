import { lazy, Suspense, useState } from 'react';
import type { DeviceSyncModel } from './useDeviceSync';

const ClientsPanel = lazy(() => import('./ClientsPanel'));
const fieldNames: Record<string, string> = { name: '名称', canvas: '画布', sources: '来源及声音', items: '位置与图层', '*': '删除', displayName: '显示名称', favorite: '收藏', group: '分组' };

export default function DeviceSyncPanel({ model, onLoad }: { model: DeviceSyncModel; onLoad: () => void }) {
  const [pairingOpen, setPairingOpen] = useState(false);
  const { pairing, pending, state, busy, error, sync } = model;
  const approved = pairing?.state === 'approved';
  return <section className="client-section device-sync-panel" aria-label="设备离线与同步">
    <div className="section-title"><div><h2>设备离线与同步</h2>
      <p>配对后可离线编辑摄像机、文字、色块及嵌套场景。布局同步独立于服务器 Program；需要使用时，在 Studio 复制到服务器预览。</p></div></div>
    <p role="status">{approved ? `已配对 · ${pending ? `${pending} 项等待同步` : '无待上传修改'}${state?.lastSyncedAt ? ` · 最近同步 ${new Date(state.lastSyncedAt).toLocaleString()}` : ''}` : '此设备尚未完成配对；离线编辑需要管理员授权。'}</p>
    {approved && <p>离线授权至 {new Date(pairing.expiresAt).toLocaleString()}。恢复网络后自动尝试同步；浏览器关闭期间暂停。</p>}
    {error && <p className="alert" role="alert">{error}</p>}
    {!!state?.conflicts.length && <div className="alert" role="alert">
      <strong>{state.conflicts.length} 个文档发生冲突，本机内容仍保留。</strong>
      <ul>{state.conflicts.map(conflict => <li key={`${conflict.kind}:${conflict.id}`}>
        {String(state.documents.find(document => document.kind === conflict.kind && document.id === conflict.id)?.document?.name ?? (conflict.kind === 'scene' ? '场景' : '摄像机偏好')).slice(0, 128)}：{conflict.fields.map(field => fieldNames[field.field] ?? '设置').join('、')}
      </li>)}</ul>
      <p>选择对所有冲突文档生效。采用服务端会放弃这些文档的本机修改；其他待同步文档会保留。选择后可重新载入设备布局。</p>
      <button type="button" disabled={busy} onClick={() => { if (window.confirm('采用服务端版本并放弃冲突文档的本机修改？')) void sync('server'); }}>采用服务端</button>
      <button type="button" disabled={busy} onClick={() => { if (window.confirm('用本机版本替换冲突字段的服务端版本？')) void sync('local'); }}>保留本地并重试</button>
    </div>}
    <div className="device-sync-actions">
      <button type="button" disabled={!approved || busy || !navigator.onLine} onClick={() => void sync()}>{busy ? '正在同步…' : '立即同步'}</button>
      <button type="button" disabled={!approved || busy} onClick={onLoad}>载入设备布局</button>
      <button type="button" aria-expanded={pairingOpen} onClick={() => setPairingOpen(!pairingOpen)}>{pairingOpen ? '收起配对管理' : '配对与授权管理'}</button>
    </div>
    {pairingOpen && <Suspense fallback={<p>正在载入配对管理…</p>}><ClientsPanel onBack={() => setPairingOpen(false)} /></Suspense>}
  </section>;
}
