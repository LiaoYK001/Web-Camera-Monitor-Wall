import {
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { connectSceneEvents, ControlApiError, fetchCameras, fetchStudio, fetchStudioCapabilities, replaceStudio, studioAction } from './api';
import DirectPreview from './DirectPreview';
import CameraRegistry from './CameraRegistry';
import NvrTimeline from './NvrTimeline';
import ProgramPreview from './ProgramPreview';
import SystemStatus from './SystemStatus';
import EventsPanel from './EventsPanel';
import ClientsPanel from './ClientsPanel';
import type { AudioMonitoring, CameraRecord, FilterKind, PlaybackMode, ScaleMode, SceneDocument, SceneFilter, SceneItem, SceneSource, StudioCapabilities, StudioDocument, Transport } from './types';

type ConnectionState = 'connecting' | 'online' | 'offline';
type WorkspaceMode = 'program' | 'layout';
type PointerMode = 'move' | 'resize';
type AddSourceKind = 'camera' | 'rtsp' | 'browser' | 'image' | 'media' | 'text' | 'color' | 'nested';

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
  initialItems: SceneItem[];
}

const cloneScene = (scene: SceneDocument): SceneDocument => JSON.parse(JSON.stringify(scene)) as SceneDocument;
const clamp = (value: number, minimum: number, maximum: number) =>
  Math.min(Math.max(value, minimum), maximum);
const initialPlaybackMode = (): PlaybackMode => window.location.hash === '#composite' ? 'composite' : 'direct';

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
      <h2>尚未添加摄像机</h2>
      <p>优先从 Camera Registry 选择设备；场景只保存稳定 ID，不保存摄像机凭据。</p>
      <button className="primary-button" type="button" onClick={onAdd}>添加来源</button>
    </div>
  );
}

export default function App() {
  const [productArea, setProductArea] = useState<'studio' | 'archive' | 'devices' | 'clients' | 'events' | 'system'>(window.location.hash === '#archive' ? 'archive' : window.location.hash === '#devices' ? 'devices' : window.location.hash === '#clients' ? 'clients' : window.location.hash === '#events' ? 'events' : window.location.hash === '#system' ? 'system' : 'studio');
  const [baseline, setBaseline] = useState<SceneDocument | null>(null);
  const [draft, setDraft] = useState<SceneDocument | null>(null);
  const [studioBaseline, setStudioBaseline] = useState<StudioDocument | null>(null);
  const [studioDraft, setStudioDraft] = useState<StudioDocument | null>(null);
  const [studioCapabilities, setStudioCapabilities] = useState<StudioCapabilities | null>(null);
  const [programScene, setProgramScene] = useState<SceneDocument | null>(null);
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(null);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([]);
  const [connection, setConnection] = useState<ConnectionState>('connecting');
  const [loadingError, setLoadingError] = useState('');
  const [notice, setNotice] = useState('');
  const [conflict, setConflict] = useState('');
  const [saving, setSaving] = useState(false);
  const [adding, setAdding] = useState(false);
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>('program');
  const [playbackMode, setPlaybackMode] = useState<PlaybackMode>(initialPlaybackMode);
  const [canvasZoom, setCanvasZoom] = useState(1);
  const [newKind, setNewKind] = useState<AddSourceKind>('camera');
  const [newName, setNewName] = useState('新摄像头');
  const [newUrl, setNewUrl] = useState('');
  const [newTransport, setNewTransport] = useState<Transport>('tcp');
  const [registryCameras, setRegistryCameras] = useState<CameraRecord[]>([]);
  const stageRef = useRef<HTMLDivElement>(null);
  const monitorRef = useRef<HTMLDivElement>(null);
  const wakeLockRef = useRef<{ release: () => Promise<void>; addEventListener: (type: 'release', listener: () => void) => void } | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [wakeLockState, setWakeLockState] = useState<'off' | 'active' | 'unsupported' | 'failed'>('off');
  const importRef = useRef<HTMLInputElement>(null);
  const pointerOperation = useRef<PointerOperation | null>(null);
  const baselineRef = useRef<SceneDocument | null>(null);
  const dirtyRef = useRef(false);
  const savingRef = useRef(false);

  const dirty = useMemo(
    () => Boolean(studioBaseline && studioDraft && JSON.stringify(studioBaseline) !== JSON.stringify(studioDraft)),
    [studioBaseline, studioDraft],
  );

  useEffect(() => {
    if (!adding) return;
    const controller = new AbortController();
    fetchCameras(controller.signal)
      .then((result) => setRegistryCameras(result.cameras))
      .catch(() => setRegistryCameras([]));
    return () => controller.abort();
  }, [adding]);

  useEffect(() => {
    baselineRef.current = baseline;
    dirtyRef.current = dirty;
  }, [baseline, dirty]);

  const applyRemoteStudio = useCallback((studio: StudioDocument) => {
    const scene = studio.scenes.find((candidate) => candidate.id === studio.previewSceneId) ?? studio.scenes[0];
    if (!scene) return;
    baselineRef.current = scene;
    dirtyRef.current = false;
    setBaseline(scene);
    setDraft(cloneScene(scene));
    setStudioBaseline(studio);
    setStudioDraft(JSON.parse(JSON.stringify(studio)) as StudioDocument);
    setSelectedSceneId(scene.id);
    setConflict('');
    setSelectedSourceId((current) =>
      current && scene.sources.some((source) => source.id === current)
        ? current
        : (scene.sources[0]?.id ?? null),
    );
    setSelectedSourceIds(scene.sources[0] ? [scene.sources[0].id] : []);
  }, []);

  const requestWakeLock = useCallback(async () => {
    if (!document.fullscreenElement || document.visibilityState !== 'visible') return;
    if (wakeLockRef.current) return;
    const wakeLock = (navigator as Navigator & { wakeLock?: { request: (type: 'screen') => Promise<{ release: () => Promise<void>; addEventListener: (type: 'release', listener: () => void) => void }> } }).wakeLock;
    if (!wakeLock) { setWakeLockState('unsupported'); return; }
    try {
      const sentinel = await wakeLock.request('screen');
      wakeLockRef.current = sentinel;
      setWakeLockState('active');
      sentinel.addEventListener('release', () => {
        if (wakeLockRef.current === sentinel) {
          wakeLockRef.current = null;
          setWakeLockState('off');
        }
      });
    } catch {
      setWakeLockState('failed');
    }
  }, []);

  useEffect(() => {
    const fullscreenChanged = () => {
      const active = document.fullscreenElement === monitorRef.current;
      setFullscreen(active);
      if (active) void requestWakeLock();
      else {
        void wakeLockRef.current?.release();
        wakeLockRef.current = null;
        setWakeLockState('off');
      }
    };
    const visibilityChanged = () => {
      if (document.visibilityState === 'visible' && document.fullscreenElement === monitorRef.current)
        void requestWakeLock();
    };
    document.addEventListener('fullscreenchange', fullscreenChanged);
    document.addEventListener('visibilitychange', visibilityChanged);
    return () => {
      document.removeEventListener('fullscreenchange', fullscreenChanged);
      document.removeEventListener('visibilitychange', visibilityChanged);
      void wakeLockRef.current?.release();
    };
  }, [requestWakeLock]);

  const toggleFullscreen = async () => {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await monitorRef.current?.requestFullscreen();
  };

  const reload = useCallback(async () => {
    setLoadingError('');
    try {
      applyRemoteStudio(await fetchStudio());
    } catch (error) {
      setLoadingError(error instanceof Error ? error.message : '无法读取场景');
    }
  }, [applyRemoteStudio]);

  useEffect(() => {
    if (!studioBaseline) return undefined;
    const controller = new AbortController();
    fetchStudioCapabilities(controller.signal)
      .then(setStudioCapabilities)
      .catch(() => { if (!controller.signal.aborted) setStudioCapabilities(null); });
    return () => controller.abort();
  }, [studioBaseline]);

  useEffect(() => {
    const controller = new AbortController();
    fetchStudio(controller.signal)
      .then(applyRemoteStudio)
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setLoadingError(error instanceof Error ? error.message : '无法读取场景');
      });
    return () => controller.abort();
  }, [applyRemoteStudio]);

  useEffect(
    () => connectSceneEvents(
      (event) => {
        setProgramScene(event.scene);
      },
      (connected) => setConnection(connected ? 'online' : 'offline'),
    ),
    [],
  );

  useEffect(() => {
    const changed = () => {
      setPlaybackMode(initialPlaybackMode());
      setProductArea(window.location.hash === '#archive' ? 'archive' : window.location.hash === '#devices' ? 'devices' : window.location.hash === '#events' ? 'events' : window.location.hash === '#system' ? 'system' : 'studio');
    };
    window.addEventListener('hashchange', changed);
    return () => window.removeEventListener('hashchange', changed);
  }, []);

  const selectPlaybackMode = (mode: PlaybackMode) => {
    setPlaybackMode(mode);
    window.history.replaceState(null, '', mode === 'composite' ? '#composite' : window.location.pathname);
  };

  const updateDraft = useCallback((update: (scene: SceneDocument) => SceneDocument) => {
    dirtyRef.current = true;
    setDraft((current) => {
      if (!current) return current;
      const next = update(current);
      setStudioDraft((studio) => studio ? {
        ...studio,
        scenes: studio.scenes.map((scene) => scene.id === current.id ? next : scene),
      } : studio);
      return next;
    });
    setNotice('');
  }, []);

  const updateSource = useCallback((sourceId: string, update: Partial<SceneSource>) => {
    updateDraft((scene) => ({
      ...scene,
      sources: scene.sources.map((source) => (
        source.id === sourceId ? { ...source, ...update } as SceneSource : source
      )),
    }));
  }, [updateDraft]);

  const updateItem = useCallback((itemId: string, update: Partial<SceneItem>) => {
    updateDraft((scene) => ({
      ...scene,
      items: scene.items.map((item) => (item.id === itemId ? { ...item, ...update } : item)),
    }));
  }, [updateDraft]);

  const updateFilter = (source: SceneSource, filterId: string, update: Partial<SceneFilter>) => {
    updateSource(source.id, { filters: source.filters.map((filter) => filter.id === filterId ? { ...filter, ...update } : filter) });
  };

  const addFilter = (source: SceneSource) => {
    if (source.filters.length >= 16) return;
    updateSource(source.id, { filters: [...source.filters, {
      id: `filter-${Date.now().toString(36)}`, kind: 'opacity', enabled: true, amount: 1, value: '',
    }] });
  };

  useEffect(() => {
    const snapped = (value: number, size: number, maximum: number) => {
      const candidates = [0, Math.round((maximum - size) / 2), maximum - size, Math.round(value / 10) * 10];
      const nearest = candidates.reduce((best, candidate) => Math.abs(candidate - value) < Math.abs(best - value) ? candidate : best, candidates[0]);
      return Math.abs(nearest - value) <= 6 ? nearest : Math.round(value);
    };
    const move = (event: PointerEvent) => {
      const operation = pointerOperation.current;
      if (!operation) return;
      const deltaX = ((event.clientX - operation.startX) / operation.stageWidth) * operation.canvasWidth;
      const deltaY = ((event.clientY - operation.startY) / operation.stageHeight) * operation.canvasHeight;
      const initial = operation.initial;
      if (operation.mode === 'move') {
        const updates = new Map(operation.initialItems.filter((item) => !item.locked).map((item) => [item.id, {
          x: snapped(clamp(item.x + deltaX, 0, Math.max(0, operation.canvasWidth - item.width)), item.width, operation.canvasWidth),
          y: snapped(clamp(item.y + deltaY, 0, Math.max(0, operation.canvasHeight - item.height)), item.height, operation.canvasHeight),
        }]));
        updateDraft((scene) => ({ ...scene, items: scene.items.map((item) => updates.has(item.id) ? { ...item, ...updates.get(item.id)! } : item) }));
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
  }, [updateDraft, updateItem]);

  const beginPointer = (event: ReactPointerEvent, item: SceneItem, mode: PointerMode) => {
    const stage = stageRef.current;
    if (!draft || !stage || item.locked) return;
    event.preventDefault();
    event.stopPropagation();
    const bounds = stage.getBoundingClientRect();
    const groupIds = item.groupId
      ? draft.items.filter((candidate) => candidate.groupId === item.groupId).map((candidate) => candidate.sourceId)
      : [item.sourceId];
    const activeIds = selectedSourceIds.includes(item.sourceId) ? selectedSourceIds : groupIds;
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
      initialItems: draft.items.filter((candidate) => activeIds.includes(candidate.sourceId))
        .map((candidate) => ({ ...candidate, crop: { ...candidate.crop } })),
    };
    setSelectedSourceId(item.sourceId);
    if (!selectedSourceIds.includes(item.sourceId)) setSelectedSourceIds(groupIds);
  };

  const selectSource = (sourceId: string, additive = false) => {
    setSelectedSourceId(sourceId);
    const item = draft?.items.find((candidate) => candidate.sourceId === sourceId);
    const targets = item?.groupId
      ? draft!.items.filter((candidate) => candidate.groupId === item.groupId).map((candidate) => candidate.sourceId)
      : [sourceId];
    setSelectedSourceIds((current) => additive
      ? targets.every((id) => current.includes(id))
        ? current.filter((id) => !targets.includes(id))
        : [...new Set([...current, ...targets])]
      : targets);
  };

  const addSource = () => {
    const validValue = newKind === 'camera' ? /^[a-zA-Z0-9._-]{1,64}\/[a-zA-Z0-9._-]{1,64}$/.test(newUrl)
      : newKind === 'rtsp' ? /^rtsps?:\/\/\S+$/i.test(newUrl)
      : newKind === 'browser' ? /^https?:\/\/\S+$/i.test(newUrl)
        : newKind === 'image' || newKind === 'media' ? /^\/(assets|recordings)\/[^.\/][^\r\n]*$/i.test(newUrl)
          : newKind === 'color' ? /^#[0-9a-f]{6}$/i.test(newUrl)
            : newKind === 'nested' ? Boolean(studioDraft?.scenes.some((scene) => scene.id === newUrl && scene.id !== draft?.id))
              : newUrl.trim().length > 0;
    const browserCount = draft?.sources.filter((source) => source.kind === 'browser').length ?? 0;
    if (!draft || !newName.trim() || !validValue || draft.sources.length >= 64 ||
        (newKind === 'browser' && browserCount >= 8)) return;
    const suffix = Date.now().toString(36);
    const sourceId = `${newKind}-${suffix}`;
    const itemId = `item-${suffix}`;
    const column = draft.items.length % 2;
    const row = Math.floor(draft.items.length / 2) % 2;
    const width = Math.max(64, Math.floor(draft.canvas.width / 2));
    const height = Math.max(64, Math.floor(draft.canvas.height / 2));
    const base = {
      id: sourceId, name: newName.trim(), muted: true, volume: 1, syncOffsetMs: 0,
      monitoring: 'off' as AudioMonitoring, audioTrack: 1, filters: [],
    };
    const source: SceneSource = newKind === 'camera' ? {
      ...base,
      kind: 'camera',
      cameraId: newUrl.split('/', 2)[0],
      profileId: newUrl.split('/', 2)[1],
      hardwareDecode: 'auto',
    } : newKind === 'rtsp' ? {
      ...base,
      id: sourceId,
      kind: 'rtsp',
      rtspUrl: newUrl,
      transport: newTransport,
    } : newKind === 'browser' ? {
      ...base,
      kind: 'browser',
      url: newUrl,
      width: 1280,
      height: 720,
      fps: 30,
      customCss: '',
      shutdownWhenHidden: true,
      restartWhenActive: true,
    } : newKind === 'image' ? { ...base, kind: 'image', filePath: newUrl }
      : newKind === 'media' ? { ...base, kind: 'media', filePath: newUrl, loop: true }
        : newKind === 'text' ? { ...base, kind: 'text', text: newUrl.trim(), color: '#ffffff' }
          : newKind === 'color' ? { ...base, kind: 'color', color: newUrl.toLowerCase() }
            : { ...base, kind: 'nested', sceneId: newUrl };
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
      locked: false,
      groupId: '',
      rotation: 0,
      opacity: 1,
      blendMode: 'normal',
    };
    updateDraft((scene) => ({ ...scene, sources: [...scene.sources, source], items: [...scene.items, item] }));
    setSelectedSourceId(sourceId);
    setNewName(newKind === 'camera' || newKind === 'rtsp' ? '新摄像头' : '新来源');
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
    const fallback = draft.sources.find((candidate) => candidate.id !== source.id)?.id ?? null;
    setSelectedSourceId(fallback);
    setSelectedSourceIds(fallback ? [fallback] : []);
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
    if (!studioDraft || !dirty || saving || conflict) return;
    savingRef.current = true;
    setSaving(true);
    setNotice('');
    try {
      const committed = await replaceStudio(studioDraft);
      applyRemoteStudio(committed);
      setNotice(`Studio s${committed.revision} 已保存；Preview 保持与 Program 隔离。`);
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
    if (!studioBaseline) return;
    applyRemoteStudio(studioBaseline);
    setNotice('已放弃整个 Studio 集合中的未保存修改。');
  };

  const selectScene = (sceneId: string) => {
    if (!studioDraft) return;
    const scene = studioDraft.scenes.find((candidate) => candidate.id === sceneId);
    if (!scene) return;
    const saved = studioBaseline?.scenes.find((candidate) => candidate.id === sceneId) ?? scene;
    setSelectedSceneId(sceneId);
    setBaseline(saved);
    setDraft(cloneScene(scene));
    setSelectedSourceId(scene.sources[0]?.id ?? null);
    setSelectedSourceIds(scene.sources[0] ? [scene.sources[0].id] : []);
    if (studioDraft.previewSceneId !== sceneId) {
      dirtyRef.current = true;
      setStudioDraft({ ...studioDraft, previewSceneId: sceneId });
      setNotice('Preview 已切换；保存 Studio 后可执行 Take。');
    }
  };

  const duplicateScene = () => {
    if (!studioDraft || !draft || studioDraft.scenes.length >= 64) return;
    const suffix = Date.now().toString(36);
    const copy = cloneScene(draft);
    copy.id = `scene-${suffix}`;
    copy.name = `${draft.name} 副本`;
    copy.revision = 0;
    const next = { ...studioDraft, previewSceneId: copy.id, scenes: [...studioDraft.scenes, copy] };
    dirtyRef.current = true;
    setStudioDraft(next);
    setDraft(copy);
    setBaseline(copy);
    setSelectedSceneId(copy.id);
    setSelectedSourceId(copy.sources[0]?.id ?? null);
    setSelectedSourceIds(copy.sources[0] ? [copy.sources[0].id] : []);
  };

  const moveScene = (direction: -1 | 1) => {
    if (!studioDraft || !selectedSceneId) return;
    const scenes = [...studioDraft.scenes];
    const index = scenes.findIndex((scene) => scene.id === selectedSceneId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= scenes.length) return;
    [scenes[index], scenes[target]] = [scenes[target], scenes[index]];
    dirtyRef.current = true;
    setStudioDraft({ ...studioDraft, scenes });
  };

  const removeScene = () => {
    if (!studioDraft || !selectedSceneId || studioDraft.scenes.length <= 1 ||
        studioDraft.programSceneId === selectedSceneId) return;
    const scenes = studioDraft.scenes.filter((scene) => scene.id !== selectedSceneId);
    const nextScene = scenes[0];
    dirtyRef.current = true;
    setStudioDraft({ ...studioDraft, previewSceneId: nextScene.id, scenes });
    setSelectedSceneId(nextScene.id);
    setDraft(cloneScene(nextScene));
    setBaseline(studioBaseline?.scenes.find((scene) => scene.id === nextScene.id) ?? nextScene);
    setSelectedSourceId(nextScene.sources[0]?.id ?? null);
    setSelectedSourceIds(nextScene.sources[0] ? [nextScene.sources[0].id] : []);
  };

  const addTemplate = (template: 'grid' | 'focus') => {
    if (!studioDraft || !draft || studioDraft.scenes.length >= 64) return;
    const suffix = Date.now().toString(36);
    const scene = cloneScene(draft);
    scene.id = `scene-${template}-${suffix}`;
    scene.name = template === 'grid' ? '四宫格模板' : '主画面模板';
    scene.revision = 0;
    scene.items = normalizeZIndexes(scene.items.map((item, index) => template === 'grid' ? {
      ...item, x: index % 2 * Math.floor(scene.canvas.width / 2), y: Math.floor(index / 2) % 2 * Math.floor(scene.canvas.height / 2),
      width: Math.floor(scene.canvas.width / 2), height: Math.floor(scene.canvas.height / 2),
    } : index === 0 ? { ...item, x: 0, y: 0, width: scene.canvas.width, height: scene.canvas.height }
      : { ...item, x: scene.canvas.width - Math.floor(scene.canvas.width / 4) - 20,
        y: 20 + (index - 1) * (Math.floor(scene.canvas.height / 4) + 12),
        width: Math.floor(scene.canvas.width / 4), height: Math.floor(scene.canvas.height / 4) }));
    dirtyRef.current = true;
    setStudioDraft({ ...studioDraft, previewSceneId: scene.id, scenes: [...studioDraft.scenes, scene] });
    setSelectedSceneId(scene.id);
    setDraft(scene);
    setBaseline(scene);
  };

  const exportStudio = () => {
    if (!studioDraft) return;
    const blob = new Blob([JSON.stringify(studioDraft, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `webobs-studio-s${studioDraft.revision}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const importStudio = async (file?: File) => {
    if (!file || !studioDraft) return;
    try {
      const imported = JSON.parse(await file.text()) as StudioDocument;
      if (imported.schemaVersion !== 1 || !Array.isArray(imported.scenes) || imported.scenes.length < 1 || imported.scenes.length > 64)
        throw new Error('不是受支持的 Studio 集合');
      imported.revision = studioDraft.revision;
      const scene = imported.scenes.find((candidate) => candidate.id === imported.previewSceneId) ?? imported.scenes[0];
      dirtyRef.current = true;
      setStudioDraft(imported);
      setSelectedSceneId(scene.id);
      setDraft(cloneScene(scene));
      setBaseline(studioBaseline?.scenes.find((candidate) => candidate.id === scene.id) ?? scene);
      setNotice('集合已导入到浏览器草稿；服务器会在保存时执行完整校验。');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '导入失败');
    } finally {
      if (importRef.current) importRef.current.value = '';
    }
  };

  const runStudioAction = async (action: 'take' | 'undo' | 'redo') => {
    if (!studioDraft || dirty || saving) return;
    setSaving(true);
    savingRef.current = true;
    setNotice('');
    try {
      const committed = await studioAction(action, studioDraft.revision);
      applyRemoteStudio(committed);
      setNotice(action === 'take' ? `Take 完成：${committed.programSceneId} 已进入 Program。`
        : `${action === 'undo' ? '撤销' : '重做'}完成（s${committed.revision}）。`);
    } catch (error) {
      if (error instanceof ControlApiError && error.status === 412)
        setConflict(`操作冲突：服务器当前为 s${error.revision ?? '未知'}，请重新载入。`);
      else
        setNotice(error instanceof Error ? error.message : 'Studio 操作失败');
    } finally {
      setSaving(false);
      savingRef.current = false;
    }
  };

  const transformSelection = (operation: 'left' | 'hcenter' | 'right' | 'top' | 'vcenter' | 'bottom' | 'hdistribute' | 'vdistribute') => {
    updateDraft((scene) => {
      const chosen = scene.items.filter((item) => selectedSourceIds.includes(item.sourceId));
      if (chosen.length < 2) return scene;
      const left = Math.min(...chosen.map((item) => item.x));
      const right = Math.max(...chosen.map((item) => item.x + item.width));
      const top = Math.min(...chosen.map((item) => item.y));
      const bottom = Math.max(...chosen.map((item) => item.y + item.height));
      const updates = new Map<string, Partial<SceneItem>>();
      if (operation === 'hdistribute' && chosen.length >= 3) {
        const ordered = [...chosen].sort((a, b) => a.x - b.x);
        const occupied = ordered.reduce((sum, item) => sum + item.width, 0);
        const gap = (right - left - occupied) / (ordered.length - 1);
        let cursor = left;
        ordered.forEach((item) => { updates.set(item.id, { x: Math.round(cursor) }); cursor += item.width + gap; });
      } else if (operation === 'vdistribute' && chosen.length >= 3) {
        const ordered = [...chosen].sort((a, b) => a.y - b.y);
        const occupied = ordered.reduce((sum, item) => sum + item.height, 0);
        const gap = (bottom - top - occupied) / (ordered.length - 1);
        let cursor = top;
        ordered.forEach((item) => { updates.set(item.id, { y: Math.round(cursor) }); cursor += item.height + gap; });
      } else {
        chosen.forEach((item) => updates.set(item.id, operation === 'left' ? { x: left }
          : operation === 'hcenter' ? { x: Math.round((left + right - item.width) / 2) }
            : operation === 'right' ? { x: right - item.width }
              : operation === 'top' ? { y: top }
                : operation === 'vcenter' ? { y: Math.round((top + bottom - item.height) / 2) }
                  : { y: bottom - item.height }));
      }
      return { ...scene, items: scene.items.map((item) => updates.has(item.id) && !item.locked ? { ...item, ...updates.get(item.id)! } : item) };
    });
  };

  const groupSelection = () => {
    if (selectedSourceIds.length < 2) return;
    const groupId = `group-${Date.now().toString(36)}`;
    updateDraft((scene) => ({ ...scene, items: scene.items.map((item) => selectedSourceIds.includes(item.sourceId) ? { ...item, groupId } : item) }));
  };

  const reloadAfterConflict = async () => {
    if (dirty && !window.confirm('重新载入会放弃当前未保存修改，继续吗？')) return;
    await reload();
  };

  if (productArea === 'archive') {
    return <NvrTimeline onBack={() => {
      window.history.replaceState(null, '', window.location.pathname);
      setProductArea('studio');
    }} />;
  }
  if (productArea === 'devices') {
    return <CameraRegistry onBack={() => {
      window.history.replaceState(null, '', window.location.pathname);
      setProductArea('studio');
    }} />;
  }
  if (productArea === 'clients') {
    return <ClientsPanel onBack={() => {
      window.history.replaceState(null, '', window.location.pathname);
      setProductArea('studio');
    }} />;
  }
  if (productArea === 'system') {
    return <SystemStatus onBack={() => {
      window.history.replaceState(null, '', window.location.pathname);
      setProductArea('studio');
    }} />;
  }
  if (productArea === 'events') {
    return <EventsPanel onBack={() => {
      window.history.replaceState(null, '', window.location.pathname);
      setProductArea('studio');
    }} />;
  }

  if (!draft || !studioDraft) {
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
  const selectedCapability = studioCapabilities?.scenes.find((scene) => scene.sceneId === draft.id);
  const newSourceValueValid = newKind === 'camera' ? /^[a-zA-Z0-9._-]{1,64}\/[a-zA-Z0-9._-]{1,64}$/.test(newUrl)
    : newKind === 'rtsp' ? /^rtsps?:\/\/\S+$/i.test(newUrl)
    : newKind === 'browser' ? /^https?:\/\/\S+$/i.test(newUrl)
      : newKind === 'image' || newKind === 'media' ? /^\/(assets|recordings)\/[^.\/][^\r\n]*$/i.test(newUrl)
        : newKind === 'color' ? /^#[0-9a-f]{6}$/i.test(newUrl)
          : newKind === 'nested' ? studioDraft.scenes.some((scene) => scene.id === newUrl && scene.id !== draft.id)
            : newUrl.trim().length > 0;

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
          <span className="eyebrow">Preview 场景</span>
          <input
            aria-label="场景名称"
            value={draft.name}
            maxLength={128}
            onChange={(event) => updateDraft((scene) => ({ ...scene, name: event.target.value }))}
          />
        </div>
        <div className="top-actions">
          <button className="ghost-button" type="button" onClick={() => {
            window.history.replaceState(null, '', '#system');
            setProductArea('system');
          }}>系统状态</button>
          <button className="ghost-button" type="button" onClick={() => {
            window.history.replaceState(null, '', '#devices');
            setProductArea('devices');
          }}>设备管理</button>
          <button className="ghost-button" type="button" onClick={() => {
            window.history.replaceState(null, '', '#clients');
            setProductArea('clients');
          }}>本地客户端</button>
          <button className="ghost-button" type="button" onClick={() => {
            window.history.replaceState(null, '', '#events');
            setProductArea('events');
          }}>事件中心</button>
          <button className="ghost-button" type="button" onClick={() => {
            window.history.replaceState(null, '', '#archive');
            setProductArea('archive');
          }}>录像时间线</button>
          <span className={`connection ${connection}`}>
            <i aria-hidden="true" />
            {connection === 'online' ? '实时同步' : connection === 'connecting' ? '正在连接' : '连接中断'}
          </span>
          <span className="revision">s{studioDraft.revision}</span>
          <button className="ghost-button" type="button" disabled={dirty || saving} onClick={() => runStudioAction('undo')}>撤销</button>
          <button className="ghost-button" type="button" disabled={dirty || saving} onClick={() => runStudioAction('redo')}>重做</button>
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

      <section className="studio-deck" aria-label="Studio 场景集合">
        <div className="studio-buses">
          <div className="bus-card program-bus">
            <span>PROGRAM</span>
            <strong>{studioDraft.scenes.find((scene) => scene.id === studioDraft.programSceneId)?.name ?? studioDraft.programSceneId}</strong>
          </div>
          <button
            className="take-button"
            type="button"
            disabled={dirty || saving}
            onClick={() => runStudioAction('take')}
          >TAKE</button>
          <div className="bus-card preview-bus">
            <span>PREVIEW</span>
            <strong>{draft.name}</strong>
          </div>
        </div>
        <div className="scene-collection" role="list" aria-label="命名场景">
          {studioDraft.scenes.map((scene) => (
            <button
              className={`scene-chip ${scene.id === selectedSceneId ? 'selected' : ''}`}
              type="button"
              role="listitem"
              key={scene.id}
              onClick={() => selectScene(scene.id)}
            >
              <span className="scene-thumb" style={{ backgroundColor: scene.canvas.backgroundColor }}>
                {scene.items.slice(0, 6).map((item) => <i key={item.id} style={{
                  left: `${item.x / scene.canvas.width * 100}%`, top: `${item.y / scene.canvas.height * 100}%`,
                  width: `${item.width / scene.canvas.width * 100}%`, height: `${item.height / scene.canvas.height * 100}%`,
                }} />)}
              </span>
              <strong>{scene.name}</strong>
              <small>{scene.id === studioDraft.programSceneId ? 'PGM' : ''}{scene.id === studioDraft.previewSceneId ? ' PVW' : ''}</small>
            </button>
          ))}
        </div>
        <div className="studio-tools">
          <button className="ghost-button" type="button" onClick={() => moveScene(-1)}>←</button>
          <button className="ghost-button" type="button" onClick={() => moveScene(1)}>→</button>
          <button className="ghost-button" type="button" disabled={studioDraft.scenes.length >= 64} onClick={duplicateScene}>复制场景</button>
          <button className="ghost-button" type="button" disabled={studioDraft.scenes.length >= 64} onClick={() => addTemplate('grid')}>四宫格模板</button>
          <button className="ghost-button" type="button" disabled={studioDraft.scenes.length >= 64} onClick={() => addTemplate('focus')}>主画面模板</button>
          <button className="ghost-button" type="button" disabled={studioDraft.scenes.length <= 1 || studioDraft.programSceneId === selectedSceneId} onClick={removeScene}>删除场景</button>
          <button className="ghost-button" type="button" onClick={exportStudio}>导出</button>
          <button className="ghost-button" type="button" onClick={() => importRef.current?.click()}>导入</button>
          <input ref={importRef} className="visually-hidden" type="file" accept="application/json,.json" onChange={(event) => void importStudio(event.target.files?.[0])} />
          <label className="inline-field">转场
            <select value={studioDraft.transition.kind} onChange={(event) => {
              dirtyRef.current = true;
              setStudioDraft({ ...studioDraft, transition: { ...studioDraft.transition, kind: event.target.value as 'cut' | 'fade' } });
            }}><option value="cut">Cut</option><option value="fade">Fade</option></select>
          </label>
          <label className="inline-field">时长
            <input type="number" min="0" max="10000" step="50" value={studioDraft.transition.durationMs} onChange={(event) => {
              dirtyRef.current = true;
              setStudioDraft({ ...studioDraft, transition: { ...studioDraft.transition, durationMs: clamp(Number(event.target.value), 0, 10000) } });
            }} /> ms
          </label>
        </div>
      </section>

      {selectedCapability && !selectedCapability.direct.exact && (
        <div className="capability-alert" role="status">
          Direct 会自动降级为 {selectedCapability.direct.selected.toUpperCase()}：
          {selectedCapability.direct.reasons.join('；')}
        </div>
      )}

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
              const selected = selectedSourceIds.includes(source.id);
              return (
                <button
                  className={`source-card ${selected ? 'selected' : ''}`}
                  type="button"
                  key={source.id}
                  onClick={(event) => selectSource(source.id, event.shiftKey || event.ctrlKey || event.metaKey)}
                >
                  <span className="source-index">{String(index + 1).padStart(2, '0')}</span>
                  <span className="source-copy">
                    <strong>{source.name}</strong>
                    <small>{source.kind === 'rtsp' ? source.transport.toUpperCase() : source.kind === 'camera' ? 'REGISTRY' : source.kind.toUpperCase()} · {item?.visible === false ? '已隐藏' : '画布中'}</small>
                  </span>
                  <span className={`source-state ${item?.visible === false ? 'hidden' : ''}`} aria-hidden="true" />
                </button>
              );
            })}
          </div>

          {adding ? (
            <div className="add-source-form">
              <label className="field">
                <span>来源类型</span>
                <select value={newKind} onChange={(event) => {
                  const kind = event.target.value as AddSourceKind;
                  setNewKind(kind);
                  setNewName(kind === 'camera' || kind === 'rtsp' ? '新摄像头' : `新${{ browser: '网页', image: '图片', media: '媒体', text: '文字', color: '色块', nested: '嵌套场景' }[kind]}`);
                  setNewUrl(kind === 'color' ? '#2563eb' : '');
                }}>
                  <option value="camera">Camera Registry（推荐）</option>
                  <option value="rtsp">RTSP 摄像头</option>
                  <option value="browser">浏览器网页</option>
                  <option value="image">图片素材</option>
                  <option value="media">本地媒体</option>
                  <option value="text">文字</option>
                  <option value="color">纯色</option>
                  <option value="nested">场景作为来源</option>
                </select>
              </label>
              <label className="field">
                <span>显示名称</span>
                <input value={newName} maxLength={128} onChange={(event) => setNewName(event.target.value)} />
              </label>
              {newKind === 'camera' ? (
                <label className="field"><span>设备与码流 Profile</span><select value={newUrl} onChange={(event) => {
                  const value = event.target.value;
                  setNewUrl(value);
                  const [cameraId] = value.split('/', 1);
                  const camera = registryCameras.find((candidate) => candidate.id === cameraId);
                  if (camera) setNewName(camera.name);
                }}>
                  <option value="">选择已登记设备…</option>
                  {registryCameras.flatMap((camera) => camera.profiles.map((profile) => (
                    <option key={`${camera.id}/${profile.id}`} value={`${camera.id}/${profile.id}`}>
                      {camera.name} · {profile.role} · {profile.videoCodec || 'unknown'} {profile.width ? `${profile.width}×${profile.height}` : ''}
                    </option>
                  )))}
                </select>{registryCameras.length === 0 && <small>请先进入“设备管理”添加或发现摄像机。</small>}</label>
              ) : newKind === 'nested' ? (
                <label className="field"><span>嵌套场景</span><select value={newUrl} onChange={(event) => setNewUrl(event.target.value)}>
                  <option value="">选择场景…</option>
                  {studioDraft.scenes.filter((scene) => scene.id !== draft.id).map((scene) => <option key={scene.id} value={scene.id}>{scene.name}</option>)}
                </select></label>
              ) : (
                <label className="field">
                  <span>{newKind === 'rtsp' ? 'RTSP 地址' : newKind === 'browser' ? '网页地址'
                    : newKind === 'image' || newKind === 'media' ? '容器内素材路径'
                      : newKind === 'text' ? '文字内容' : '颜色'}</span>
                  <input
                    value={newUrl}
                    type={newKind === 'color' ? 'color' : 'text'}
                    inputMode={newKind === 'rtsp' || newKind === 'browser' ? 'url' : 'text'}
                    autoComplete="off"
                    spellCheck={false}
                    placeholder={newKind === 'rtsp' ? 'rtsp://camera-host/stream'
                      : newKind === 'browser' ? 'https://dashboard.example/view'
                        : newKind === 'image' ? '/assets/logo.png'
                          : newKind === 'media' ? '/recordings/clip.mp4' : ''}
                    onChange={(event) => setNewUrl(event.target.value)}
                  />
                </label>
              )}
              {newKind === 'rtsp' && (
                <label className="field">
                  <span>传输方式</span>
                  <select value={newTransport} onChange={(event) => setNewTransport(event.target.value as Transport)}>
                    <option value="tcp">TCP（推荐）</option>
                    <option value="udp">UDP</option>
                  </select>
                </label>
              )}
              <p className="security-note">{newKind === 'rtsp'
                ? '凭据不会由 API 回显。请勿在共享屏幕或浏览器同步中保存真实地址。'
                : newKind === 'camera' ? 'Scene 只保存 cameraId/profileId；账号密码由容器 Secret 引用在内部解析。'
                  : newKind === 'browser' ? '只允许管理员批准的网页 Origin；私网地址还需显式启用。'
                  : newKind === 'image' || newKind === 'media' ? '素材路径仅允许 /assets 或 /recordings，拒绝目录穿越。'
                    : newKind === 'nested' ? '嵌套深度最多两级，循环引用会由服务器拒绝。'
                      : '该来源由 libobs 在容器内生成，不会加载外部网络内容。'}</p>
              <div className="form-actions">
                <button className="ghost-button" type="button" onClick={() => setAdding(false)}>取消</button>
                <button
                  className="primary-button"
                  type="button"
                  disabled={!newName.trim() || !newSourceValueValid}
                  onClick={addSource}
                >添加到画布</button>
              </div>
            </div>
          ) : (
            <button className="add-source-button" type="button" onClick={() => setAdding(true)} disabled={draft.sources.length >= 64}>
              <span aria-hidden="true">＋</span> 添加来源
            </button>
          )}
        </aside>

        <section className="workspace">
          <div className="workspace-toolbar">
            <div>
              <span className="eyebrow">Studio 画布</span>
              <strong>{draft.canvas.width} × {draft.canvas.height}</strong>
            </div>
            <div className="workspace-mode" aria-label="工作区显示模式">
              <button className={workspaceMode === 'program' ? 'active' : ''} type="button" onClick={() => setWorkspaceMode('program')}>实时节目</button>
              <button className={workspaceMode === 'layout' ? 'active' : ''} type="button" onClick={() => setWorkspaceMode('layout')}>布局编辑</button>
            </div>
          </div>
          {workspaceMode === 'program' && (
            <div className="playback-mode" aria-label="实时播放渲染模式">
              <span>渲染路径</span>
              <button className={playbackMode === 'composite' ? 'active' : ''} type="button" onClick={() => selectPlaybackMode('composite')}>服务端合成</button>
              <button className={playbackMode === 'direct' ? 'active' : ''} type="button" onClick={() => selectPlaybackMode('direct')}>网关直通</button>
              <button type="button" onClick={() => void toggleFullscreen()}>真全屏</button>
            </div>
          )}
          {workspaceMode === 'layout' && <div className="canvas-tools" aria-label="画布工具">
            <span>缩放 {Math.round(canvasZoom * 100)}%</span>
            <button type="button" onClick={() => setCanvasZoom((value) => clamp(value - 0.1, 0.5, 1.5))}>−</button>
            <button type="button" onClick={() => setCanvasZoom(1)}>适屏</button>
            <button type="button" onClick={() => setCanvasZoom((value) => clamp(value + 0.1, 0.5, 1.5))}>＋</button>
            <i />
            {([['left', '左齐'], ['hcenter', '水平中'], ['right', '右齐'], ['top', '顶齐'], ['vcenter', '垂直中'], ['bottom', '底齐'], ['hdistribute', '横向均布'], ['vdistribute', '纵向均布']] as const).map(([operation, label]) =>
              <button type="button" key={operation} disabled={selectedSourceIds.length < 2} onClick={() => transformSelection(operation)}>{label}</button>)}
            <button type="button" disabled={selectedSourceIds.length < 2} onClick={groupSelection}>成组</button>
          </div>}
          <div className="stage-wrap" ref={monitorRef} data-fullscreen={fullscreen ? 'true' : 'false'}>
            {workspaceMode === 'program' && fullscreen && (
              <div className="monitor-overlay">
                <button type="button" onClick={() => void toggleFullscreen()}>退出全屏</button>
                <button type="button" onClick={() => void document.exitFullscreen().then(() => setWorkspaceMode('layout'))}>布局编辑</button>
                <span>{playbackMode === 'direct' ? 'Direct' : 'Composite'}</span>
                <span>{wakeLockState === 'active' ? '● 屏幕常亮' : wakeLockState === 'unsupported' ? '⚠ 不支持防休眠' : wakeLockState === 'failed' ? '⚠ 防休眠申请失败' : '屏幕常亮待申请'}</span>
              </div>
            )}
            {workspaceMode === 'program' ? (
              playbackMode === 'composite'
                ? <ProgramPreview aspectRatio={`${draft.canvas.width} / ${draft.canvas.height}`} />
                : <DirectPreview scene={programScene ?? baseline ?? draft} />
            ) : draft.items.length === 0 ? <EmptyState onAdd={() => setAdding(true)} /> : (
              <div
                className="stage"
                ref={stageRef}
                style={{ aspectRatio: `${draft.canvas.width} / ${draft.canvas.height}`, backgroundColor: draft.canvas.backgroundColor, transform: `scale(${canvasZoom})` }}
                onPointerDown={() => { setSelectedSourceId(null); setSelectedSourceIds([]); }}
              >
                <div className="stage-grid" aria-hidden="true" />
                <div className="stage-safe-area" aria-hidden="true" />
                {[...draft.items].sort((left, right) => left.zIndex - right.zIndex).map((item) => {
                  const source = draft.sources.find((candidate) => candidate.id === item.sourceId);
                  if (!source) return null;
                  const selected = selectedSourceIds.includes(source.id);
                  const tileStyle = {
                    left: `${(item.x / draft.canvas.width) * 100}%`,
                    top: `${(item.y / draft.canvas.height) * 100}%`,
                    width: `${(item.width / draft.canvas.width) * 100}%`,
                    height: `${(item.height / draft.canvas.height) * 100}%`,
                    zIndex: item.zIndex + 1,
                    opacity: item.opacity,
                    transform: `rotate(${item.rotation}deg)`,
                    '--source-hue': sourceHue(source.id),
                  } as CSSProperties;
                  return (
                    <div
                      className={`camera-tile ${selected ? 'selected' : ''} ${item.visible ? '' : 'invisible'} ${item.locked ? 'locked' : ''}`}
                      style={tileStyle}
                      key={item.id}
                      role="button"
                      tabIndex={0}
                      aria-label={`${source.name}，位置 ${item.x}, ${item.y}，尺寸 ${item.width} × ${item.height}`}
                      onClick={(event) => { event.stopPropagation(); selectSource(source.id, event.shiftKey || event.ctrlKey || event.metaKey); }}
                      onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') selectSource(source.id, event.shiftKey || event.ctrlKey || event.metaKey); }}
                      onPointerDown={(event) => beginPointer(event, item, 'move')}
                    >
                      <div className="tile-noise" aria-hidden="true" />
                      <span className="tile-tag">{source.kind === 'rtsp'
                        ? `RTSP · ${source.transport.toUpperCase()}`
                        : source.kind === 'camera' ? `CAMERA · ${source.profileId}`
                          : source.kind === 'browser' ? `BROWSER · ${source.width}×${source.height}`
                          : source.kind.toUpperCase()}</span>
                      <div className="tile-caption">
                        <strong>{source.name}</strong>
                        <span>{item.width} × {item.height}{item.locked ? ' · 锁定' : ''}</span>
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
            <span>{workspaceMode === 'program' ? (playbackMode === 'direct' ? 'Direct WHEP' : 'Composite WHEP') : '布局预览'}</span>
            <span>{workspaceMode === 'program'
              ? (playbackMode === 'direct' ? '每路来源按同一场景文档在浏览器布局，内部 RTSP 与媒体路径均不暴露' : '浏览器播放容器内 libobs 合成节目')
              : '编辑仅作用于 Preview；保存后仍需 Take 才会进入 Program'}</span>
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
                {selectedSource.kind === 'rtsp' ? (
                  <>
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
                  </>
                ) : selectedSource.kind === 'camera' ? (
                  <>
                    <label className="field"><span>Camera ID</span><input value={selectedSource.cameraId} readOnly /></label>
                    <label className="field"><span>Profile ID</span><input value={selectedSource.profileId} readOnly /></label>
                    <label className="field"><span>硬件解码</span><select value={selectedSource.hardwareDecode} onChange={(event) => updateSource(selectedSource.id, { hardwareDecode: event.target.value as 'auto' | 'on' | 'off' })}>
                      <option value="auto">自动（推荐）</option><option value="on">优先硬件</option><option value="off">关闭</option>
                    </select></label>
                    <p className="security-note">端点和凭据由 Camera Registry 内部解析；要切换设备或 Profile，请移除此来源后重新选择。</p>
                  </>
                ) : selectedSource.kind === 'browser' ? (
                  <>
                    <label className="field">
                      <span>网页地址</span>
                      <input
                        value={selectedSource.url}
                        autoComplete="off"
                        spellCheck={false}
                        onChange={(event) => updateSource(selectedSource.id, { url: event.target.value })}
                      />
                    </label>
                    <p className="security-note"><code>?***</code> 或 <code>#***</code> 表示服务器保留的查询参数或片段；来源必须命中管理员允许列表。</p>
                    <div className="field-grid">
                      <NumberField label="网页宽" value={selectedSource.width} min={16} max={8192} onChange={(width) => updateSource(selectedSource.id, { width })} />
                      <NumberField label="网页高" value={selectedSource.height} min={16} max={8192} onChange={(height) => updateSource(selectedSource.id, { height })} />
                      <NumberField label="帧率" value={selectedSource.fps} min={1} max={60} onChange={(fps) => updateSource(selectedSource.id, { fps })} />
                    </div>
                    <label className="field">
                      <span>自定义 CSS（最多 32 KiB）</span>
                      <textarea value={selectedSource.customCss} maxLength={32768} onChange={(event) => updateSource(selectedSource.id, { customCss: event.target.value })} />
                    </label>
                    <Toggle label="隐藏时释放浏览器" checked={selectedSource.shutdownWhenHidden} onChange={(shutdownWhenHidden) => updateSource(selectedSource.id, { shutdownWhenHidden })} />
                    <Toggle label="重新显示时刷新" checked={selectedSource.restartWhenActive} onChange={(restartWhenActive) => updateSource(selectedSource.id, { restartWhenActive })} />
                  </>
                ) : selectedSource.kind === 'image' || selectedSource.kind === 'media' ? (
                  <>
                    <label className="field"><span>素材路径</span><input value={selectedSource.filePath} onChange={(event) => updateSource(selectedSource.id, { filePath: event.target.value })} /></label>
                    {selectedSource.kind === 'media' && <Toggle label="循环播放" checked={selectedSource.loop} onChange={(loop) => updateSource(selectedSource.id, { loop })} />}
                    <p className="security-note">只接受容器中的 /assets 或 /recordings 绝对路径。</p>
                  </>
                ) : selectedSource.kind === 'text' ? (
                  <>
                    <label className="field"><span>文字</span><textarea value={selectedSource.text} maxLength={8192} onChange={(event) => updateSource(selectedSource.id, { text: event.target.value })} /></label>
                    <label className="field"><span>颜色</span><input type="color" value={selectedSource.color} onChange={(event) => updateSource(selectedSource.id, { color: event.target.value })} /></label>
                  </>
                ) : selectedSource.kind === 'color' ? (
                  <label className="field"><span>填充颜色</span><input type="color" value={selectedSource.color} onChange={(event) => updateSource(selectedSource.id, { color: event.target.value })} /></label>
                ) : (
                  <label className="field"><span>嵌套场景</span><select value={selectedSource.sceneId} onChange={(event) => updateSource(selectedSource.id, { sceneId: event.target.value })}>
                    {studioDraft.scenes.filter((scene) => scene.id !== draft.id).map((scene) => <option key={scene.id} value={scene.id}>{scene.name}</option>)}
                  </select></label>
                )}
                <Toggle label="静音" checked={selectedSource.muted} onChange={(muted) => updateSource(selectedSource.id, { muted })} />
                <label className="range-field">
                  <span>音量 <strong>{Math.round(selectedSource.volume * 100)}%</strong></span>
                  <input type="range" min="0" max="1" step="0.01" value={selectedSource.volume} onChange={(event) => updateSource(selectedSource.id, { volume: Number(event.target.value) })} />
                </label>
                <div className="field-grid">
                  <NumberField label="同步偏移（ms）" value={selectedSource.syncOffsetMs} min={-10000} max={10000} onChange={(syncOffsetMs) => updateSource(selectedSource.id, { syncOffsetMs })} />
                  <NumberField label="音轨" value={selectedSource.audioTrack} min={1} max={6} onChange={(audioTrack) => updateSource(selectedSource.id, { audioTrack })} />
                </div>
                <label className="field">
                  <span>监听模式</span>
                  <select value={selectedSource.monitoring} onChange={(event) => updateSource(selectedSource.id, { monitoring: event.target.value as AudioMonitoring })}>
                    <option value="off">关闭</option>
                    <option value="monitor-only">仅监听</option>
                    <option value="monitor-and-output">监听并输出</option>
                  </select>
                </label>
                <p className="security-note">M5 起步：同步、监听和轨道已应用到 libobs；最终 MP4 与 Composite WebRTC 音频输出仍待后续门禁。</p>
              </section>

              <section className="property-section">
                <div className="section-title-row"><h3>滤镜链</h3><button className="ghost-button" type="button" disabled={selectedSource.filters.length >= 16} onClick={() => addFilter(selectedSource)}>添加</button></div>
                {selectedSource.filters.length === 0 && <p className="security-note">滤镜按列表顺序在 libobs 中执行。</p>}
                {selectedSource.filters.map((filter, index) => <div className="filter-card" key={filter.id}>
                  <Toggle label={`#${index + 1} 启用`} checked={filter.enabled} onChange={(enabled) => updateFilter(selectedSource, filter.id, { enabled })} />
                  <label className="field"><span>类型</span><select value={filter.kind} onChange={(event) => updateFilter(selectedSource, filter.id, { kind: event.target.value as FilterKind })}>
                    <option value="crop-pad">裁切/扩边</option><option value="opacity">透明度</option><option value="color-correction">色彩校正</option>
                    <option value="mask-blend">遮罩/混合</option><option value="lut">LUT</option><option value="scaling">缩放</option><option value="delay">延迟</option>
                  </select></label>
                  <NumberField label="数值" value={filter.amount} min={-10000} max={10000} step={0.01} onChange={(amount) => updateFilter(selectedSource, filter.id, { amount })} />
                  <label className="field"><span>路径/参数</span><input value={filter.value} maxLength={4096} onChange={(event) => updateFilter(selectedSource, filter.id, { value: event.target.value })} /></label>
                  <div className="filter-actions">
                    <button type="button" disabled={index === 0} onClick={() => updateSource(selectedSource.id, { filters: selectedSource.filters.map((entry, position, all) => position === index - 1 ? all[index] : position === index ? all[index - 1] : entry) })}>上移</button>
                    <button type="button" disabled={index === selectedSource.filters.length - 1} onClick={() => updateSource(selectedSource.id, { filters: selectedSource.filters.map((entry, position, all) => position === index + 1 ? all[index] : position === index ? all[index + 1] : entry) })}>下移</button>
                    <button type="button" onClick={() => updateSource(selectedSource.id, { filters: selectedSource.filters.filter((entry) => entry.id !== filter.id) })}>删除</button>
                  </div>
                </div>)}
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
                    <Toggle label="锁定画布操作" checked={selectedItem.locked} onChange={(locked) => updateItem(selectedItem.id, { locked })} />
                    <div className="field-grid">
                      <NumberField label="旋转（°）" value={selectedItem.rotation} min={-3600} max={3600} step={0.1} onChange={(rotation) => updateItem(selectedItem.id, { rotation })} />
                      <NumberField label="透明度" value={selectedItem.opacity} min={0} max={1} step={0.01} onChange={(opacity) => updateItem(selectedItem.id, { opacity })} />
                    </div>
                    <label className="field"><span>混合模式</span><select value={selectedItem.blendMode} onChange={(event) => updateItem(selectedItem.id, { blendMode: event.target.value as SceneItem['blendMode'] })}>
                      <option value="normal">Normal</option><option value="add">Add</option><option value="multiply">Multiply</option><option value="screen">Screen</option>
                    </select></label>
                    <label className="field"><span>组 ID（可选）</span><input value={selectedItem.groupId} maxLength={64} onChange={(event) => updateItem(selectedItem.id, { groupId: event.target.value.replace(/[^a-zA-Z0-9._-]/g, '') })} /></label>
                    <div className="transform-presets">
                      <button type="button" onClick={() => updateItem(selectedItem.id, { x: 0, y: 0, width: draft.canvas.width, height: draft.canvas.height, scaleMode: 'contain' })}>适应</button>
                      <button type="button" onClick={() => updateItem(selectedItem.id, { x: 0, y: 0, width: draft.canvas.width, height: draft.canvas.height, scaleMode: 'cover' })}>填充</button>
                      <button type="button" onClick={() => updateItem(selectedItem.id, { x: 0, y: 0, width: draft.canvas.width, height: draft.canvas.height, scaleMode: 'stretch' })}>拉伸</button>
                      <button type="button" onClick={() => updateItem(selectedItem.id, { x: Math.round((draft.canvas.width - selectedItem.width) / 2), y: Math.round((draft.canvas.height - selectedItem.height) / 2) })}>居中</button>
                    </div>
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
