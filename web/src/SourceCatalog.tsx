import { useEffect, useMemo, useState } from 'react';
import CameraRegistry from './CameraRegistry';
import DirectPreview from './DirectPreview';
import {
  batchSourceCatalog, fetchSourceCatalog, patchSourceCatalogItem, probeSourceProfile,
} from './api';
import type { SceneDocument, SourceCatalogItem, SourceCatalogProfile, TransportMode } from './types';

interface PreviewTopology {
  sourceId: string; topology: string; executionOwner: string; mediaTransport: string;
  decoder: string; liveServerMediaExpected: boolean | null; fallbackReason: string;
}

const transportOptions: Record<string, TransportMode[]> = {
  rtsp: ['auto', 'rtsp-tcp', 'rtsp-udp', 'rtsp-udp-multicast'],
  onvif: ['auto', 'rtsp-tcp', 'rtsp-udp', 'rtsp-udp-multicast'],
  mjpeg: ['auto', 'http', 'https'], snapshot: ['auto', 'http', 'https'],
  hls: ['auto', 'http', 'https'], whep: ['auto', 'https'], 'http-flv': ['auto', 'http', 'https'],
};

function previewScene(camera: SourceCatalogItem, profile: SourceCatalogProfile): SceneDocument {
  return {
    schemaVersion: 5, revision: 1, id: `preview-${camera.id}-${profile.id}`, name: `${camera.name} · ${profile.name}`,
    canvas: { width: Math.max(320, profile.width || 1920), height: Math.max(180, profile.height || 1080), backgroundColor: '#05080d' },
    sources: [{ id: 'source-preview', kind: 'camera', name: camera.name, cameraId: camera.id, profileId: profile.id,
      hardwareDecode: camera.hardwareDecode, muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [] }],
    items: [{ id: 'item-preview', sourceId: 'source-preview', x: 0, y: 0,
      width: Math.max(320, profile.width || 1920), height: Math.max(180, profile.height || 1080), scaleMode: 'contain',
      crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: 0, visible: true, locked: true,
      groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' }],
  };
}

function TrackList({ profile }: { profile: SourceCatalogProfile }) {
  return <div className="track-list">{profile.tracks.length === 0
    ? <span className="muted-copy">尚无轨道探测结果</span>
    : profile.tracks.map((track) => <span key={`${track.kind}-${track.index}`}>
      <strong>{track.kind.toUpperCase()} {track.index}</strong>
      {track.codec || 'unknown'}
      {track.kind === 'video' && track.width > 0 ? ` · ${track.width}×${track.height} · ${track.fps || '—'} fps` : ''}
      {track.kind === 'audio' && track.sampleRate > 0 ? ` · ${track.sampleRate} Hz · ${track.channels} ch` : ''}
      {track.bitrateKbps ? ` · ${track.bitrateKbps} kbps` : ''}
    </span>)}</div>;
}

function ProfileEditor({ camera, profile, onChanged, onPreview }: {
  camera: SourceCatalogItem; profile: SourceCatalogProfile;
  onChanged: (value: SourceCatalogItem) => void; onPreview: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const patch = async (change: Record<string, unknown>) => {
    setBusy(true); setError('');
    try { onChanged(await patchSourceCatalogItem(camera.id, camera.revision, { profiles: [{ id: profile.id, ...change }] })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Profile 更新失败'); }
    finally { setBusy(false); }
  };
  const transports = transportOptions[camera.adapter] ?? ['auto'];
  return <article className="catalog-profile">
    <header><div><strong>{profile.name}</strong><span>{profile.role} · {profile.videoCodec || 'unknown'}{profile.audioCodec ? ` + ${profile.audioCodec}` : ''}</span></div>
      <div><button type="button" onClick={onPreview}>独立预览</button><button type="button" disabled={busy} onClick={() => {
        setBusy(true); setError('');
        void probeSourceProfile(camera.id, profile.id).then((value) => onChanged({ ...camera,
          profiles: camera.profiles.map((candidate) => candidate.id === profile.id ? value.profile : candidate) }))
          .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '探测失败')).finally(() => setBusy(false));
      }}>探测轨道</button></div></header>
    <div className="profile-settings">
      <label><span>启用</span><input type="checkbox" checked={profile.enabled} disabled={busy}
        onChange={(event) => void patch({ enabled: event.target.checked })} /></label>
      <label><span>传输</span><select value={profile.transportMode} disabled={busy}
        onChange={(event) => void patch({ transportMode: event.target.value })}>{transports.map((value) => <option key={value}>{value}</option>)}</select></label>
      <label><span>实时码率上限 kbps</span><input type="number" min="32" max="1000000" placeholder="不限制"
        key={`${profile.id}-${profile.liveBitrateCapKbps ?? 'none'}`} defaultValue={profile.liveBitrateCapKbps ?? ''} disabled={busy} onBlur={(event) => {
          const value = event.currentTarget.value === '' ? null : Number(event.currentTarget.value);
          void patch({ liveBitrateCapKbps: value });
        }} /></label>
      <label><span>音频预期</span><select value={profile.audioExpectation} disabled={busy}
        onChange={(event) => void patch({ audioExpectation: event.target.value })}><option value="auto">自动</option><option value="required">必须有</option><option value="disabled">禁用</option></select></label>
    </div>
    <div className="profile-facts"><span>{profile.width || '—'}×{profile.height || '—'}</span><span>{profile.fps || '—'} fps</span><span>{profile.endpointDisplay || '地址已保护'}</span><span>Probe: {profile.probeState}</span></div>
    <TrackList profile={profile} />{error && <p className="inline-error" role="alert">{error}</p>}
  </article>;
}

export default function SourceCatalog() {
  const [items, setItems] = useState<SourceCatalogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState('');
  const [adapter, setAdapter] = useState('');
  const [enabled, setEnabled] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [expanded, setExpanded] = useState<string[]>([]);
  const [preview, setPreview] = useState<{ camera: SourceCatalogItem; profile: SourceCatalogProfile } | null>(null);
  const [showLegacyRegistry, setShowLegacyRegistry] = useState(false);
  const [batchGroup, setBatchGroup] = useState('');
  const [batchTag, setBatchTag] = useState('');
  const [previewTopology, setPreviewTopology] = useState<PreviewTopology | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const reload = () => {
    setLoading(true);
    void fetchSourceCatalog({ q: query, adapter, enabled: enabled === '' ? undefined : enabled === 'true', limit: 256, sort: 'name' })
      .then((value) => { setItems(value.items); setTotal(value.total); setError(''); })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '来源目录不可用'))
      .finally(() => setLoading(false));
  };
  useEffect(reload, [adapter, enabled, query]);
  useEffect(() => {
    const changed = (event: Event) => {
      const detail = (event as CustomEvent<PreviewTopology>).detail;
      if (detail?.sourceId === 'source-preview') setPreviewTopology(detail);
    };
    window.addEventListener('webobs:media-topology', changed);
    return () => window.removeEventListener('webobs:media-topology', changed);
  }, []);
  const selectedItems = useMemo(() => items.filter((item) => selected.includes(item.id)), [items, selected]);
  const replace = (next: SourceCatalogItem) => {
    setItems((current) => current.map((item) => item.id === next.id ? next : item));
    setPreview((current) => current?.camera.id === next.id ? { camera: next,
      profile: next.profiles.find((profile) => profile.id === current.profile.id) ?? current.profile } : current);
  };
  const batch = async (change: Record<string, unknown>) => {
    if (!selectedItems.length) return;
    try {
      const result = await batchSourceCatalog(selectedItems.map((item) => ({ cameraId: item.id, revision: item.revision, ...change })));
      result.items.forEach(replace); setSelected([]); setError('');
    } catch (reason) { setError(reason instanceof Error ? reason.message : '批量更新失败，未修改任何设备'); }
  };
  if (showLegacyRegistry) return <CameraRegistry onBack={() => { setShowLegacyRegistry(false); reload(); }} />;
  return <section className="source-catalog page-panel">
    <header className="page-heading"><div><span className="eyebrow">Camera → Profile → Track</span><h1>设备与来源</h1><p>共 {total} 台；地址仅显示脱敏值，凭据由 Secret 引用保管。</p></div>
      <button className="primary-button" type="button" onClick={() => setShowLegacyRegistry(true)}>添加 / ONVIF 发现</button></header>
    <div className="catalog-toolbar">
      <input aria-label="搜索设备" placeholder="搜索名称、标签或分组" value={query} onChange={(event) => setQuery(event.target.value.slice(0, 128))} />
      <select aria-label="协议筛选" value={adapter} onChange={(event) => setAdapter(event.target.value)}><option value="">全部协议</option>{['onvif','rtsp','whep','hls','mjpeg','snapshot','http-flv','srt','rtp','v4l2'].map((value) => <option key={value}>{value}</option>)}</select>
      <select aria-label="启用状态" value={enabled} onChange={(event) => setEnabled(event.target.value)}><option value="">全部状态</option><option value="true">已启用</option><option value="false">已停用</option></select>
      <button type="button" disabled={!selected.length} onClick={() => void batch({ enabled: true })}>批量启用</button>
      <button type="button" disabled={!selected.length} onClick={() => void batch({ enabled: false })}>批量停用</button>
      <input aria-label="批量移动到分组" maxLength={64} placeholder="批量分组" value={batchGroup}
        onChange={(event) => setBatchGroup(event.target.value)} />
      <button type="button" disabled={!selected.length} onClick={() => void batch({ groupId: batchGroup.trim() })}>移动分组</button>
      <input aria-label="批量增加标签" maxLength={32} placeholder="批量标签" value={batchTag}
        onChange={(event) => setBatchTag(event.target.value)} />
      <button type="button" disabled={!selected.length || !batchTag.trim()} onClick={() => {
        const tag = batchTag.trim();
        void batchSourceCatalog(selectedItems.map((item) => ({ cameraId: item.id, revision: item.revision,
          tags: [...new Set([...item.tags, tag])].slice(0, 32) }))).then((result) => {
          result.items.forEach(replace); setSelected([]); setBatchTag(''); setError('');
        }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '批量标签更新失败'));
      }}>增加标签</button>
      <button type="button" disabled={!selected.length || !batchTag.trim()} onClick={() => {
        const tag = batchTag.trim();
        void batchSourceCatalog(selectedItems.map((item) => ({ cameraId: item.id, revision: item.revision,
          tags: item.tags.filter((value) => value !== tag) }))).then((result) => {
          result.items.forEach(replace); setSelected([]); setBatchTag(''); setError('');
        }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '批量标签更新失败'));
      }}>移除标签</button>
    </div>
    {error && <div className="alert conflict-alert" role="alert">{error}</div>}
    {loading ? <p className="catalog-loading">正在读取 Camera Registry…</p> : <div className="catalog-table" role="table" aria-label="设备与来源">
      <div className="catalog-row catalog-head" role="row"><span /><span>名称 / 类型</span><span>协议 / 地址</span><span>状态</span><span>Profiles / 轨道</span><span>标签 / 分组</span><span>操作</span></div>
      {items.map((camera) => {
        const opened = expanded.includes(camera.id);
        return <div className="catalog-record" key={camera.id}>
          <div className="catalog-row" role="row">
            <input aria-label={`选择 ${camera.name}`} type="checkbox" checked={selected.includes(camera.id)} onChange={(event) => setSelected((value) => event.target.checked ? [...value, camera.id] : value.filter((id) => id !== camera.id))} />
            <span><strong>{camera.name}</strong><small>{camera.kind === 'camera' ? '摄像机' : '网络流'}</small></span>
            <span><strong>{camera.adapter.toUpperCase()}</strong><small>{camera.addressDisplay || '地址已保护'}</small></span>
            <span><i className={`health-dot ${camera.health}`} />{camera.enabled ? camera.health : '已停用'}</span>
            <span>{camera.profileCount} / {camera.trackCount}</span>
            <span><small>{camera.groupId || '未分组'}</small><span className="tag-line">{camera.tags.map((tag) => <i key={tag}>{tag}</i>)}</span></span>
            <span className="row-actions"><button type="button" onClick={() => setExpanded((value) => opened ? value.filter((id) => id !== camera.id) : [...value, camera.id])}>{opened ? '收起' : '详情'}</button>
              <button type="button" onClick={() => void patchSourceCatalogItem(camera.id, camera.revision, { enabled: !camera.enabled }).then(replace).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '更新失败'))}>{camera.enabled ? '停用' : '启用'}</button></span>
          </div>
          {opened && <div className="catalog-details"><div className="device-meta-editor">
            <label>分组<input maxLength={64} defaultValue={camera.groupId} onBlur={(event) => { if (event.currentTarget.value !== camera.groupId) void patchSourceCatalogItem(camera.id, camera.revision, { groupId: event.currentTarget.value }).then(replace); }} /></label>
            <label>标签（逗号分隔）<input defaultValue={camera.tags.join(', ')} onBlur={(event) => { const tags = event.currentTarget.value.split(',').map((value) => value.trim()).filter(Boolean); if (JSON.stringify(tags) !== JSON.stringify(camera.tags)) void patchSourceCatalogItem(camera.id, camera.revision, { tags }).then(replace); }} /></label>
          </div>{camera.profiles.map((profile) => <ProfileEditor key={profile.id} camera={camera} profile={profile} onChanged={replace} onPreview={() => setPreview({ camera, profile })} />)}</div>}
        </div>;
      })}
    </div>}
    {preview && <div className="profile-preview-modal" role="dialog" aria-modal="true" aria-label="独立来源预览"><div className="profile-preview-card">
      <header><div><span className="eyebrow">Profile preview</span><h2>{preview.camera.name} · {preview.profile.name}</h2></div><button type="button" onClick={() => { setPreview(null); setPreviewTopology(null); }}>关闭并释放</button></header>
      <DirectPreview compact scene={previewScene(preview.camera, preview.profile)} />
      <div className="preview-facts"><span>协议 {preview.camera.adapter.toUpperCase()}</span><span>{preview.profile.videoCodec || 'unknown'}</span><span>{preview.profile.audioCodec || '无音频'}</span><span>{preview.profile.width || '—'}×{preview.profile.height || '—'} @ {preview.profile.fps || '—'} fps</span></div>
      <div className="preview-facts" aria-label="媒体执行链">
        <span>Topology {previewTopology?.topology ?? 'checking'}</span>
        <span>{previewTopology?.executionOwner === 'browser' ? 'Camera → Browser' : previewTopology?.executionOwner === 'docker' ? 'Camera → Docker → Browser' : '媒体路径检查中'}</span>
        <span>Decoder {previewTopology?.decoder ?? '—'}</span>
        <span>{previewTopology?.fallbackReason || '无回退'}</span>
      </div>
      <div className="preview-facts" aria-label="设备能力">
        <span>PTZ {preview.camera.deviceCapabilities.ptz ? '支持' : '不支持/未知'}</span>
        <span>快照 {preview.camera.deviceCapabilities.snapshot ? '支持' : '不支持/未知'}</span>
        <span>对讲 {preview.camera.deviceCapabilities.talk ? '支持' : '不支持/未知'}</span>
      </div>
    </div></div>}
  </section>;
}
