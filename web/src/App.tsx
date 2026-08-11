import {
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { connectSceneEvents, ControlApiError, fetchScene, replaceScene } from './api';
import ProgramPreview from './ProgramPreview';
import type { ScaleMode, SceneDocument, SceneItem, SceneSource, Transport } from './types';

type ConnectionState = 'connecting' | 'online' | 'offline';
type WorkspaceMode = 'program' | 'layout';
type PointerMode = 'move' | 'resize';

interface PointerOperation {
  mode: PointerMode;
  itemId: string;
  startX: number;
  startY: number;
  stageWidth: number;
  stageHeight: number;
  canvasWidth: number;
  canvasHeight: number;
  initial: SceneItem;
}

const cloneScene = (scene: SceneDocument): SceneDocument => JSON.parse(JSON.stringify(scene)) as SceneDocument;
const clamp = (value: number, minimum: number, maximum: number) =>
  Math.min(Math.max(value, minimum), maximum);

function normalizeZIndexes(items: SceneItem[]): SceneItem[] {
  return [...items]
    .sort((left, right) => left.zIndex - right.zIndex)
    .map((item, zIndex) => ({ ...item, zIndex }));
}

function sourceHue(id: string): number {
  let hash = 0;
  for (const character of id) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return 185 + (hash % 105);
}

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step?: number;
}) {
  return (
    <label className="field compact-field">
      <span>{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (Number.isFinite(next)) onChange(clamp(next, min, max));
        }}
      />
    </label>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="toggle-row">
      <span>{label}</span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span className="toggle" aria-hidden="true" />
    </label>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="empty-state">
      <div className="empty-mark" aria-hidden="true">+</div>
      <h2>添加第一路摄像头</h2>
      <p>从 RTSP 来源开始构建监控墙。凭据只会写入受保护的本地场景文件。</p>
      <button className="primary-button" type="button" onClick={onAdd}>添加来源</button>
    </div>
  );
}

export default function App() {
  const [baseline, setBaseline] = useState<SceneDocument | null>(null);
  const [draft, setDraft] = useState<SceneDocument | null>(null);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [connection, setConnection] = useState<ConnectionState>('connecting');
  const [loadingError, setLoadingError] = useState('');
  const [notice, setNotice] = useState('');
  const [conflict, setConflict] = useState('');
  const [saving, setSaving] = useState(false);
  const [adding, setAdding] = useState(false);
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>('program');
  const [newName, setNewName] = useState('新摄像头');
  const [newUrl, setNewUrl] = useState('');
  const [newTransport, setNewTransport] = useState<Transport>('tcp');
  const stageRef = useRef<HTMLDivElement>(null);
  const pointerOperation = useRef<PointerOperation | null>(null);
  const baselineRef = useRef<SceneDocument | null>(null);
  const dirtyRef = useRef(false);
  const savingRef = useRef(false);

  const dirty = useMemo(
    () => Boolean(baseline && draft && JSON.stringify(baseline) !== JSON.stringify(draft)),
    [baseline, draft],
  );

  useEffect(() => {
    baselineRef.current = baseline;
    dirtyRef.current = dirty;
  }, [baseline, dirty]);

  const applyRemoteScene = useCallback((scene: SceneDocument) => {
    baselineRef.current = scene;
    dirtyRef.current = false;
    setBaseline(scene);
    setDraft(cloneScene(scene));
    setConflict('');
    setSelectedSourceId((current) =>
      current && scene.sources.some((source) => source.id === current)
        ? current
        : (scene.sources[0]?.id ?? null),
    );
  }, []);

  const reload = useCallback(async () => {
    setLoadingError('');
    try {
      applyRemoteScene(await fetchScene());
    } catch (error) {
      setLoadingError(error instanceof Error ? error.message : '无法读取场景');
    }
  }, [applyRemoteScene]);

  useEffect(() => {
    const controller = new AbortController();
    fetchScene(controller.signal)
      .then(applyRemoteScene)
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setLoadingError(error instanceof Error ? error.message : '无法读取场景');
      });
    return () => controller.abort();
  }, [applyRemoteScene]);

  useEffect(
    () => connectSceneEvents(
      (event) => {
        const current = baselineRef.current;
        if (!current || !dirtyRef.current || savingRef.current) {
          applyRemoteScene(event.scene);
        } else if (event.scene.revision > current.revision) {
          setConflict(`服务器场景已更新到 r${event.scene.revision}，请重新载入后再编辑。`);
        }
      },
      (connected) => setConnection(connected ? 'online' : 'offline'),
    ),
    [applyRemoteScene],
  );

  const updateDraft = useCallback((update: (scene: SceneDocument) => SceneDocument) => {
    dirtyRef.current = true;
    setDraft((current) => (current ? update(current) : current));
    setNotice('');
  }, []);

  const updateSource = useCallback((sourceId: string, update: Partial<SceneSource>) => {
    updateDraft((scene) => ({
      ...scene,
      sources: scene.sources.map((source) => (source.id === sourceId ? { ...source, ...update } : source)),
    }));
  }, [updateDraft]);

  const updateItem = useCallback((itemId: string, update: Partial<SceneItem>) => {
    updateDraft((scene) => ({
      ...scene,
      items: scene.items.map((item) => (item.id === itemId ? { ...item, ...update } : item)),
    }));
  }, [updateDraft]);

  useEffect(() => {
    const move = (event: PointerEvent) => {
      const operation = pointerOperation.current;
      if (!operation) return;
      const deltaX = ((event.clientX - operation.startX) / operation.stageWidth) * operation.canvasWidth;
      const deltaY = ((event.clientY - operation.startY) / operation.stageHeight) * operation.canvasHeight;
      const initial = operation.initial;
      if (operation.mode === 'move') {
        updateItem(initial.id, {
          x: Math.round(clamp(initial.x + deltaX, 0, Math.max(0, operation.canvasWidth - initial.width))),
          y: Math.round(clamp(initial.y + deltaY, 0, Math.max(0, operation.canvasHeight - initial.height))),
        });
      } else {
        updateItem(initial.id, {
          width: Math.round(clamp(initial.width + deltaX, 64, operation.canvasWidth - initial.x)),
          height: Math.round(clamp(initial.height + deltaY, 64, operation.canvasHeight - initial.y)),
        });
      }
    };
    const stop = () => { pointerOperation.current = null; };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
    };
  }, [updateItem]);

  const beginPointer = (event: ReactPointerEvent, item: SceneItem, mode: PointerMode) => {
    const stage = stageRef.current;
    if (!draft || !stage) return;
    event.preventDefault();
    event.stopPropagation();
    const bounds = stage.getBoundingClientRect();
    pointerOperation.current = {
      mode,
      itemId: item.id,
      startX: event.clientX,
      startY: event.clientY,
      stageWidth: bounds.width,
      stageHeight: bounds.height,
      canvasWidth: draft.canvas.width,
      canvasHeight: draft.canvas.height,
      initial: { ...item, crop: { ...item.crop } },
    };
    setSelectedSourceId(item.sourceId);
  };

  const addSource = () => {
    if (!draft || !newName.trim() || !/^rtsps?:\/\/\S+$/i.test(newUrl) || draft.sources.length >= 64) return;
    const suffix = Date.now().toString(36);
    const sourceId = `camera-${suffix}`;
    const itemId = `item-${suffix}`;
    const column = draft.items.length % 2;
    const row = Math.floor(draft.items.length / 2) % 2;
    const width = Math.max(64, Math.floor(draft.canvas.width / 2));
    const height = Math.max(64, Math.floor(draft.canvas.height / 2));
    const source: SceneSource = {
      id: sourceId,
      kind: 'rtsp',
      name: newName.trim(),
      rtspUrl: newUrl,
      transport: newTransport,
      muted: true,
      volume: 1,
    };
    const item: SceneItem = {
      id: itemId,
      sourceId,
      x: column * width,
      y: row * height,
      width,
      height,
      scaleMode: 'contain',
      crop: { top: 0, right: 0, bottom: 0, left: 0 },
      zIndex: draft.items.length,
      visible: true,
    };
    updateDraft((scene) => ({ ...scene, sources: [...scene.sources, source], items: [...scene.items, item] }));
    setSelectedSourceId(sourceId);
    setNewName('新摄像头');
    setNewUrl('');
    setNewTransport('tcp');
    setAdding(false);
  };

  const removeSource = (source: SceneSource) => {
    if (!draft || !window.confirm(`移除“${source.name}”及其布局项？保存后生效。`)) return;
    updateDraft((scene) => ({
      ...scene,
      sources: scene.sources.filter((candidate) => candidate.id !== source.id),
      items: normalizeZIndexes(scene.items.filter((item) => item.sourceId !== source.id)),
    }));
    setSelectedSourceId(draft.sources.find((candidate) => candidate.id !== source.id)?.id ?? null);
  };

  const moveLayer = (direction: -1 | 1) => {
    if (!draft || !selectedSourceId) return;
    const ordered = [...draft.items].sort((left, right) => left.zIndex - right.zIndex);
    const index = ordered.findIndex((item) => item.sourceId === selectedSourceId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= ordered.length) return;
    [ordered[index], ordered[target]] = [ordered[target], ordered[index]];
    updateDraft((scene) => ({ ...scene, items: normalizeZIndexes(ordered) }));
  };

  const save = async () => {
    if (!draft || !dirty || saving || conflict) return;
    savingRef.current = true;
    setSaving(true);
    setNotice('');
    try {
      const committed = await replaceScene(draft);
      applyRemoteScene(committed);
      setNotice(`场景 r${committed.revision} 已保存并切换到输出。`);
    } catch (error) {
      if (error instanceof ControlApiError && error.status === 412) {
        setConflict(`保存冲突：服务器当前为 r${error.revision ?? '未知'}，请重新载入。`);
      } else {
        setNotice(error instanceof Error ? error.message : '保存失败');
      }
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  const discard = () => {
    if (!baseline) return;
    setDraft(cloneScene(baseline));
    dirtyRef.current = false;
    setConflict('');
    setNotice('已放弃未保存的修改。');
  };

  const reloadAfterConflict = async () => {
    if (dirty && !window.confirm('重新载入会放弃当前未保存修改，继续吗？')) return;
    await reload();
  };

  if (!draft) {
    return (
      <main className="boot-screen">
        <div className="brand-mark">W</div>
        <h1>WebOBS Monitor Wall</h1>
        {loadingError ? (
          <>
            <p>{loadingError}</p>
            <button className="primary-button" type="button" onClick={reload}>重新连接</button>
          </>
        ) : <p>正在连接本地合成器…</p>}
      </main>
    );
  }

  const selectedSource = draft.sources.find((source) => source.id === selectedSourceId) ?? null;
  const selectedItem = draft.items.find((item) => item.sourceId === selectedSourceId) ?? null;
  const orderedSources = [...draft.sources].sort((left, right) => {
    const leftItem = draft.items.find((item) => item.sourceId === left.id);
    const rightItem = draft.items.find((item) => item.sourceId === right.id);
    return (rightItem?.zIndex ?? -1) - (leftItem?.zIndex ?? -1);
  });

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark small">W</div>
          <div>
            <strong>WebOBS</strong>
            <span>MONITOR WALL</span>
          </div>
        </div>
        <div className="scene-title">
          <span className="eyebrow">当前场景</span>
          <input
            aria-label="场景名称"
            value={draft.name}
            maxLength={128}
            onChange={(event) => updateDraft((scene) => ({ ...scene, name: event.target.value }))}
          />
        </div>
        <div className="top-actions">
          <span className={`connection ${connection}`}>
            <i aria-hidden="true" />
            {connection === 'online' ? '实时同步' : connection === 'connecting' ? '正在连接' : '连接中断'}
          </span>
          <span className="revision">r{draft.revision}</span>
          <button className="ghost-button" type="button" disabled={!dirty || saving} onClick={discard}>放弃</button>
          <button className="primary-button save-button" type="button" disabled={!dirty || saving || Boolean(conflict)} onClick={save}>
            {saving ? '正在保存…' : dirty ? '保存并应用' : '已同步'}
          </button>
        </div>
      </header>

      {conflict && (
        <div className="alert conflict-alert" role="alert">
          <span>{conflict}</span>
          <button type="button" onClick={reloadAfterConflict}>重新载入</button>
        </div>
      )}
      {notice && <div className="alert notice-alert" role="status">{notice}</div>}

      <main className="editor-grid">
        <aside className="source-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">输入源</span>
              <h2>摄像头</h2>
            </div>
            <span className="count-badge">{draft.sources.length}/64</span>
          </div>

          <div className="source-list">
            {orderedSources.map((source, index) => {
              const item = draft.items.find((candidate) => candidate.sourceId === source.id);
              const selected = source.id === selectedSourceId;
              return (
                <button
                  className={`source-card ${selected ? 'selected' : ''}`}
                  type="button"
                  key={source.id}
                  onClick={() => setSelectedSourceId(source.id)}
                >
                  <span className="source-index">{String(index + 1).padStart(2, '0')}</span>
                  <span className="source-copy">
                    <strong>{source.name}</strong>
                    <small>{source.transport.toUpperCase()} · {item?.visible === false ? '已隐藏' : '画布中'}</small>
                  </span>
                  <span className={`source-state ${item?.visible === false ? 'hidden' : ''}`} aria-hidden="true" />
                </button>
              );
            })}
          </div>

          {adding ? (
            <div className="add-source-form">
              <label className="field">
                <span>显示名称</span>
                <input value={newName} maxLength={128} onChange={(event) => setNewName(event.target.value)} />
              </label>
              <label className="field">
                <span>RTSP 地址</span>
                <input
                  value={newUrl}
                  type="text"
                  inputMode="url"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="rtsp://camera-host/stream"
                  onChange={(event) => setNewUrl(event.target.value)}
                />
              </label>
              <label className="field">
                <span>传输方式</span>
                <select value={newTransport} onChange={(event) => setNewTransport(event.target.value as Transport)}>
                  <option value="tcp">TCP（推荐）</option>
                  <option value="udp">UDP</option>
                </select>
              </label>
              <p className="security-note">凭据不会由 API 回显。请勿在共享屏幕或浏览器同步中保存真实地址。</p>
              <div className="form-actions">
                <button className="ghost-button" type="button" onClick={() => setAdding(false)}>取消</button>
                <button
                  className="primary-button"
                  type="button"
                  disabled={!newName.trim() || !/^rtsps?:\/\/\S+$/i.test(newUrl)}
                  onClick={addSource}
                >添加到画布</button>
              </div>
            </div>
          ) : (
            <button className="add-source-button" type="button" onClick={() => setAdding(true)} disabled={draft.sources.length >= 64}>
              <span aria-hidden="true">＋</span> 添加 RTSP 来源
            </button>
          )}
        </aside>

        <section className="workspace">
          <div className="workspace-toolbar">
            <div>
              <span className="eyebrow">节目画布</span>
              <strong>{draft.canvas.width} × {draft.canvas.height}</strong>
            </div>
            <div className="workspace-mode" aria-label="工作区显示模式">
              <button className={workspaceMode === 'program' ? 'active' : ''} type="button" onClick={() => setWorkspaceMode('program')}>实时节目</button>
              <button className={workspaceMode === 'layout' ? 'active' : ''} type="button" onClick={() => setWorkspaceMode('layout')}>布局编辑</button>
            </div>
          </div>
          <div className="stage-wrap">
            {workspaceMode === 'program' ? (
              <ProgramPreview aspectRatio={`${draft.canvas.width} / ${draft.canvas.height}`} />
            ) : draft.items.length === 0 ? <EmptyState onAdd={() => setAdding(true)} /> : (
              <div
                className="stage"
                ref={stageRef}
                style={{ aspectRatio: `${draft.canvas.width} / ${draft.canvas.height}`, backgroundColor: draft.canvas.backgroundColor }}
                onPointerDown={() => setSelectedSourceId(null)}
              >
                <div className="stage-grid" aria-hidden="true" />
                {[...draft.items].sort((left, right) => left.zIndex - right.zIndex).map((item) => {
                  const source = draft.sources.find((candidate) => candidate.id === item.sourceId);
                  if (!source) return null;
                  const selected = source.id === selectedSourceId;
                  const tileStyle = {
                    left: `${(item.x / draft.canvas.width) * 100}%`,
                    top: `${(item.y / draft.canvas.height) * 100}%`,
                    width: `${(item.width / draft.canvas.width) * 100}%`,
                    height: `${(item.height / draft.canvas.height) * 100}%`,
                    zIndex: item.zIndex + 1,
                    '--source-hue': sourceHue(source.id),
                  } as CSSProperties;
                  return (
                    <div
                      className={`camera-tile ${selected ? 'selected' : ''} ${item.visible ? '' : 'invisible'}`}
                      style={tileStyle}
                      key={item.id}
                      role="button"
                      tabIndex={0}
                      aria-label={`${source.name}，位置 ${item.x}, ${item.y}，尺寸 ${item.width} × ${item.height}`}
                      onClick={(event) => { event.stopPropagation(); setSelectedSourceId(source.id); }}
                      onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') setSelectedSourceId(source.id); }}
                      onPointerDown={(event) => beginPointer(event, item, 'move')}
                    >
                      <div className="tile-noise" aria-hidden="true" />
                      <span className="tile-tag">RTSP · {source.transport.toUpperCase()}</span>
                      <div className="tile-caption">
                        <strong>{source.name}</strong>
                        <span>{item.width} × {item.height}</span>
                      </div>
                      {!item.visible && <span className="hidden-label">已隐藏</span>}
                      <button
                        className="resize-handle"
                        type="button"
                        aria-label={`调整 ${source.name} 的尺寸`}
                        onPointerDown={(event) => beginPointer(event, item, 'resize')}
                      />
                    </div>
                  );
                })}
              </div>
            )}
          </div>
          <div className="workspace-footer">
            <span>{workspaceMode === 'program' ? 'WHEP 实时播放' : '布局预览'}</span>
            <span>{workspaceMode === 'program' ? '浏览器仅连接同源信令代理，不接触容器内部端点' : '保存后由容器内 libobs 原子应用到合成输出'}</span>
          </div>
        </section>

        <aside className="inspector-panel">
          <div className="panel-heading inspector-heading">
            <div>
              <span className="eyebrow">属性</span>
              <h2>{selectedSource?.name ?? '未选择来源'}</h2>
            </div>
          </div>

          {!selectedSource ? (
            <div className="inspector-empty"><p>选择画布或左侧列表中的摄像头以编辑参数。</p></div>
          ) : (
            <div className="inspector-scroll">
              <section className="property-section">
                <h3>来源</h3>
                <label className="field">
                  <span>名称</span>
                  <input value={selectedSource.name} maxLength={128} onChange={(event) => updateSource(selectedSource.id, { name: event.target.value })} />
                </label>
                <label className="field">
                  <span>RTSP 地址</span>
                  <input
                    value={selectedSource.rtspUrl}
                    autoComplete="off"
                    spellCheck={false}
                    onChange={(event) => updateSource(selectedSource.id, { rtspUrl: event.target.value })}
                  />
                </label>
                <p className="security-note"><code>***:***</code> 表示服务器保留的既有凭据；改变端点时请输入完整新地址。</p>
                <label className="field">
                  <span>传输方式</span>
                  <select value={selectedSource.transport} onChange={(event) => updateSource(selectedSource.id, { transport: event.target.value as Transport })}>
                    <option value="tcp">TCP</option>
                    <option value="udp">UDP</option>
                  </select>
                </label>
                <Toggle label="静音" checked={selectedSource.muted} onChange={(muted) => updateSource(selectedSource.id, { muted })} />
                <label className="range-field">
                  <span>音量 <strong>{Math.round(selectedSource.volume * 100)}%</strong></span>
                  <input type="range" min="0" max="1" step="0.01" value={selectedSource.volume} onChange={(event) => updateSource(selectedSource.id, { volume: Number(event.target.value) })} />
                </label>
              </section>

              {selectedItem && (
                <>
                  <section className="property-section">
                    <h3>布局</h3>
                    <div className="field-grid">
                      <NumberField label="X" value={selectedItem.x} min={-32768} max={32768} onChange={(x) => updateItem(selectedItem.id, { x })} />
                      <NumberField label="Y" value={selectedItem.y} min={-32768} max={32768} onChange={(y) => updateItem(selectedItem.id, { y })} />
                      <NumberField label="宽" value={selectedItem.width} min={1} max={8192} onChange={(width) => updateItem(selectedItem.id, { width })} />
                      <NumberField label="高" value={selectedItem.height} min={1} max={8192} onChange={(height) => updateItem(selectedItem.id, { height })} />
                    </div>
                    <label className="field">
                      <span>缩放模式</span>
                      <select value={selectedItem.scaleMode} onChange={(event) => updateItem(selectedItem.id, { scaleMode: event.target.value as ScaleMode })}>
                        <option value="contain">完整显示（Contain）</option>
                        <option value="cover">填满区域（Cover）</option>
                        <option value="stretch">拉伸（Stretch）</option>
                      </select>
                    </label>
                    <Toggle label="在节目中显示" checked={selectedItem.visible} onChange={(visible) => updateItem(selectedItem.id, { visible })} />
                  </section>

                  <section className="property-section">
                    <h3>裁切</h3>
                    <div className="field-grid">
                      {(['top', 'right', 'bottom', 'left'] as const).map((edge) => (
                        <NumberField
                          key={edge}
                          label={{ top: '上', right: '右', bottom: '下', left: '左' }[edge]}
                          value={selectedItem.crop[edge]}
                          min={0}
                          max={8192}
                          onChange={(value) => updateItem(selectedItem.id, { crop: { ...selectedItem.crop, [edge]: value } })}
                        />
                      ))}
                    </div>
                  </section>

                  <section className="property-section">
                    <h3>层级</h3>
                    <div className="layer-actions">
                      <button className="ghost-button" type="button" disabled={selectedItem.zIndex === 0} onClick={() => moveLayer(-1)}>下移一层</button>
                      <span>{selectedItem.zIndex + 1} / {draft.items.length}</span>
                      <button className="ghost-button" type="button" disabled={selectedItem.zIndex === draft.items.length - 1} onClick={() => moveLayer(1)}>上移一层</button>
                    </div>
                  </section>
                </>
              )}

              <section className="danger-section">
                <button type="button" onClick={() => removeSource(selectedSource)}>移除来源</button>
              </section>
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}
