import { useEffect, useState } from 'react';
import type { DesktopDisplay } from './desktopRuntime';
import Modal from './Modal';
import type { SceneDocument, SceneSource, StudioDocument } from './types';

export type SceneOperation = 'duplicate' | 'delete' | 'up' | 'down' | 'top' | 'bottom' | 'lock' | 'unlock' | 'grid' | 'projector';
export function cameraSourceId(cameraId: string, profileId: string): string {
  let hash = 0xcbf29ce484222325n;
  for (const byte of new TextEncoder().encode(`${cameraId}\0${profileId}`)) {
    hash = BigInt.asUintN(64, (hash ^ BigInt(byte)) * 0x100000001b3n);
  }
  return `source-camera-${hash.toString(16).padStart(16, '0')}`;
}
export function arrangeSceneGrid(scene: SceneDocument): SceneDocument {
  const columns = Math.max(1, Math.ceil(Math.sqrt(scene.items.length)));
  const rows = Math.max(1, Math.ceil(scene.items.length / columns));
  return { ...scene, items: scene.items.map((item, index) => {
    if (item.locked) return item;
    const column = index % columns, row = Math.floor(index / columns);
    const x = Math.floor(column * scene.canvas.width / columns), y = Math.floor(row * scene.canvas.height / rows);
    return { ...item, x, y, width: Math.floor((column + 1) * scene.canvas.width / columns) - x,
      height: Math.floor((row + 1) * scene.canvas.height / rows) - y, rotation: 0 };
  }) };
}

export default function SceneCollection({ studio, selected, sources, savedSceneIds, serverOperations = true, onSelect, onOperation, onUpdate, onCreate }: {
  studio: StudioDocument; selected: string; sources: SceneSource[]; savedSceneIds: string[];
  serverOperations?: boolean;
  onSelect: (id: string) => void; onOperation: (id: string, operation: SceneOperation) => void;
  onUpdate: (scene: SceneDocument) => void; onCreate: (scene: SceneDocument) => void;
}) {
  const [menu, setMenu] = useState<string | null>(null);
  const [editing, setEditing] = useState<SceneDocument | null>(null);
  const [mode, setMode] = useState<'rename' | 'canvas' | 'sources' | 'new' | 'delete'>('rename');
  const [checked, setChecked] = useState<string[]>([]);
  const [sourceQuery, setSourceQuery] = useState('');
  const [displays, setDisplays] = useState<DesktopDisplay[]>([]);
  const [displayId, setDisplayId] = useState('');
  const [fullscreen, setFullscreen] = useState(false);
  const [projectorError, setProjectorError] = useState('');
  useEffect(() => { if (menu && window.webobsDesktop) void window.webobsDesktop.displays().then(setDisplays).catch(() => setProjectorError('无法读取显示器，请刷新后重试')); }, [menu]);
  const scene = studio.scenes.find((value) => value.id === menu);
  const open = (target: SceneDocument, next: typeof mode) => {
    setMenu(null); setMode(next); setEditing(structuredClone(target)); setChecked(target.sources.map((source) => source.id)); setSourceQuery('');
  };
  const add = () => open({ ...studio.scenes[0], id: `scene-${crypto.randomUUID()}`, revision: 0,
    name: '新场景', sources: [], items: [] }, 'new');
  const operation = (value: SceneOperation) => { if (scene) onOperation(scene.id, value); setMenu(null); };
  const referenced = (id: string) => studio.scenes.some((value) => value.id !== id && value.sources.some((source) => source.kind === 'nested' && source.sceneId === id));
  const availableSources = sources.filter((source) => source.kind !== 'nested' || source.sceneId !== editing?.id);
  const filteredSources = availableSources.filter((source) => source.name.toLowerCase().includes(sourceQuery.trim().toLowerCase()));
  const submit = () => {
    if (!editing || !editing.name.trim()) return;
    if (mode === 'delete') { onOperation(editing.id, 'delete'); setEditing(null); return; }
    let next = { ...editing, name: editing.name.trim() };
    if (mode === 'sources' || mode === 'new') {
      const selectedSources = structuredClone(sources.filter((source) => checked.includes(source.id)).slice(0, 64));
      next = { ...next, sources: selectedSources, items: selectedSources.map((source, index) =>
        next.items.find((item) => item.sourceId === source.id) ?? { id: `item-${crypto.randomUUID()}`, sourceId: source.id,
          x: 0, y: 0, width: next.canvas.width, height: next.canvas.height, scaleMode: 'contain',
          crop: { top: 0, bottom: 0, left: 0, right: 0 }, zIndex: index, visible: true, locked: false,
          groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' }) };
      if (mode === 'new') next = arrangeSceneGrid(next);
    }
    if (mode === 'new') onCreate(next); else onUpdate(next);
    setEditing(null);
  };
  return <div className="scene-manager">
    <div className="scene-manager-heading"><strong>Scenes · 场景预设</strong>
      <button type="button" disabled={studio.scenes.length >= 64} onClick={add}>新建场景</button>
      <small>{serverOperations ? '每个场景独立保存来源、位置和画布；保存 Studio 后可投影。' : '设备布局先同步，再复制到服务器预览后可投影。'}</small></div>
    <div className="scene-collection" role="list" aria-label="命名场景">
      {studio.scenes.map((value) => <div key={value.id} role="listitem" className="scene-entry">
        <button className={`scene-chip ${value.id === selected ? 'selected' : ''}`} type="button" aria-pressed={value.id === selected} title={value.name}
          aria-label={`选择场景 ${value.name}`} onClick={() => onSelect(value.id)}
          onContextMenu={(event) => { event.preventDefault(); setMenu(value.id); }}
          onKeyDown={(event) => { if (event.key === 'F2') { event.preventDefault(); open(value, 'rename'); }
            if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) { event.preventDefault(); setMenu(value.id); } }}>
          <span className="scene-thumb" style={{ backgroundColor: value.canvas.backgroundColor }}>
            {value.items.filter((item) => item.visible).slice(0, 16).map((item) => <i key={item.id} style={{
              left: `${item.x / value.canvas.width * 100}%`, top: `${item.y / value.canvas.height * 100}%`,
              width: `${item.width / value.canvas.width * 100}%`, height: `${item.height / value.canvas.height * 100}%` }} />)}
          </span><strong>{value.name}</strong>
          <small>{value.sources.length} 个来源 · {value.canvas.width}×{value.canvas.height}</small>
          <span className="scene-badges">{serverOperations && value.id === studio.programSceneId && <span className="scene-badge program">PGM</span>}{value.id === studio.previewSceneId && <span className="scene-badge preview">PVW</span>}{serverOperations && !savedSceneIds.includes(value.id) && <span className="scene-badge unsaved">待保存</span>}</span>
        </button>
        <button type="button" className="scene-menu-button" aria-label={`${value.name} 场景选项`} aria-expanded={menu === value.id} onClick={() => setMenu(value.id)}>⋯</button>
      </div>)}
    </div>
    {scene && <Modal className="scene-options-modal" label={`${scene.name} 场景选项`} onClose={() => setMenu(null)}>
      <header><div><span className="eyebrow">Scene options</span><h2>{scene.name}</h2></div><button type="button" onClick={() => setMenu(null)}>关闭</button></header>
      <div className="scene-actions" role="menu" aria-label="场景操作" onKeyDown={(event) => {
        if (!(event.target instanceof HTMLButtonElement) || event.target.getAttribute('role') !== 'menuitem' || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
        const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('button[role="menuitem"]:not(:disabled)')];
        const index = buttons.indexOf(event.target);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
        event.preventDefault(); buttons[next]?.focus();
      }}>
        <div className="scene-action-group" role="group" aria-label="场景管理"><h3>场景管理</h3>
        <button role="menuitem" onClick={add} disabled={studio.scenes.length >= 64}>新建场景</button>
        <button role="menuitem" onClick={() => operation('duplicate')} disabled={studio.scenes.length >= 64}>复制场景</button>
        <button role="menuitem" onClick={() => open(scene, 'rename')}>重命名</button>
        <button role="menuitem" onClick={() => open(scene, 'sources')}>选择场景来源</button>
        <button role="menuitem" onClick={() => open(scene, 'canvas')}>画布属性</button>
        </div><div className="scene-action-group" role="group" aria-label="布局与顺序"><h3>布局与顺序</h3>
        <button role="menuitem" onClick={() => operation('grid')}>按网格排列来源</button>
        <button role="menuitem" onClick={() => operation('lock')}>锁定全部位置</button>
        <button role="menuitem" onClick={() => operation('unlock')}>解锁全部位置</button>
        {(['up', 'down', 'top', 'bottom'] as const).map((action, index) => <button role="menuitem" key={action}
          disabled={studio.scenes.findIndex((value) => value.id === scene.id) === (index % 2 ? studio.scenes.length - 1 : 0)}
          onClick={() => operation(action)}>{['向前移动', '向后移动', '移到首位', '移到末位'][index]}</button>)}
        </div><div className="scene-action-group" role="group" aria-label="场景投影"><h3>场景投影</h3>
        <button role="menuitem" disabled={!savedSceneIds.includes(scene.id)} onClick={() => operation('projector')}>打开场景投影 · 新窗口</button>
        {window.webobsDesktop && <><label>投影显示器<select value={displayId} onChange={event => setDisplayId(event.target.value)}><option value="">独立窗口</option>{displays.map(display => <option key={display.id} value={display.id}>{display.label}{display.primary ? '（主显示器）' : ''}</option>)}</select></label>
          <label><input type="checkbox" checked={fullscreen} onChange={event => setFullscreen(event.target.checked)} />全屏投影（Esc 退出全屏）</label>
          <button role="menuitem" disabled={!savedSceneIds.includes(scene.id)} onClick={() => { void window.webobsDesktop!.projector({ mode: 'direct', sceneId: scene.id, displayId: displayId ? Number(displayId) : undefined, fullscreen }).then(() => setMenu(null)).catch((reason: unknown) => setProjectorError(reason instanceof Error ? reason.message : '无法打开投影')); }}>投影到所选显示器</button>
          {projectorError && <p role="alert">{projectorError}</p>}</>}
        <p className="scene-operation-hint">{!serverOperations ? '设备布局尚未进入服务器，请先复制到服务器预览，再打开投影。' : !savedSceneIds.includes(scene.id) ? '此场景有未保存修改，请保存 Studio 后再打开投影。' : '不同场景可同时投影；同一场景重复打开会复用窗口。'}</p>
        </div><div className="scene-action-group scene-danger-group" role="group" aria-label="删除场景"><h3>删除</h3>
        <button role="menuitem" className="danger-button" disabled={studio.scenes.length <= 1 || (serverOperations && scene.id === studio.programSceneId) || referenced(scene.id)} onClick={() => open(scene, 'delete')}>删除场景</button>
        <p className="scene-operation-hint">{studio.scenes.length <= 1 ? '至少需要保留一个场景。' : serverOperations && scene.id === studio.programSceneId ? '此场景正在 Program 输出，请切换输出场景后再删除。' : referenced(scene.id) ? '此场景被其他场景嵌套引用，请先解除引用。' : '删除前会再次确认，设备目录中的来源会保留。'}</p>
        </div>
      </div>
    </Modal>}
    {editing && <Modal label={{ rename: '重命名场景', canvas: '画布属性', sources: '选择场景来源', new: '新建场景', delete: '删除场景' }[mode]} onClose={() => setEditing(null)}>
      <form onSubmit={(event) => { event.preventDefault(); submit(); }} className="scene-edit-form">
        <h2>{{ rename: '重命名场景', canvas: '画布属性', sources: '选择场景来源', new: '新建场景', delete: '删除场景' }[mode]}</h2>
        {mode === 'delete' ? <p>删除“{editing.name}”及其布局？设备目录中的摄像机不会被删除，保存 Studio 后生效。</p>
          : <label>场景名称<input autoFocus required maxLength={128} value={editing.name} onChange={(event) => setEditing({ ...editing, name: event.target.value })} /></label>}
        {(mode === 'canvas' || mode === 'new') && <>
          {(['width', 'height'] as const).map((key) => <label key={key}>{key === 'width' ? '画布宽度' : '画布高度'}<input type="number" required min="16" max="8192" step="2" value={editing.canvas[key]}
            onChange={(event) => setEditing({ ...editing, canvas: { ...editing.canvas, [key]: event.currentTarget.valueAsNumber } })} /></label>)}
          <label>背景颜色<input type="color" value={editing.canvas.backgroundColor} onChange={(event) => setEditing({ ...editing, canvas: { ...editing.canvas, backgroundColor: event.target.value } })} /></label>
          <small>修改画布尺寸保留来源位置，可随后执行“按网格排列来源”。</small>
        </>}
        {(mode === 'sources' || mode === 'new') && <fieldset className="scene-source-picker"><legend>选择来源 · 已选 {checked.length}/64</legend>
          <div className="scene-source-search"><input aria-label="搜索场景来源" type="search" placeholder="搜索来源名称…" maxLength={128} value={sourceQuery} onChange={(event) => setSourceQuery(event.target.value)} />
            <button type="button" disabled={!checked.length} onClick={() => setChecked([])}>清空选择</button></div>
          {filteredSources.map((source) => <label key={source.id}>
            <input type="checkbox" checked={checked.includes(source.id)} disabled={!checked.includes(source.id) && checked.length >= 64}
              onChange={(event) => setChecked(event.target.checked ? [...checked, source.id] : checked.filter((id) => id !== source.id))} />{source.name}</label>)}
          {!availableSources.length && <p>先在“设备与来源”添加设备，再在 Studio 添加来源；也可创建空场景。</p>}
          {!!availableSources.length && !filteredSources.length && <p role="status">没有匹配的来源；已选来源仍会保留。</p>}
        </fieldset>}
        {mode !== 'delete' && <small className="scene-operation-hint">应用后仍需点击 Studio 的“保存并应用”，才会更新已保存场景和投影。</small>}
        <footer><button type="button" onClick={() => setEditing(null)}>取消</button><button type="submit" className={mode === 'delete' ? 'danger-button' : 'primary-button'}>{mode === 'delete' ? '确认删除' : '应用到草稿'}</button></footer>
      </form>
    </Modal>}
  </div>;
}
