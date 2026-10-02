import { type CSSProperties, type DragEvent, type ReactNode, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import LocalRuntimeBadge from './LocalRuntimeBadge';
import { fetchAccountProfile, type AccountProfile } from './api';
import { avatarChoices, roleLabel } from './accountPresentation';
import ProblemCenter from './ProblemCenter';
import Modal from './Modal';
import WorkspaceIcon from './WorkspaceIcon';
import { canLeaveWorkspace } from './navigationGuard';
import { listLocalConfigProfiles, loadActiveLocalConfigProfile, loadWorkspaceLayout, saveWorkspaceLayout, setActiveLocalConfigProfile, type LocalConfigProfile, type WorkspaceDock, type WorkspaceLayout } from './localRuntime';

export type ProductArea = 'monitor' | 'studio' | 'devices' | 'go2rtc' | 'audio' | 'analytics' | 'events' | 'archive' | 'storage' | 'settings' | 'admin' | 'account';

const entries: Array<{ id: ProductArea; label: string; short: string }> = [
  { id: 'monitor', label: '监看 Monitor', short: '监看' },
  { id: 'studio', label: 'Studio 画布', short: 'Studio' },
  { id: 'devices', label: '设备与来源', short: '设备' },
  { id: 'audio', label: '音频工作台', short: '音频' },
  { id: 'go2rtc', label: 'go2rtc 管理', short: 'go2rtc' },
  { id: 'analytics', label: '分析策略', short: '分析' },
  { id: 'events', label: '事件', short: '事件' },
  { id: 'archive', label: '录像回放', short: '回放' },
  { id: 'storage', label: '存储', short: '存储' },
  { id: 'settings', label: '系统设置', short: '设置' },
  { id: 'admin', label: '集群与权限', short: '管理' },
];
const areaDescriptions: Record<ProductArea, string> = {
  monitor: '实时画面、声音监听与多窗口投影', studio: '创建场景，调整来源与画布布局', devices: '发现摄像机、导入视频源与检测轨道',
  audio: '逐路音量、监听与声音输出', go2rtc: '视频源协议接入、配置与诊断', analytics: '识别与分析策略', events: '查看事件和告警记录',
  archive: '查找录像、回放与导出', storage: '录像存储和容量管理', settings: '账号配置、播放优化与应用更新', admin: '集群、用户与访问权限', account: '个人资料与账号安全',
};
const allEntries = [...entries, { id: 'account' as const, label: '我的账号', short: '账号' }];

const defaultDocks: WorkspaceDock[] = [
  { id: 'canvas', kind: 'canvas', region: 'center', order: 0, size: 60, collapsed: false },
  { id: 'scenes', kind: 'scenes', region: 'left', order: 1, size: 22, collapsed: false },
  { id: 'sources', kind: 'sources', region: 'left', order: 2, size: 22, collapsed: false },
  { id: 'audio', kind: 'audio', region: 'bottom', order: 3, size: 24, collapsed: false },
  { id: 'transitions', kind: 'transitions', region: 'right', order: 4, size: 20, collapsed: true },
  { id: 'properties', kind: 'properties', region: 'right', order: 5, size: 24, collapsed: false },
  { id: 'issues', kind: 'issues', region: 'right', order: 6, size: 24, collapsed: true },
];

function validLayout(value: WorkspaceLayout | null): WorkspaceLayout {
  if (!value || value.schemaVersion !== 1 || !['obs', 'classic'].includes(value.style)) return { schemaVersion: 1, style: 'obs', docks: defaultDocks };
  const byId = new Map(value.docks.map((dock) => [dock.id, dock]));
  const legacyUntouchedDocks = defaultDocks.every((dock) => {
    const saved = byId.get(dock.id);
    return saved && saved.region === dock.region && saved.order === dock.order && saved.size === dock.size &&
      saved.collapsed === (dock.kind === 'properties' ? true : dock.collapsed);
  });
  const regions = new Set<WorkspaceDock['region']>(['left', 'right', 'bottom', 'center']);
  const docks = defaultDocks.map((dock) => {
    const candidate = byId.get(dock.id);
    if (!candidate || candidate.kind !== dock.kind || !regions.has(candidate.region) ||
      !Number.isFinite(candidate.size) || candidate.size < 10 || candidate.size > 80 ||
      !Number.isInteger(candidate.order) || typeof candidate.collapsed !== 'boolean') return dock;
    return { ...dock,
      region: (dock.kind === 'sources' || dock.kind === 'properties') && candidate.region !== 'left' && candidate.region !== 'right' ? dock.region : candidate.region,
      order: candidate.order, size: candidate.size, collapsed: dock.kind === 'canvas' || (dock.kind === 'properties' && legacyUntouchedDocks) ? false : candidate.collapsed };
  }).sort((left, right) => left.order - right.order).map((dock, order) => ({ ...dock, order }));
  return { schemaVersion: 1, style: value.style, docks };
}

export function areaFromHash(hash = window.location.hash): ProductArea {
  const route = hash.replace(/^#\/?/, '').split(/[/?]/, 1)[0];
  if (entries.some((entry) => entry.id === route)) return route as ProductArea;
  if (route === 'account') return 'account';
  if (route === 'clients') return 'settings';
  if (route === 'system') return 'settings';
  if (route === 'composite') return 'monitor';
  return 'monitor';
}

export default function WorkspaceShell({ area, onNavigate: navigate, connection, children }: {
  area: ProductArea; onNavigate: (area: ProductArea) => void; connection?: 'online' | 'offline' | 'connecting'; children: ReactNode;
}) {
  const onNavigate = (next: ProductArea) => {
    if (next !== area && !canLeaveWorkspace()) return false;
    if (next !== area) navigate(next);
    setNavigationOpen(false); setSearchOpen(false);
    return true;
  };
  const [layout, setLayout] = useState<WorkspaceLayout>({ schemaVersion: 1, style: 'obs', docks: defaultDocks });
  const [layoutLoaded, setLayoutLoaded] = useState(false);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [searchIndex, setSearchIndex] = useState(0);
  const searchResults = allEntries.filter((entry) => `${entry.label} ${entry.short} ${areaDescriptions[entry.id]}`.toLowerCase().includes(search.trim().toLowerCase()));
  const openSearch = () => { setSearch(''); setSearchIndex(0); setSearchOpen(true); };
  const previousArea = useRef(area);
  useEffect(() => {
    if (previousArea.current === area) return;
    previousArea.current = area;
    const content = document.getElementById('workspace-main');
    content?.focus({ preventScroll: true });
    if (content) content.scrollTop = 0;
    window.scrollTo({ top: 0, behavior: 'instant' });
  }, [area]);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === 'k' && !event.isComposing && !document.querySelector('dialog[open]')) {
        event.preventDefault(); openSearch();
      }
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, []);
  const [layoutError, setLayoutError] = useState('');
  const [profileStatus, setProfileStatus] = useState('');
  const savedLayout = useRef('');
  const layoutWrites = useRef(Promise.resolve());
  const queuedLayoutWrites = useRef(0);
  const latestLayout = useRef(layout);
  useEffect(() => setNavigationOpen(false), [area]);
  const [draggedDock, setDraggedDock] = useState<string | null>(null);
  const [profiles, setProfiles] = useState<LocalConfigProfile[]>([]);
  const [activeProfileId, setActiveProfileId] = useState('');
  const [profileSwitching, setProfileSwitching] = useState(false);
  const switchingProfile = useRef(false);
  const [accountProfile, setAccountProfile] = useState<AccountProfile | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    const refresh = () => { void fetchAccountProfile(controller.signal).then(setAccountProfile).catch(() => undefined); };
    refresh(); window.addEventListener('webobs:account-profile-updated', refresh);
    return () => { controller.abort(); window.removeEventListener('webobs:account-profile-updated', refresh); };
  }, []);
  useEffect(() => {
    let cancelled = false;
    void Promise.all([loadWorkspaceLayout(), loadActiveLocalConfigProfile()]).then(([value, active]) => {
      if (cancelled) return;
      const next = validLayout(active?.workspaceLayout ?? value);
      savedLayout.current = JSON.stringify(next);
      setLayout(next); setLayoutLoaded(true);
    }).catch(() => { if (!cancelled) setLayoutError('工作区布局读取失败，请刷新重试。'); });
    return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    latestLayout.current = layout;
    const encoded = JSON.stringify(layout);
    if (!layoutLoaded || (encoded === savedLayout.current && queuedLayoutWrites.current === 0)) return;
    const timer = window.setTimeout(() => {
      queuedLayoutWrites.current += 1;
      layoutWrites.current = layoutWrites.current.catch(() => undefined).then(async () => {
        const next = latestLayout.current;
        const serialized = JSON.stringify(next);
        if (serialized !== savedLayout.current) {
          await saveWorkspaceLayout(next);
          savedLayout.current = serialized;
        }
      }).catch(() => setLayoutError('工作区布局保存失败，请稍后重试。'))
        .finally(() => { queuedLayoutWrites.current -= 1; });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [layout, layoutLoaded]);
  useEffect(() => {
    const reloadProfiles = () => { void Promise.all([listLocalConfigProfiles(), loadActiveLocalConfigProfile()]).then(([next, active]) => {
      setProfiles(next); setActiveProfileId(active?.id ?? '');
      if (active?.workspaceLayout) {
        const next = validLayout(active.workspaceLayout);
        savedLayout.current = JSON.stringify(next);
        setLayout(next);
      }
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
  const studioDocks = orderedDocks.filter((dock) => ['canvas', 'sources', 'properties'].includes(dock.kind));
  const visibleDocks = studioDocks.filter((dock) => !dock.collapsed);
  const sourceDock = studioDocks.find((dock) => dock.kind === 'sources')!;
  const propertyDock = studioDocks.find((dock) => dock.kind === 'properties')!;
  const positionOrder = [
    ...[sourceDock, propertyDock].filter((dock) => dock.region === 'left').sort((left, right) => left.order - right.order),
    studioDocks.find((dock) => dock.kind === 'canvas')!,
    ...[sourceDock, propertyDock].filter((dock) => dock.region !== 'left').sort((left, right) => left.order - right.order),
  ];
  const workspaceStyle = {
    '--workspace-visible-docks': visibleDocks.length,
    '--workspace-left-docks': visibleDocks.filter((dock) => dock.region === 'left').length,
    '--workspace-right-docks': visibleDocks.filter((dock) => dock.region === 'right').length,
    '--studio-source-order': positionOrder.findIndex((dock) => dock.kind === 'sources'),
    '--studio-canvas-order': positionOrder.findIndex((dock) => dock.kind === 'canvas'),
    '--studio-property-order': positionOrder.findIndex((dock) => dock.kind === 'properties'),
    '--studio-source-width': `${Math.max(180, Math.min(420, sourceDock.size * 12))}px`,
    '--studio-property-width': `${Math.max(180, Math.min(420, propertyDock.size * 12))}px`,
  } as CSSProperties;
  const updateDock = (dockId: string, change: Partial<WorkspaceDock>) => setLayout((value) => ({
    ...value, docks: value.docks.map((dock) => dock.id === dockId ? { ...dock, ...change } : dock),
  }));
  const chooseProfile = async (id: string) => {
    if (switchingProfile.current || id === activeProfileId || !canLeaveWorkspace()) return;
    switchingProfile.current = true; setProfileSwitching(true);
    try {
      setProfileStatus('正在切换账号配置…');
      await setActiveLocalConfigProfile(id || null);
      setActiveProfileId(id);
      setProfileStatus(id ? '账号配置已切换，场景正在载入。' : '已切回服务器默认配置。');
    } catch (reason) { setProfileStatus(reason instanceof Error ? reason.message : '切换账号配置失败'); }
    finally { switchingProfile.current = false; setProfileSwitching(false); }
  };
  return <div className={`workspace-shell workspace-style-${layout.style}`} style={workspaceStyle} data-product-area={area} data-workspace-style={layout.style} data-studio-sources={sourceDock.collapsed ? 'hidden' : 'visible'} data-studio-properties={propertyDock.collapsed ? 'hidden' : 'visible'}>
    <a className="skip-navigation" href="#workspace-main" onClick={(event) => { event.preventDefault(); document.getElementById('workspace-main')?.focus(); }}>跳到主要内容</a>
    <aside className="workspace-navigation" aria-label="主导航">
      <div className="workspace-brand"><span className="brand-mark small">W</span><div><strong>WebOBS</strong><small>MONITOR WALL</small></div></div>
      <button type="button" className="workspace-search-button" aria-label="搜索页面" aria-keyshortcuts="Control+k Meta+k" onClick={openSearch}><WorkspaceIcon name="search" /><span>快速切换</span><kbd>Ctrl K</kbd></button>
      <nav>{entries.map((entry, index) => <div className="workspace-nav-entry" key={entry.id}>
        {[0, 4, 9].includes(index) && <p className="workspace-nav-group">{index === 0 ? '工作台' : index === 4 ? '媒体与数据' : '系统'}</p>}
        <button type="button" title={entry.label} className={area === entry.id ? 'active' : ''} aria-label={entry.label} aria-current={area === entry.id ? 'page' : undefined} onClick={() => onNavigate(entry.id)}><WorkspaceIcon name={entry.id} /><span>{entry.label}</span><small>{entry.short}</small></button>
      </div>)}</nav>
    </aside>
    <div className="workspace-frame">
      <header className="workspace-global-bar" data-workspace-style={layout.style}>
        <div><strong>{area === 'account' ? '我的账号' : entries.find((entry) => entry.id === area)?.label ?? 'WebOBS'}</strong>{connection && <span className={`connection ${connection}`}><i aria-hidden="true" />{connection === 'online' ? '在线' : connection === 'connecting' ? '连接中' : '离线'}</span>}</div>
        <div><label className="config-profile-selector"><span>配置</span><select aria-label="选择账号配置" disabled={profileSwitching} value={activeProfileId} onChange={(event) => void chooseProfile(event.target.value)}><option value="">服务器默认</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label><button type="button" className="config-profile-manage" onClick={() => onNavigate('settings')}>管理配置</button><div className="workspace-style-switch" role="group" aria-label="工作区风格"><button type="button" aria-pressed={layout.style === 'obs'} className={layout.style === 'obs' ? 'active' : ''} onClick={() => setLayout((value) => ({ ...value, style: 'obs' }))}>OBS 风格</button><button type="button" aria-pressed={layout.style === 'classic'} className={layout.style === 'classic' ? 'active' : ''} onClick={() => setLayout((value) => ({ ...value, style: 'classic' }))}>经典</button></div>{layout.style === 'obs' && <details className="workspace-dock-menu"><summary>面板</summary><div className="workspace-dock-config">{studioDocks.filter((dock) => dock.kind !== 'canvas').map((dock) => <div className="workspace-dock-item" draggable onDragStart={() => setDraggedDock(dock.id)} onDragOver={(event: DragEvent<HTMLDivElement>) => event.preventDefault()} onDrop={() => reorderDock(dock.id)} key={dock.id}><button type="button" onClick={() => updateDock(dock.id, { collapsed: !dock.collapsed })}>{dockLabels[dock.kind]} {dock.collapsed ? '显示' : '隐藏'}</button><select aria-label={`${dockLabels[dock.kind]} 区域`} value={dock.region} onChange={(event) => updateDock(dock.id, { region: event.target.value as WorkspaceDock['region'] })}><option value="left">左</option><option value="right">右</option></select><label><span className="sr-only">{dockLabels[dock.kind]} 大小</span><input aria-label={`${dockLabels[dock.kind]} 大小`} type="range" min="10" max="80" step="1" value={dock.size} onChange={(event) => updateDock(dock.id, { size: Number(event.target.value) })} /></label></div>)}<button type="button" onClick={() => setLayout({ schemaVersion: 1, style: 'obs', docks: defaultDocks })}>恢复默认布局</button></div></details>}<LocalRuntimeBadge /><ProblemCenter />{accountProfile && <button type="button" className="account-badge" onClick={() => onNavigate('account')} aria-label={`我的账号 ${accountProfile.displayName} ${accountProfile.roles.map(roleLabel).join('、')}`}><span className="account-avatar">{avatarChoices.find((choice) => choice.id === accountProfile.avatar)?.icon ?? '●'}</span><span><strong>{accountProfile.displayName}</strong><small>{accountProfile.roles.map(roleLabel).join('、')}</small></span></button>}</div>
      </header>
      {area === 'studio' && (layout.style === 'obs' ? <div className="workspace-obs-dockbar" aria-label="OBS 面板概览">
        <strong>OBS 工作区</strong>
        <div>{studioDocks.filter((dock) => dock.kind !== 'canvas').map((dock) => <button type="button" key={dock.id} className={dock.collapsed ? 'collapsed' : 'visible'} aria-pressed={!dock.collapsed} onClick={() => updateDock(dock.id, { collapsed: !dock.collapsed })}>
          {dockLabels[dock.kind]} <small>{dock.collapsed ? '隐藏' : dock.region}</small>
        </button>)}</div>
        <span>画布固定居中 · {visibleDocks.length - 1} 个侧栏可见 · 从“面板”调整区域和尺寸</span>
      </div> : <div className="workspace-classic-strip" role="status">经典工作区 · 使用左侧导航和当前页面布局</div>)}
      <div id="workspace-main" className="workspace-content" tabIndex={-1}>{layoutError && <p className="inline-error" role="alert">{layoutError}</p>}{profileStatus && <p className="config-profile-notice" role="status">{profileStatus}</p>}<Suspense fallback={<div className="page-panel workspace-loading" role="status"><span className="loading-indicator" aria-hidden="true" />正在加载页面…</div>}>{children}</Suspense></div>
    </div>
    <nav className="workspace-mobile-navigation" aria-label="移动端主导航">{entries.slice(0, 4).map((entry) => <button type="button" className={area === entry.id ? 'active' : ''} key={entry.id} aria-current={area === entry.id ? 'page' : undefined} onClick={() => onNavigate(entry.id)}><WorkspaceIcon name={entry.id} />{entry.short}</button>)}<button type="button" aria-haspopup="dialog" aria-expanded={navigationOpen} className={entries.slice(4).some((entry) => entry.id === area) || area === 'account' ? 'active' : ''} onClick={() => setNavigationOpen(true)}><WorkspaceIcon name="more" />更多</button></nav>
    {navigationOpen && <Modal label="全部页面" className="navigation-modal" onClose={() => setNavigationOpen(false)}>
      <header><h2>全部页面</h2><button type="button" onClick={() => setNavigationOpen(false)}>关闭</button></header>
      <div className="mobile-style-picker" role="group" aria-label="移动端工作区风格"><button type="button" aria-pressed={layout.style === 'obs'} onClick={() => setLayout((value) => ({ ...value, style: 'obs' }))}>OBS 风格</button><button type="button" aria-pressed={layout.style === 'classic'} onClick={() => setLayout((value) => ({ ...value, style: 'classic' }))}>经典</button></div>
      <nav aria-label="全部页面">{allEntries.map((entry) =>
        <button type="button" key={entry.id} aria-label={entry.label} aria-current={area === entry.id ? 'page' : undefined} onClick={() => onNavigate(entry.id)}><WorkspaceIcon name={entry.id} /><span>{entry.label}<small>{areaDescriptions[entry.id]}</small></span></button>)}</nav>
    </Modal>}
    {searchOpen && <Modal label="快速切换页面" className="workspace-search-modal" onClose={() => setSearchOpen(false)}>
      <header><h2>快速切换页面</h2><button type="button" onClick={() => setSearchOpen(false)}>关闭</button></header>
      <label className="workspace-search-field"><WorkspaceIcon name="search" /><input autoFocus data-modal-autofocus aria-label="搜索页面名称或功能" aria-describedby="workspace-search-help" aria-controls="workspace-search-results" placeholder="搜索页面名称或功能…" maxLength={128} value={search} onChange={(event) => { setSearch(event.target.value); setSearchIndex(0); }} onKeyDown={(event) => {
        if (event.nativeEvent.isComposing) return;
        if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) && searchResults.length) {
          // Home/End keep their normal text editing behavior when a query is present.
          if (search && ['Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? searchResults.length - 1 : (searchIndex + (event.key === 'ArrowDown' ? 1 : -1) + searchResults.length) % searchResults.length;
          setSearchIndex(next);
          document.getElementById(`workspace-search-${searchResults[next].id}`)?.scrollIntoView({ block: 'nearest' });
        } else if (event.key === 'Enter' && searchResults[searchIndex]) { event.preventDefault(); onNavigate(searchResults[searchIndex].id); }
      }} /></label>
      <nav id="workspace-search-results" aria-label="页面搜索结果">{searchResults.map((entry, index) => <button type="button" key={entry.id} id={`workspace-search-${entry.id}`} className={index === searchIndex ? 'highlighted' : ''} aria-label={entry.label} aria-current={area === entry.id ? 'page' : undefined} onClick={() => onNavigate(entry.id)}><WorkspaceIcon name={entry.id} /><span>{entry.label}<small>{areaDescriptions[entry.id]}</small></span>{area === entry.id && <small>当前</small>}</button>)}</nav>
      <p role="status" className={searchResults.length ? 'sr-only' : 'workspace-search-empty'}>{searchResults.length ? `${searchResults.length} 个页面，当前选择 ${searchResults[searchIndex]?.label ?? ''}` : '没有匹配的页面，试试“声音”“投影”或“更新”。'}</p>
      <p id="workspace-search-help" className="workspace-search-help">↑ ↓ 选择 · Enter 打开 · Esc 关闭</p>
    </Modal>}
  </div>;
}
