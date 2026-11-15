import { useEffect, useMemo, useRef, useState } from 'react';
import { isPageVisible, subscribePageVisibility } from './pageVisibility';
import { ControlApiError, fetchAudioMeters, fetchStudio, probeSourceProfile, replaceStudio } from './api';
import { useDesktopWork } from './desktopRuntime';
import { useDraftGuard } from './useDraftGuard';
import { withRequestTimeout } from './requestTimeout';
import DirectPreview from './DirectPreview';
import { connectAudioTrack, type AudioChannelState, type AudioTrackConnection } from './audioTrackChannel';
import { getDirectAudioMixer, type DirectAudioSnapshot, type DirectAudioTrackSelection } from './directAudioMixer';
import { defaultSelectedTracks, fetchSourceAudioTracks, invalidateSourceAudioTracks, type SourceAudioTrack, type SourceAudioTracks } from './sourceAudio';
import { sourceAudioTrackState } from './monitorView';
import { ownRecordValue } from './recordValue';
import type { AudioMonitoring, SceneSource, StudioDocument } from './types';

const dbLabel = (value: number | null | undefined) => value === null || value === undefined ? '—' : `${value.toFixed(1)} dBFS`;
const meterWidth = (value: number | null | undefined) => value === null || value === undefined ? 0 : Math.max(0, Math.min(100, (value + 120) / 1.2));
const trackLabel = (track: SourceAudioTrack) => {
  const name = track.title || track.language || `轨道 ${track.index + 1}`;
  return `${name} · ${track.codec}${track.channels > 1 ? ` ${track.channels}ch` : ''}`;
};

interface TrackSelection {
  selected: number[];
  gain: Record<number, number>;
  muted: Record<number, boolean>;
  /** Per-track sync offset in milliseconds (applied by the gateway mix). */
  offset: Record<number, number>;
  mode: 'merged' | 'independent';
}

function initialTrackSelection(source: SceneSource | undefined, tracks: SourceAudioTrack[]): TrackSelection {
  const saved = source?.audioInputs ?? [];
  const gain: Record<number, number> = {};
  const muted: Record<number, boolean> = {};
  const offset: Record<number, number> = {};
  for (const input of saved) {
    gain[input.track] = input.gain;
    muted[input.track] = input.muted;
    offset[input.track] = input.syncOffsetMs ?? 0;
  }
  return {
    // Explicit [] is intentional silence. Missing selected tracks must not
    // silently switch to a different track either; only legacy omission defaults.
    selected: source?.audioInputs !== undefined
      ? saved.map((input) => input.track).sort((left, right) => left - right)
      : defaultSelectedTracks(tracks),
    gain, muted, offset, mode: 'merged',
  };
}

interface ChannelEntry {
  element: HTMLAudioElement;
  connection: AudioTrackConnection;
}

export default function AudioWorkspace({ studio, onCommitted, localPlayback = true }: { studio: StudioDocument; onCommitted: (studio: StudioDocument) => void; localPlayback?: boolean }) {
  const [nativeForeground, setNativeForeground] = useState(window.webobsAndroidForeground !== false);
  useEffect(() => subscribePageVisibility(() => setNativeForeground(window.webobsAndroidForeground !== false)), []);
  const [sceneId, setSceneId] = useState(studio.previewSceneId);
  const [topology, setTopology] = useState<'direct' | 'composite'>('direct');
  const [snapshot, setSnapshot] = useState<DirectAudioSnapshot>({ state: 'disabled', inputCount: 0, level: 0, sources: [] });
  const [tracksBySource, setTracksBySource] = useState<Record<string, SourceAudioTracks>>({});
  const [selection, setSelection] = useState<Record<string, TrackSelection>>({});
  const [channelStates, setChannelStates] = useState<Record<string, AudioChannelState>>({});
  const [pending, setPending] = useState<StudioDocument | null>(null);
  // Track selections are unsaved document changes even without a scene edit.
  const [audioDirty, setAudioDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(false);
  const [reloadGeneration, setReloadGeneration] = useState(0);
  const lastRevision = useRef(studio.revision);
  const latestStudio = useRef(studio);
  latestStudio.current = studio;
  const requestOwner = useRef(new AbortController());
  useEffect(() => {
    const owner = new AbortController(); requestOwner.current = owner;
    return () => owner.abort();
  }, []);
  const dirty = Boolean(pending) || audioDirty;
  useDesktopWork('audio-workspace', dirty, saving);
  useDraftGuard(dirty, saving, '离开将放弃未保存的音频修改，继续吗？', setError);
  const channels = useRef(new Map<string, ChannelEntry>());
  const probeGeneration = useRef(0);
  const mixer = useMemo(() => getDirectAudioMixer(), []);
  const scene = (pending ?? studio).scenes.find((candidate) => candidate.id === sceneId)
    ?? (pending ?? studio).scenes[0];
  const sourceIds = scene ? scene.sources.map((source) => `${source.id}:${source.kind}:${source.kind === 'camera' ? `${source.cameraId}/${source.profileId}` : ''}`).join(',') : '';

  useEffect(() => {
    if (topology !== 'direct' || !localPlayback) return;
    setSnapshot(mixer.getSnapshot());
    const receive = (event: Event) => setSnapshot((event as CustomEvent<DirectAudioSnapshot>).detail);
    window.addEventListener('webobs:direct-audio-meters', receive);
    return () => window.removeEventListener('webobs:direct-audio-meters', receive);
  }, [topology, mixer, localPlayback]);
  useEffect(() => {
    if (lastRevision.current === studio.revision) return;
    lastRevision.current = studio.revision;
    if (dirty) {
      setConflict(true);
      setError('服务器音频或场景配置已更新。当前修改已保留，请放弃修改并重新载入后再编辑。');
    } else {
      setSelection({});
      setChannelStates({});
    }
  }, [studio.revision]);
  useEffect(() => {
    if (topology !== 'composite' || !scene) return;
    let active = true;
    let timer: number | undefined;
    let request: AbortController | null = null;
    setSnapshot((current) => ({ ...current, sources: [] }));
    const poll = async () => {
      if (!active || request || !isPageVisible()) return;
      const controller = new AbortController(); request = controller;
      try {
        const value = await fetchAudioMeters(scene.id, 'composite', controller.signal);
        if (active && request === controller && !controller.signal.aborted && isPageVisible()) {
          setSnapshot((current) => ({ ...current,
            // Composite meters come from libobs and are per source, not per track.
            sources: value.sources.map((source) => ({ ...source,
              merged: { rmsDbfs: source.rmsDbfs, peakDbfs: source.peakDbfs }, independent: [] })) }));
        }
      } catch { /* Keep the last measured level while the backend is unavailable. */ }
      finally {
        if (request === controller) {
          request = null;
          if (active && isPageVisible()) timer = window.setTimeout(() => void poll(), 250);
        }
      }
    };
    const visibility = () => {
      window.clearTimeout(timer); timer = undefined;
      if (!isPageVisible()) { request?.abort(); request = null; }
      else void poll();
    };
    const unsubscribe = subscribePageVisibility(visibility);
    void poll();
    return () => { active = false; unsubscribe(); window.clearTimeout(timer); request?.abort(); request = null; };
  }, [scene?.id, topology]);

  // Probe the real audio tracks of every media source (cached + deduplicated).
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    probeGeneration.current += 1;
    for (const source of scene.sources) {
      if (source.kind !== 'camera' && source.kind !== 'rtsp') continue;
      setTracksBySource((current) => ownRecordValue(current, source.id) ? current : { ...current, [source.id]: { status: 'loading' } });
      void fetchSourceAudioTracks(source.id, controller.signal, source.kind === 'camera' ? source : undefined).then((value) => {
        if (cancelled) return;
        setTracksBySource((current) => ({ ...current, [source.id]: value }));
        if (value.status === 'available' || (value.status === 'none' && source.audioInputs !== undefined)) {
          // A saved schema 6 selection wins; otherwise the first real track is
          // selected by default and multi-select keeps the others available.
          setSelection((current) => {
            if (ownRecordValue(current, source.id)) return current;
            return { ...current, [source.id]: initialTrackSelection(source, value.status === 'available' ? value.tracks : []) };
          });
        }
      });
    }
    return () => { cancelled = true; probeGeneration.current += 1; controller.abort(); };
  }, [scene.id, sourceIds, studio.revision, reloadGeneration]);

  // Keep the mixer and the audio-only WHEP channels in sync with the selection.
  useEffect(() => {
    const activeSources = new Set(nativeForeground && localPlayback ? scene.sources.map((source) => source.id) : []);
    for (const [key, entry] of [...channels.current]) {
      const [sourceId, index] = key.split('#');
      const probed = ownRecordValue(tracksBySource, sourceId);
      if (activeSources.has(sourceId) && probed?.status === 'available' &&
          probed.tracks.some((track) => track.index === Number(index)) && ownRecordValue(selection, sourceId)?.selected.includes(Number(index))) continue;
      entry.connection.close();
      entry.element.srcObject = null;
      entry.element.remove();
      mixer.unbindTrack(sourceId, Number(index));
      channels.current.delete(key);
    }
    for (const [sourceId, state] of Object.entries(selection)) {
      if (!activeSources.has(sourceId)) continue;
      const probed = ownRecordValue(tracksBySource, sourceId);
      const tracks = probed?.status === 'available' ? probed.tracks : [];
      const selections: DirectAudioTrackSelection[] = state.selected.map((index) => ({
        index, gain: state.gain[index] ?? 1, muted: state.muted[index] ?? false,
      }));
      mixer.configureTracks(sourceId, selections);
      for (const index of state.selected) {
        const track = tracks.find((candidate) => candidate.index === index);
        if (!track) continue;
        const key = `${sourceId}#${index}`;
        if (channels.current.has(key)) continue;
        // The video element stays muted by the mixer, so a multi-track source
        // never double-plays: audio arrives only through these channels.
        const element = document.createElement('audio');
        element.autoplay = true;
        element.muted = true;
        element.dataset.audioTrack = key;
        element.style.display = 'none';
        document.body.appendChild(element);
        const connection = connectAudioTrack(track,
          (channelState) => setChannelStates((current) => ({ ...current, [key]: channelState })),
          (stream) => {
            element.srcObject = stream;
            void element.play().catch(() => undefined);
            mixer.bindTrack(sourceId, index, stream);
          });
        channels.current.set(key, { element, connection });
      }
      for (const [key, entry] of [...channels.current]) {
        const [owner, indexText] = key.split('#');
        if (owner !== sourceId || state.selected.includes(Number(indexText))) continue;
        entry.connection.close();
        mixer.unbindTrack(sourceId, Number(indexText));
        entry.element.remove();
        channels.current.delete(key);
      }
    }
  }, [scene.id, sourceIds, selection, tracksBySource, mixer, nativeForeground, localPlayback]);

  useEffect(() => {
    const open = channels.current;
    return () => {
      for (const [key, entry] of open) {
        entry.connection.close();
        entry.element.remove();
        const [sourceId, index] = key.split('#');
        mixer.unbindTrack(sourceId, Number(index));
      }
      open.clear();
    };
  }, [mixer]);

  const meterBySource = useMemo(() => new Map(snapshot.sources.map((value) => [value.sourceId, value])), [snapshot]);
  if (!scene) return <section className="page-panel"><p>当前没有可用 Scene。</p></section>;
  const update = (sourceId: string, change: Partial<SceneSource>) => {
    if (saving || conflict) return;
    const base = pending ?? studio;
    setPending({ ...base, scenes: base.scenes.map((candidate) => candidate.id !== scene.id ? candidate : {
      ...candidate, sources: candidate.sources.map((source) => source.id === sourceId ? { ...source, ...change } as SceneSource : source),
    }) });
  };
  const updateSelection = (sourceId: string, change: (current: TrackSelection) => TrackSelection) => {
    if (saving || conflict) return;
    // Track-only edits must retain the same If-Match base as master edits.
    setPending((current) => current ?? studio);
    setAudioDirty(true);
    setSelection((current) => {
      const fallback: TrackSelection = { selected: [], gain: {}, muted: {}, offset: {}, mode: 'merged' };
      return { ...current, [sourceId]: change(ownRecordValue(current, sourceId) ?? fallback) };
    });
  };
  const reprobe = async (sourceId: string) => {
    const generation = probeGeneration.current;
    const source = scene.sources.find((candidate) => candidate.id === sourceId);
    invalidateSourceAudioTracks(sourceId);
    setChannelStates({});
    setTracksBySource((current) => ({ ...current, [sourceId]: { status: 'loading' } }));
    try {
      if (source?.kind === 'camera') {
        const result = await probeSourceProfile(source.cameraId, source.profileId);
        if (result.profile.probeState === 'failed') throw new Error('probe_failed');
      }
      const value = await fetchSourceAudioTracks(sourceId, undefined, source?.kind === 'camera' ? source : undefined);
      if (generation !== probeGeneration.current) return;
      setTracksBySource((current) => ({ ...current, [sourceId]: value }));
      if (value.status === 'available' || (value.status === 'none' && source?.audioInputs !== undefined)) {
        setSelection((current) => ownRecordValue(current, sourceId) ? current
          : { ...current, [sourceId]: initialTrackSelection(source, value.status === 'available' ? value.tracks : []) });
      }
    } catch {
      if (generation === probeGeneration.current) setTracksBySource((current) => ({ ...current,
        [sourceId]: { status: 'unavailable', reason: 'probe_failed' } }));
    }
  };
  const withAudioInputs = (base: StudioDocument): StudioDocument => ({
    ...base,
    scenes: base.scenes.map((candidate) => candidate.id !== scene.id ? candidate : {
      ...candidate,
      sources: candidate.sources.map((source) => {
        const state = ownRecordValue(selection, source.id);
        if (!state) return source;
        // Empty selection means "this source adds no audio"; otherwise the
        // legacy audioTrack mirrors the first input for older readers/engines.
        const audioInputs = state.selected.map((index) => ({ track: index,
          gain: state.gain[index] ?? 1, muted: state.muted[index] ?? false,
          syncOffsetMs: state.offset[index] ?? 0 }));
        // audioTrack stays the user's output bus: selecting input tracks must
        // never rewrite it.
        return { ...source, audioInputs } as SceneSource;
      }),
    }),
  });
  const commit = async () => {
    if (saving || conflict) return;
    const owner = requestOwner.current;
    setSaving(true); setError('');
    try {
      const candidate = withAudioInputs(pending ?? studio);
      const committed = await withRequestTimeout(10000, (signal) => replaceStudio(candidate, signal), owner.signal);
      if (owner.signal.aborted) return;
      if (latestStudio.current.revision > committed.revision) {
        setConflict(true);
        setError('保存期间服务器配置再次更新。请重新载入最新配置后核对。');
        return;
      }
      setPending(null);
      setAudioDirty(false);
      setConflict(false); setError('');
      onCommitted(committed);
    }
    catch (reason) {
      if (owner.signal.aborted) return;
      if (reason instanceof DOMException && reason.name === 'TimeoutError') {
        setConflict(true);
        setError('保存结果尚未确认，请重新载入核对；当前修改已保留。');
        return;
      }
      if (reason instanceof ControlApiError && reason.status === 412) setConflict(true);
      setError(reason instanceof Error ? reason.message : '音频配置保存失败');
    }
    finally { if (!owner.signal.aborted) setSaving(false); }
  };
  const reload = async () => {
    if (saving) return;
    const owner = requestOwner.current;
    setSaving(true);
    try {
      const current = await withRequestTimeout(8000, fetchStudio, owner.signal);
      if (owner.signal.aborted) return;
      setPending(null); setAudioDirty(false); setSelection({}); setChannelStates({});
      setConflict(false); setError('');
      setReloadGeneration((generation) => generation + 1);
      onCommitted(current);
    } catch (reason) {
      if (owner.signal.aborted) return;
      setError(reason instanceof Error ? reason.message : '重新载入失败，当前修改已保留。');
    } finally { if (!owner.signal.aborted) setSaving(false); }
  };
  return <section className="audio-workspace page-panel">
    <header className="page-heading"><div><span className="eyebrow">Per-source audio</span><h1>音频工作台</h1><p>仅展示含音轨的源。Direct 按真实音轨在浏览器本地测量，每条选中音轨使用独立 audio-only 通道；Composite 仅在 libobs 返回真实电平时显示数值。多轨支持多选、合并/独立与逐轨电平。</p></div>
      <div className="audio-actions"><select aria-label="Scene" value={scene.id} disabled={dirty || saving || conflict}
        title={dirty ? '先保存或放弃音频修改，再切换场景' : undefined}
        onChange={(event) => { setSelection({}); setTracksBySource({}); setChannelStates({}); setSceneId(event.target.value); }}>{studio.scenes.map((value) => <option value={value.id} key={value.id}>{value.name}</option>)}</select>
        <button type="button" className={topology === 'direct' ? 'active' : ''} onClick={() => setTopology('direct')}>Direct</button>
        <button type="button" className={topology === 'composite' ? 'active' : ''} onClick={() => setTopology('composite')}>Composite</button>
        <button type="button" disabled={!localPlayback} onClick={() => window.dispatchEvent(new Event('webobs:audio-monitor-enable'))}>启用本地监听</button>
        <button type="button" onClick={() => window.dispatchEvent(new Event('webobs:audio-monitor-disable'))}>静音监听</button>
        <button className="primary-button" type="button" disabled={!dirty || saving || conflict} onClick={() => void commit()}>{saving ? '保存中…' : '保存音频配置'}</button>
        {(dirty || conflict) && <button type="button" disabled={saving} onClick={() => void reload()}>放弃修改并重新载入</button>}</div></header>
    {error && <div className="alert conflict-alert">{error}</div>}
    {localPlayback ? <div className="audio-monitor-preview"><DirectPreview compact audioWorkspace scene={scene} /></div>
      : <p role="status">声音配置在此编辑，实时监听与画面由 WebOBS Wall 原生窗口提供。</p>}
    {scene.sources.some((source) => ownRecordValue(tracksBySource, source.id)?.status === 'none') && <p role="status">已确认无音轨：{scene.sources.filter((source) => ownRecordValue(tracksBySource, source.id)?.status === 'none').map((source) => source.name).join('、')}。这些来源不显示音频控制。</p>}
    <div className="audio-mixer-head"><span>来源 / Profile</span><span>电平</span><span>静音 / 音量</span><span>监听 / 同步</span><span>音轨</span></div>
    <fieldset className="audio-mixer-list" disabled={saving || conflict} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>{scene.sources.map((source) => {
      const meter = meterBySource.get(source.id);
      const cameraProfile = source.kind === 'camera' ? `${source.cameraId} / ${source.profileId}` : source.kind;
      const probed = ownRecordValue(tracksBySource, source.id);
      const apiTracks = probed?.status === 'available' ? probed.tracks : [];
      const trackState = probed
        ? (probed.status === 'available' ? 'available'
          : probed.status === 'none' ? 'none'
            : probed.status === 'loading' ? 'loading' : 'unprobed')
        : sourceAudioTrackState({ kind: source.kind, liveAudioTracks: meter?.audioTracks, streamBound: meter?.streamBound });
      const state = ownRecordValue(selection, source.id);
      const selected = state?.selected ?? source.audioInputs?.map((input) => input.track) ?? [];
      const missing = selected.filter((index) => !apiTracks.some((track) => track.index === index));
      // Hide confirmed video-only sources unless a saved track needs attention.
      if (trackState === 'none' && selected.length === 0) return null;
      const mode = state?.mode ?? 'merged';
      return <article className="audio-channel" key={source.id}>
        {(trackState === 'available' || trackState === 'none') && missing.length > 0 && <div className="audio-track-missing" role="alert" style={{ gridColumn: '1 / -1' }}>
          <span>已选音轨 {missing.map((index) => index + 1).join('、')} 当前不可用，配置已保留。</span>
          <button type="button" onClick={() => updateSelection(source.id, (current) => ({ ...current,
            selected: current.selected.filter((index) => !missing.includes(index)),
          }))}>移除缺失音轨</button>
        </div>}
        <div><strong>{source.name}</strong><small>{cameraProfile}</small><span>{!localPlayback ? '原生宿主配置' : topology === 'direct' ? 'Browser Web Audio' : 'libobs Composite'}</span></div>
        {trackState === 'unprobed'
            ? <div className="audio-track-missing"><span role="status">{probed?.status === 'unavailable' ? '音轨探测失败，请检查源连接、VPN 和访问权限后重试。' : '音频轨道待探测'}</span><button type="button" onClick={() => void reprobe(source.id)}>重新探测</button></div>
            : trackState === 'loading'
              ? <div className="audio-track-missing">音轨探测中…</div>
              : <>
                <div className="vu-section">
                  <div className="vu-track"><i style={{ width: `${meterWidth(mode === 'merged' ? meter?.merged?.rmsDbfs : meter?.rmsDbfs)}%` }} /></div>
                  <span>{mode === 'merged' ? '合并' : '独立'} RMS {dbLabel(mode === 'merged' ? meter?.merged?.rmsDbfs : meter?.rmsDbfs)}</span>
                  <span>Peak {dbLabel(mode === 'merged' ? meter?.merged?.peakDbfs : meter?.peakDbfs)}</span>
                  <button type="button" className="audio-level-mode" onClick={() => updateSelection(source.id, (current) => ({ ...current, mode: current.mode === 'merged' ? 'independent' : 'merged' }))}>{mode === 'merged' ? '切换独立电平' : '切换合并电平'}</button>
                </div>
                <div className="audio-track-list">{apiTracks.map((track) => {
                  const selected = state?.selected.includes(track.index) ?? false;
                  const key = `${source.id}#${track.index}`;
                  const channel = ownRecordValue(channelStates, key);
                  const trackMeter = meter?.independent.find((value) => value.trackIndex === track.index);
                  return <label className={`audio-track ${selected ? 'selected' : ''}`} key={track.index}>
                    <input type="checkbox" checked={selected} onChange={(event) => updateSelection(source.id, (current) => ({
                      ...current,
                      selected: event.target.checked
                        ? [...current.selected, track.index].sort((left, right) => left - right)
                        : current.selected.filter((value) => value !== track.index),
                    }))} />{trackLabel(track)}
                    {selected && <span className="audio-track-state">{!localPlayback ? '浏览器试听关闭' : channel ?? '连接中'}{localPlayback && mode === 'independent' && trackMeter ? ` · ${dbLabel(trackMeter.rmsDbfs)}` : ''}</span>}
                  </label>;
                })}</div>
                <div className="audio-track-controls">{apiTracks.filter((track) => state?.selected.includes(track.index)).map((track) => <div className="audio-track-control" key={track.index}>
                  <span>{track.title || track.language || `轨道 ${track.index + 1}`}</span>
                  <label><input type="checkbox" checked={state?.muted[track.index] ?? false} onChange={(event) => updateSelection(source.id, (current) => ({ ...current, muted: { ...current.muted, [track.index]: event.target.checked } }))} />静音</label>
                  <label>增益 <input type="range" min="0" max="1" step="0.01" value={state?.gain[track.index] ?? 1} onChange={(event) => updateSelection(source.id, (current) => ({ ...current, gain: { ...current.gain, [track.index]: Number(event.target.value) } }))} /> {Math.round((state?.gain[track.index] ?? 1) * 100)}%</label>
                  <label>偏移 <input type="number" min="-10000" max="10000" step="10" aria-label={`轨道 ${track.index + 1} 同步偏移`} value={state?.offset[track.index] ?? 0} onChange={(event) => updateSelection(source.id, (current) => ({ ...current, offset: { ...current.offset, [track.index]: Number(event.target.value) } }))} /> ms</label>
                </div>)}</div>
                <div><label><input type="checkbox" checked={source.muted} onChange={(event) => update(source.id, { muted: event.target.checked })} />来源静音</label><label>音量 <input type="range" min="0" max="1" step="0.01" value={source.volume} onChange={(event) => update(source.id, { volume: Number(event.target.value) })} /> {Math.round(source.volume * 100)}%</label></div>
                <div><select value={source.monitoring} onChange={(event) => update(source.id, { monitoring: event.target.value as AudioMonitoring })}><option value="off">关闭监听</option><option value="monitor-only">仅监听</option><option value="monitor-and-output">监听并输出</option></select><label>偏移 <input type="number" min="-10000" max="10000" value={source.syncOffsetMs} onChange={(event) => update(source.id, { syncOffsetMs: Number(event.target.value) })} /> ms</label></div>
              </>}
      </article>;
    })}</fieldset>
  </section>;
}
