import type { ReactNode } from 'react';
import LocalRuntimeBadge from './LocalRuntimeBadge';
import ProblemCenter from './ProblemCenter';

export type ProductArea = 'monitor' | 'studio' | 'devices' | 'audio' | 'events' | 'archive' | 'storage' | 'settings' | 'clients';

const entries: Array<{ id: ProductArea; label: string; short: string }> = [
  { id: 'monitor', label: '监看 Monitor', short: '监看' },
  { id: 'studio', label: 'Studio 画布', short: 'Studio' },
  { id: 'devices', label: '设备与来源', short: '设备' },
  { id: 'audio', label: '音频工作台', short: '音频' },
  { id: 'events', label: '事件', short: '事件' },
  { id: 'archive', label: '录像回放', short: '回放' },
  { id: 'storage', label: '存储', short: '存储' },
  { id: 'settings', label: '系统设置', short: '设置' },
];

export function areaFromHash(hash = window.location.hash): ProductArea {
  const route = hash.replace(/^#\/?/, '').split(/[/?]/, 1)[0];
  if (entries.some((entry) => entry.id === route) || route === 'clients') return route as ProductArea;
  if (route === 'system') return 'settings';
  if (route === 'composite') return 'monitor';
  return 'monitor';
}

export default function WorkspaceShell({ area, onNavigate, connection, children }: {
  area: ProductArea; onNavigate: (area: ProductArea) => void; connection?: 'online' | 'offline' | 'connecting'; children: ReactNode;
}) {
  return <div className="workspace-shell">
    <aside className="workspace-navigation" aria-label="主导航">
      <div className="workspace-brand"><span className="brand-mark small">W</span><div><strong>WebOBS</strong><small>MONITOR WALL</small></div></div>
      <nav>{entries.map((entry) => <button type="button" className={area === entry.id ? 'active' : ''} aria-current={area === entry.id ? 'page' : undefined} key={entry.id} onClick={() => onNavigate(entry.id)}><span>{entry.label}</span><small>{entry.short}</small></button>)}</nav>
    </aside>
    <div className="workspace-frame">
      <header className="workspace-global-bar">
        <div><strong>{entries.find((entry) => entry.id === area)?.label ?? 'WebOBS'}</strong>{connection && <span className={`connection ${connection}`}><i aria-hidden="true" />{connection === 'online' ? '在线' : connection === 'connecting' ? '连接中' : '离线'}</span>}</div>
        <div><LocalRuntimeBadge /><ProblemCenter /></div>
      </header>
      <div className="workspace-content">{children}</div>
    </div>
    <nav className="workspace-mobile-navigation" aria-label="移动端主导航">{entries.slice(0, 5).map((entry) => <button type="button" className={area === entry.id ? 'active' : ''} key={entry.id} onClick={() => onNavigate(entry.id)}>{entry.short}</button>)}</nav>
  </div>;
}
