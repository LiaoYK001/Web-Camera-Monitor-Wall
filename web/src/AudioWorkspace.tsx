import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchAudioMeters, replaceStudio } from './api';
import DirectPreview from './DirectPreview';
import { connectAudioTrack, type AudioChannelState, type AudioTrackConnection } from './audioTrackChannel';
import { getDirectAudioMixer, type DirectAudioSnapshot, type DirectAudioTrackSelection } from './directAudioMixer';
import { defaultSelectedTracks, fetchSourceAudioTracks, invalidateSourceAudioTracks, type SourceAudioTrack, type SourceAudioTracks } from './sourceAudio';
import { sourceAudioTrackState } from './monitorView';
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
  mode: 'merged' | 'independent';
}

interface ChannelEntry {
  element: HTMLAudioElement;
  connection: AudioTrackConnection;
}

export default function AudioWorkspace({ studio, onCommitted }: { studio: StudioDocument; onCommitted: (studio: StudioDocument) => void }) {
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
  const channels = useRef(new Map<string, ChannelEntry>());
  const mixer = useMemo(() => getDirectAudioMixer(), []);
  const scene = (pending ?? studio).scenes.find((candidate) => candidate.id === sceneId)
    ?? (pending ?? studio).scenes[0];
  const sourceIds = scene ? scene.sources.map((source) => `${source.id}:${source.kind}`).join(',') : '';

  useEffect(() => {
    const receive = (event: Event) => setSnapshot((event as CustomEvent<DirectAudioSnapshot>).detail);
    window.addEventListener('webobs:direct-audio-meters', receive);
    return () => window.removeEventListener('webobs:direct-audio-meters', receive);
  }, []);
  useEffect(() => { setPending(null); }, [studio.revision]);
  useEffect(() => {
    if (topology !== 'composite') return undefined;
    const controller = new AbortController();
    const poll = () => void fetchAudioMeters(scene.id, 'composite', controller.signal)
      .then((value) => setSnapshot((current) => ({ ...current,
        // Composite meters come from libobs and are per source, not per track.
        sources: value.sources.map((source) => ({ ...source, merged: null, independent: [] })) })))
      .catch(() => undefined);
    poll();
    const timer = window.setInterval(poll, 250);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [scene.id, topology]);

  // Probe the real audio tracks of every media source (cached + deduplicated).
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    for (const source of scene.sources) {
      if (source.kind !== 'camera' && source.kind !== 'rtsp') continue;
      setTracksBySource((current) => current[source.id] ? current : { ...current, [source.id]: { status: 'loading' } });
      void fetchSourceAudioTracks(source.id, controller.signal).then((value) => {
        if (cancelled) return;
        setTracksBySource((current) => ({ ...current, [source.id]: value }));
        if (value.status === 'available') {
          // A saved schema 6 selection wins; otherwise the first real track is
          // selected by default and multi-select keeps the others available.
          setSelection((current) => {
            if (current[source.id]) return current;
            const saved = source.audioInputs?.filter((input) => value.tracks.some((track) => track.index === input.track)) ?? [];
            const gain: Record<number, number> = {};
            const muted: Record<number, boolean> = {};
            for (const input of saved) { gain[input.track] = input.gain; muted[input.track] = input.muted; }
            const selected = saved.length > 0
              ? saved.map((input) => input.track).sort((left, right) => left - right)
              : defaultSelectedTracks(value.tracks);
            return { ...current, [source.id]: { selected, gain, muted, mode: 'merged' } };
          });
        }
      });
    }
    return () => { cancelled = true; controller.abort(); };
  }, [scene.id, sourceIds]);

  // Keep the mixer and the audio-only WHEP channels in sync with the selection.
  useEffect(() => {
    for (const [sourceId, state] of Object.entries(selection)) {
      const tracks = tracksBySource[sourceId]?.status === 'available' ? tracksBySource[sourceId].tracks : [];
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
  }, [selection, tracksBySource, mixer]);

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
    const base = pending ?? studio;
    setPending({ ...base, scenes: base.scenes.map((candidate) => candidate.id !== scene.id ? candidate : {
      ...candidate, sources: candidate.sources.map((source) => source.id === sourceId ? { ...source, ...change } as SceneSource : source),
    }) });
  };
  const updateSelection = (sourceId: string, change: (current: TrackSelection) => TrackSelection) => {
    setAudioDirty(true);
    setSelection((current) => {
      const fallback: TrackSelection = { selected: [], gain: {}, muted: {}, mode: 'merged' };
      return { ...current, [sourceId]: change(current[sourceId] ?? fallback) };
    });
  };
  const reprobe = (sourceId: string) => {
    invalidateSourceAudioTracks(sourceId);
    setChannelStates({});
    setTracksBySource((current) => ({ ...current, [sourceId]: { status: 'loading' } }));
    void fetchSourceAudioTracks(sourceId).then((value) => {
      setTracksBySource((current) => ({ ...current, [sourceId]: value }));
      if (value.status === 'available') {
        updateSelection(sourceId, (current) => ({ ...current, selected: current.selected.length > 0 ? current.selected : defaultSelectedTracks(value.tracks) }));
      }
    });
  };
  const withAudioInputs = (base: StudioDocument): StudioDocument => ({
    ...base,
    scenes: base.scenes.map((candidate) => candidate.id !== scene.id ? candidate : {
      ...candidate,
      sources: candidate.sources.map((source) => {
        const state = selection[source.id];
        if (!state) return source;
        // Empty selection means "this source adds no audio"; otherwise the
        // legacy audioTrack mirrors the first input for older readers/engines.
        const audioInputs = state.selected
          .map((index) => ({ track: index, gain: state.gain[index] ?? 1, muted: state.muted[index] ?? false }));
        return { ...source, audioInputs,
          audioTrack: audioInputs.length > 0 ? audioInputs[0].track + 1 : source.audioTrack } as SceneSource;
      }),
    }),
  });
  const commit = async () => {
    setSaving(true); setError('');
    try {
      const committed = await replaceStudio(withAudioInputs(pending ?? studio));
      setPending(null);
      setAudioDirty(false);
      onCommitted(committed);
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : '音频配置保存失败'); }
    finally { setSaving(false); }
  };
  return <section className="audio-workspace page-panel">
    <header className="page-heading"><div><span className="eyebrow">Per-source audio</span><h1>音频工作台</h1><p>Direct 按真实音轨在浏览器本地测量，每条选中音轨使用独立 audio-only 通道；Composite 仅在 libobs 返回真实电平时显示数值。</p></div>
      <div className="audio-actions"><select aria-label="Scene" value={scene.id} onChange={(event) => setSceneId(event.target.value)}>{studio.scenes.map((value) => <option value={value.id} key={value.id}>{value.name}</option>)}</select>
        <button type="button" className={topology === 'direct' ? 'active' : ''} onClick={() => setTopology('direct')}>Direct</button>
        <button type="button" className={topology === 'composite' ? 'active' : ''} onClick={() => setTopology('composite')}>Composite</button>
        <button type="button" onClick={() => window.dispatchEvent(new Event('webobs:audio-monitor-enable'))}>启用本地监听</button>
        <button type="button" onClick={() => window.dispatchEvent(new Event('webobs:audio-monitor-disable'))}>静音监听</button>
        <button className="primary-button" type="button" disabled={(!pending && !audioDirty) || saving} onClick={() => void commit()}>{saving ? '保存中…' : '保存音频配置'}</button></div></header>
    {error && <div className="alert conflict-alert">{error}</div>}
    <div className="audio-monitor-preview"><DirectPreview compact scene={scene} /></div>
    <div className="audio-mixer-head"><span>来源 / Profile</span><span>电平</span><span>静音 / 音量</span><span>监听 / 同步</span><span>音轨</span></div>
    <div className="audio-mixer-list">{scene.sources.map((source) => {
      const meter = topology === 'direct' ? meterBySource.get(source.id) : undefined;
      const cameraProfile = source.kind === 'camera' ? `${source.cameraId} / ${source.profileId}` : source.kind;
      const probed = tracksBySource[source.id];
      const apiTracks = probed?.status === 'available' ? probed.tracks : [];
      const trackState = probed
        ? (probed.status === 'available' ? 'available'
          : probed.status === 'none' ? 'none'
            : probed.status === 'loading' ? 'loading' : 'unprobed')
        : sourceAudioTrackState({ kind: source.kind, liveAudioTracks: meter?.audioTracks, streamBound: meter?.streamBound });
      const state = selection[source.id];
      const mode = state?.mode ?? 'merged';
      return <article className={`audio-channel ${trackState === 'none' ? 'no-audio' : ''}`} key={source.id}>
        <div><strong>{source.name}</strong><small>{cameraProfile}</small><span>{topology === 'direct' ? 'Browser Web Audio' : 'libobs Composite'}</span></div>
        {trackState === 'none'
          ? <div className="audio-track-missing">该源没有音频轨道，无需电平 / 音量 / 监听设置。</div>
          : trackState === 'unprobed'
            ? <div className="audio-track-missing">音频轨道待探测<button type="button" onClick={() => reprobe(source.id)}>重新探测</button></div>
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
                  const channel = channelStates[key];
                  const trackMeter = meter?.independent.find((value) => value.trackIndex === track.index);
                  return <label className={`audio-track ${selected ? 'selected' : ''}`} key={track.index}>
                    <input type="checkbox" checked={selected} onChange={(event) => updateSelection(source.id, (current) => ({
                      ...current,
                      selected: event.target.checked
                        ? [...current.selected, track.index].sort((left, right) => left - right)
                        : current.selected.filter((value) => value !== track.index),
                    }))} />{trackLabel(track)}
                    {selected && <span className="audio-track-state">{channel ?? '连接中'}{mode === 'independent' && trackMeter ? ` · ${dbLabel(trackMeter.rmsDbfs)}` : ''}</span>}
                  </label>;
                })}</div>
                <div className="audio-track-controls">{apiTracks.filter((track) => state?.selected.includes(track.index)).map((track) => <div className="audio-track-control" key={track.index}>
                  <span>{track.title || track.language || `轨道 ${track.index + 1}`}</span>
                  <label><input type="checkbox" checked={state?.muted[track.index] ?? false} onChange={(event) => updateSelection(source.id, (current) => ({ ...current, muted: { ...current.muted, [track.index]: event.target.checked } }))} />静音</label>
                  <label>增益 <input type="range" min="0" max="1" step="0.01" value={state?.gain[track.index] ?? 1} onChange={(event) => updateSelection(source.id, (current) => ({ ...current, gain: { ...current.gain, [track.index]: Number(event.target.value) } }))} /> {Math.round((state?.gain[track.index] ?? 1) * 100)}%</label>
                </div>)}</div>
                <div><label><input type="checkbox" checked={source.muted} onChange={(event) => update(source.id, { muted: event.target.checked })} />来源静音</label><label>音量 <input type="range" min="0" max="1" step="0.01" value={source.volume} onChange={(event) => update(source.id, { volume: Number(event.target.value) })} /> {Math.round(source.volume * 100)}%</label></div>
                <div><select value={source.monitoring} onChange={(event) => update(source.id, { monitoring: event.target.value as AudioMonitoring })}><option value="off">关闭监听</option><option value="monitor-only">仅监听</option><option value="monitor-and-output">监听并输出</option></select><label>偏移 <input type="number" min="-10000" max="10000" value={source.syncOffsetMs} onChange={(event) => update(source.id, { syncOffsetMs: Number(event.target.value) })} /> ms</label></div>
              </>}
      </article>;
    })}</div>
  </section>;
}
