import { useEffect, useMemo, useState } from 'react';
import { fetchAudioMeters, replaceStudio } from './api';
import DirectPreview from './DirectPreview';
import type { DirectAudioSnapshot } from './directAudioMixer';
import type { AudioMonitoring, SceneSource, StudioDocument } from './types';

const dbLabel = (value: number | null | undefined) => value === null || value === undefined ? '—' : `${value.toFixed(1)} dBFS`;
const meterWidth = (value: number | null | undefined) => value === null || value === undefined ? 0 : Math.max(0, Math.min(100, (value + 120) / 1.2));

export default function AudioWorkspace({ studio, onCommitted }: { studio: StudioDocument; onCommitted: (studio: StudioDocument) => void }) {
  const [sceneId, setSceneId] = useState(studio.previewSceneId);
  const [topology, setTopology] = useState<'direct' | 'composite'>('direct');
  const [snapshot, setSnapshot] = useState<DirectAudioSnapshot>({ state: 'disabled', inputCount: 0, level: 0, sources: [] });
  const [pending, setPending] = useState<StudioDocument | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const scene = (pending ?? studio).scenes.find((candidate) => candidate.id === sceneId)
    ?? (pending ?? studio).scenes[0];
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
      .then((value) => setSnapshot((current) => ({ ...current, sources: value.sources })))
      .catch(() => undefined);
    poll();
    const timer = window.setInterval(poll, 250);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [scene.id, topology]);
  const meterBySource = useMemo(() => new Map(snapshot.sources.map((value) => [value.sourceId, value])), [snapshot]);
  if (!scene) return <section className="page-panel"><p>当前没有可用 Scene。</p></section>;
  const update = (sourceId: string, change: Partial<SceneSource>) => {
    const base = pending ?? studio;
    setPending({ ...base, scenes: base.scenes.map((candidate) => candidate.id !== scene.id ? candidate : {
      ...candidate, sources: candidate.sources.map((source) => source.id === sourceId ? { ...source, ...change } as SceneSource : source),
    }) });
  };
  const commit = async () => {
    if (!pending) return;
    setSaving(true); setError('');
    try { const committed = await replaceStudio(pending); setPending(null); onCommitted(committed); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '音频配置保存失败'); }
    finally { setSaving(false); }
  };
  return <section className="audio-workspace page-panel">
    <header className="page-heading"><div><span className="eyebrow">Per-source audio</span><h1>音频工作台</h1><p>Direct 在浏览器本地测量；Composite 仅在 libobs 返回真实电平时显示数值。</p></div>
      <div className="audio-actions"><select aria-label="Scene" value={scene.id} onChange={(event) => setSceneId(event.target.value)}>{studio.scenes.map((value) => <option value={value.id} key={value.id}>{value.name}</option>)}</select>
        <button type="button" className={topology === 'direct' ? 'active' : ''} onClick={() => setTopology('direct')}>Direct</button>
        <button type="button" className={topology === 'composite' ? 'active' : ''} onClick={() => setTopology('composite')}>Composite</button>
        <button type="button" onClick={() => window.dispatchEvent(new Event('webobs:audio-monitor-enable'))}>启用本地监听</button>
        <button type="button" onClick={() => window.dispatchEvent(new Event('webobs:audio-monitor-disable'))}>静音监听</button>
        <button className="primary-button" type="button" disabled={!pending || saving} onClick={() => void commit()}>{saving ? '保存中…' : '保存音频配置'}</button></div></header>
    {error && <div className="alert conflict-alert">{error}</div>}
    <div className="audio-monitor-preview"><DirectPreview compact scene={scene} /></div>
    <div className="audio-mixer-head"><span>来源 / Profile</span><span>电平</span><span>静音 / 音量</span><span>监听 / 同步</span><span>轨道</span></div>
    <div className="audio-mixer-list">{scene.sources.map((source) => {
      const meter = topology === 'direct' ? meterBySource.get(source.id) : undefined;
      const cameraProfile = source.kind === 'camera' ? `${source.cameraId} / ${source.profileId}` : source.kind;
      return <article className="audio-channel" key={source.id}>
        <div><strong>{source.name}</strong><small>{cameraProfile}</small><span>{topology === 'direct' ? 'Browser Web Audio' : 'libobs Composite'}</span></div>
        <div className="vu-section"><div className="vu-track"><i style={{ width: `${meterWidth(meter?.rmsDbfs)}%` }} /></div><span>RMS {dbLabel(meter?.rmsDbfs)}</span><span>Peak {dbLabel(meter?.peakDbfs)}</span></div>
        <div><label><input type="checkbox" checked={source.muted} onChange={(event) => update(source.id, { muted: event.target.checked })} />静音</label><label>音量 <input type="range" min="0" max="1" step="0.01" value={source.volume} onChange={(event) => update(source.id, { volume: Number(event.target.value) })} /> {Math.round(source.volume * 100)}%</label></div>
        <div><select value={source.monitoring} onChange={(event) => update(source.id, { monitoring: event.target.value as AudioMonitoring })}><option value="off">关闭监听</option><option value="monitor-only">仅监听</option><option value="monitor-and-output">监听并输出</option></select><label>偏移 <input type="number" min="-10000" max="10000" value={source.syncOffsetMs} onChange={(event) => update(source.id, { syncOffsetMs: Number(event.target.value) })} /> ms</label></div>
        <div><label>输出 <select value={source.audioTrack} onChange={(event) => update(source.id, { audioTrack: Number(event.target.value) })}>{[1,2,3,4,5,6].map((value) => <option value={value} key={value}>{value}</option>)}</select></label><span className={meter ? 'meter-ready' : 'meter-unavailable'}>{meter ? '实时' : '— 不可测'}</span></div>
      </article>;
    })}</div>
  </section>;
}
