import { type CSSProperties, type DragEvent, type ReactNode, useEffect, useMemo, useState } from 'react';
import LocalRuntimeBadge from './LocalRuntimeBadge';
import ProblemCenter from './ProblemCenter';
import { listLocalConfigProfiles, loadActiveLocalConfigProfile, loadWorkspaceLayout, saveWorkspaceLayout, setActiveLocalConfigProfile, type LocalConfigProfile, type WorkspaceDock, type WorkspaceLayout } from './localRuntime';

export type ProductArea = 'monitor' | 'studio' | 'devices' | 'audio' | 'analytics' | 'events' | 'archive' | 'storage' | 'settings' | 'admin' | 'clients';

const entries: Array<{ id: ProductArea; label: string; short: string }> = [
  { id: 'monitor', label: '监看 Monitor', short: '监看' },
  { id: 'studio', label: 'Studio 画布', short: 'Studio' },
  { id: 'devices', label: '设备与来源', short: '设备' },
  { id: 'audio', label: '音频工作台', short: '音频' },
  { id: 'analytics', label: '分析策略', short: '分析' },
  { id: 'events', label: '事件', short: '事件' },
  { id: 'archive', label: '录像回放', short: '回放' },
  { id: 'storage', label: '存储', short: '存储' },
  { id: 'settings', label: '系统设置', short: '设置' },
  { id: 'admin', label: '集群与权限', short: '管理' },
  { id: 'clients', label: '本地客户端', short: '配对' },
];

const defaultDocks: WorkspaceDock[] = [
  { id: 'canvas', kind: 'canvas', region: 'center', order: 0, size: 60, collapsed: false },
  { id: 'scenes', kind: 'scenes', region: 'left', order: 1, size: 22, collapsed: false },
  { id: 'sources', kind: 'sources', region: 'left', order: 2, size: 22, collapsed: false },
  { id: 'audio', kind: 'audio', region: 'bottom', order: 3, size: 24, collapsed: false },
  { id: 'transitions', kind: 'transitions', region: 'right', order: 4, size: 20, collapsed: true },
  { id: 'properties', kind: 'properties', region: 'right', order: 5, size: 24, collapsed: true },
  { id: 'issues', kind: 'issues', region: 'right', order: 6, size: 24, collapsed: true },
];

function validLayout(value: WorkspaceLayout | null): WorkspaceLayout {
  if (!value || value.schemaVersion !== 1 || !['obs', 'classic'].includes(value.style)) return { schemaVersion: 1, style: 'obs', docks: defaultDocks };
  const byId = new Map(value.docks.map((dock) => [dock.id, dock]));
  const regions = new Set<WorkspaceDock['region']>(['left', 'right', 'bottom', 'center']);
  const docks = defaultDocks.map((dock) => {
    const candidate = byId.get(dock.id);
    if (!candidate || candidate.kind !== dock.kind || !regions.has(candidate.region) ||
      !Number.isFinite(candidate.size) || candidate.size < 10 || candidate.size > 80 ||
      !Number.isInteger(candidate.order) || typeof candidate.collapsed !== 'boolean') return dock;
    return { ...dock, region: candidate.region, order: candidate.order, size: candidate.size, collapsed: candidate.collapsed };
  }).sort((left, right) => left.order - right.order).map((dock, order) => ({ ...dock, order }));
  return { schemaVersion: 1, style: value.style, docks };
}

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
  const [layout, setLayout] = useState<WorkspaceLayout>({ schemaVersion: 1, style: 'obs', docks: defaultDocks });
  const [layoutLoaded, setLayoutLoaded] = useState(false);
  const [draggedDock, setDraggedDock] = useState<string | null>(null);
  const [profiles, setProfiles] = useState<LocalConfigProfile[]>([]);
  const [activeProfileId, setActiveProfileId] = useState('');
  useEffect(() => { void Promise.all([loadWorkspaceLayout(), loadActiveLocalConfigProfile()]).then(([value, active]) => { setLayout(validLayout(active?.workspaceLayout ?? value)); setLayoutLoaded(true); }); }, []);
  useEffect(() => { if (layoutLoaded) void saveWorkspaceLayout(layout); }, [layout, layoutLoaded]);
  useEffect(() => {
    const reloadProfiles = () => { void Promise.all([listLocalConfigProfiles(), loadActiveLocalConfigProfile()]).then(([next, active]) => {
      setProfiles(next); setActiveProfileId(active?.id ?? '');
      if (active?.workspaceLayout) setLayout(validLayout(active.workspaceLayout));
    }).catch(() => undefined); };
    reloadProfiles();
    window.addEventListener('webobs:config-profile-updated', reloadProfiles);
    window.addEventListener('webobs:config-profile-selected', reloadProfiles);
    return () => { window.removeEventListener('webobs:config-profile-updated', reloadProfiles); window.removeEventListener('webobs:config-profile-selected', reloadProfiles); };
  }, []);
  const reorderDock = (targetId: string) => {
    if (!draggedDock || draggedDock === targetId) return;
    setLayout((current) => {
      const docks = [...current.docks].sort((left, right) => left.order - right.order);
      const from = docks.findIndex((dock) => dock.id === draggedDock); const to = docks.findIndex((dock) => dock.id === targetId);
      if (from < 0 || to < 0) return current;
      const [item] = docks.splice(from, 1); docks.splice(to, 0, item);
      return { ...current, docks: docks.map((dock, order) => ({ ...dock, order })) };
    });
    setDraggedDock(null);
  };
  const dockLabels: Record<WorkspaceDock['kind'], string> = { canvas: '画布', scenes: '场景', sources: '来源', audio: '混音器', transitions: '转场', properties: '属性', issues: '问题' };
  const orderedDocks = useMemo(() => [...layout.docks].sort((left, right) => left.order - right.order), [layout.docks]);
  const visibleDocks = orderedDocks.filter((dock) => !dock.collapsed);
  const workspaceStyle = {
    '--workspace-visible-docks': visibleDocks.length,
    '--workspace-left-docks': visibleDocks.filter((dock) => dock.region === 'left').length,
    '--workspace-right-docks': visibleDocks.filter((dock) => dock.region === 'right').length,
  } as CSSProperties;
  const updateDock = (dockId: string, change: Partial<WorkspaceDock>) => setLayout((value) => ({
    ...value, docks: value.docks.map((dock) => dock.id === dockId ? { ...dock, ...change } : dock),
  }));
  const chooseProfile = async (id: string) => {
    try {
      await setActiveLocalConfigProfile(id || null);
      setActiveProfileId(id);
    } catch { /* The settings panel reports detailed profile errors. */ }
  };
  return <div className={`workspace-shell workspace-style-${layout.style}`} style={workspaceStyle} data-workspace-style={layout.style}>
    <aside className="workspace-navigation" aria-label="主导航">
      <div className="workspace-brand"><span className="brand-mark small">W</span><div><strong>WebOBS</strong><small>MONITOR WALL</small></div></div>
      <nav>{entries.map((entry) => <button type="button" className={area === entry.id ? 'active' : ''} aria-current={area === entry.id ? 'page' : undefined} key={entry.id} onClick={() => onNavigate(entry.id)}><span>{entry.label}</span><small>{entry.short}</small></button>)}</nav>
    </aside>
    <div className="workspace-frame">
      <header className="workspace-global-bar" data-workspace-style={layout.style}>
        <div><strong>{entries.find((entry) => entry.id === area)?.label ?? 'WebOBS'}</strong>{connection && <span className={`connection ${connection}`}><i aria-hidden="true" />{connection === 'online' ? '在线' : connection === 'connecting' ? '连接中' : '离线'}</span>}</div>
        <div><label className="config-profile-selector"><span>配置</span><select aria-label="选择本机配置" value={activeProfileId} onChange={(event) => void chooseProfile(event.target.value)}><option value="">服务器默认</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label><button type="button" className="config-profile-manage" onClick={() => onNavigate('settings')}>管理配置</button><div className="workspace-style-switch" role="group" aria-label="工作区风格"><button type="button" aria-pressed={layout.style === 'obs'} className={layout.style === 'obs' ? 'active' : ''} onClick={() => setLayout((value) => ({ ...value, style: 'obs' }))}>OBS 风格</button><button type="button" aria-pressed={layout.style === 'classic'} className={layout.style === 'classic' ? 'active' : ''} onClick={() => setLayout((value) => ({ ...value, style: 'classic' }))}>经典</button></div>{layout.style === 'obs' && <details className="workspace-dock-menu"><summary>面板</summary><div className="workspace-dock-config">{orderedDocks.map((dock) => <div className="workspace-dock-item" draggable onDragStart={() => setDraggedDock(dock.id)} onDragOver={(event: DragEvent<HTMLDivElement>) => event.preventDefault()} onDrop={() => reorderDock(dock.id)} key={dock.id}><button type="button" onClick={() => updateDock(dock.id, { collapsed: !dock.collapsed })}>{dockLabels[dock.kind]} {dock.collapsed ? '显示' : '隐藏'}</button><select aria-label={`${dockLabels[dock.kind]} 区域`} value={dock.region} onChange={(event) => updateDock(dock.id, { region: event.target.value as WorkspaceDock['region'] })}><option value="left">左</option><option value="right">右</option><option value="bottom">底部</option><option value="center">中央</option></select><label><span className="sr-only">{dockLabels[dock.kind]} 大小</span><input aria-label={`${dockLabels[dock.kind]} 大小`} type="range" min="10" max="80" step="1" value={dock.size} onChange={(event) => updateDock(dock.id, { size: Number(event.target.value) })} /></label></div>)}<button type="button" onClick={() => setLayout({ schemaVersion: 1, style: 'obs', docks: defaultDocks })}>恢复默认布局</button></div></details>}<LocalRuntimeBadge /><ProblemCenter /></div>
      </header>
      {layout.style === 'obs' ? <div className="workspace-obs-dockbar" aria-label="OBS 面板概览">
        <strong>OBS 工作区</strong>
        <div>{orderedDocks.map((dock) => <button type="button" key={dock.id} className={dock.collapsed ? 'collapsed' : 'visible'} aria-pressed={!dock.collapsed} onClick={() => updateDock(dock.id, { collapsed: !dock.collapsed })}>
          {dockLabels[dock.kind]} <small>{dock.collapsed ? '隐藏' : dock.region}</small>
        </button>)}</div>
        <span>{visibleDocks.length} 个面板可见 · 可从“面板”拖动排序、调整区域和尺寸</span>
      </div> : <div className="workspace-classic-strip" role="status">经典工作区 · 使用左侧导航和当前页面布局</div>}
      <div className="workspace-content">{children}</div>
    </div>
    <nav className="workspace-mobile-navigation" aria-label="移动端主导航">{entries.slice(0, 5).map((entry) => <button type="button" className={area === entry.id ? 'active' : ''} key={entry.id} onClick={() => onNavigate(entry.id)}>{entry.short}</button>)}<button type="button" className={area === 'clients' ? 'active' : ''} onClick={() => onNavigate('clients')}>配对</button></nav>
  </div>;
}
