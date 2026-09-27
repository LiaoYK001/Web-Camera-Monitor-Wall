import { useEffect, useMemo, useRef, useState } from 'react';
import CameraRegistry from './CameraRegistry';
import DirectPreview from './DirectPreview';
import Modal from './Modal';
import {
  batchSourceCatalog, createCamera, fetchLegacySourceImport, fetchSourceCatalog, importLegacySources, patchSourceCatalogItem, probeSourceProfile,
} from './api';
import { parseBulkSourceLines } from './bulkSourceImport';
import type { SceneDocument, SourceCatalogItem, SourceCatalogProfile, TransportMode } from './types';
import type { LegacySourceImportItem } from './api';

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
          profiles: camera.profiles.map((candidate) => candidate.id === profile.id
            ? { ...candidate, ...value.profile, endpointDisplay: candidate.endpointDisplay } : candidate) }))
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
      {profile.endpointDisplay?.startsWith('http://') && <label className="insecure-http-opt-in"><span>允许 HTTP 明文媒体</span>
        <input type="checkbox" checked={profile.allowInsecureHttp} disabled={busy}
          onChange={(event) => void patch({ allowInsecureHttp: event.target.checked })} />
        <small>仅允许 Docker Gateway/NVR 拉取；HTTPS 浏览器不会将其视为真直连。</small></label>}
    </div>
    <div className="profile-facts"><span>{profile.width || '—'}×{profile.height || '—'}</span><span>{profile.fps || '—'} fps</span><span>{profile.endpointDisplay || '地址已保护'}</span><span>Probe: {profile.probeState}</span></div>
    <TrackList profile={profile} />{error && <p className="inline-error" role="alert">{error}</p>}
  </article>;
}

export default function SourceCatalog() {
  const [items, setItems] = useState<SourceCatalogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [reloadVersion, setReloadVersion] = useState(0);
  const [batchBusy, setBatchBusy] = useState(false);
  const appliedQuery = useRef('');
  const pageSize = 24;
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
  const [legacyItems, setLegacyItems] = useState<LegacySourceImportItem[]>([]);
  const [legacyRevision, setLegacyRevision] = useState(0);
  const [legacyBusy, setLegacyBusy] = useState(false);
  const [showBulkImport, setShowBulkImport] = useState(false);
  const [bulkText, setBulkText] = useState('');
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkMessage, setBulkMessage] = useState('');
  const [bulkProgress, setBulkProgress] = useState({ done: 0, total: 0 });
  const stopBulk = useRef(false);
  useEffect(() => () => { stopBulk.current = true; }, []);
  const reload = () => setReloadVersion((value) => value + 1);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    const timer = window.setTimeout(() => {
      appliedQuery.current = query;
      void fetchSourceCatalog({ q: query, adapter, enabled: enabled === '' ? undefined : enabled === 'true', page, limit: pageSize, sort: 'name' }, controller.signal)
        .then((value) => {
          if (controller.signal.aborted) return;
          setItems(value.items); setTotal(value.total); setError('');
          setPage((current) => Math.min(current, Math.max(1, Math.ceil(value.total / pageSize))));
        })
        .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '来源目录不可用'); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, query === appliedQuery.current ? 0 : 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [adapter, enabled, query, page, reloadVersion]);
  useEffect(() => { setSelected([]); setExpanded([]); }, [adapter, enabled, query, page]);
  const resetFilters = () => { setQuery(''); setAdapter(''); setEnabled(''); setPage(1); };
  const previewDocument = useMemo(() => preview ? previewScene(preview.camera, preview.profile) : null, [preview]);
  const inspectLegacy = () => {
    setLegacyBusy(true);
    void fetchLegacySourceImport().then((value) => { setLegacyItems(value.items); setLegacyRevision(value.baseRevision); setError(''); }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '旧来源检查失败')).finally(() => setLegacyBusy(false));
  };
  const importReadyLegacy = () => {
    const ids = legacyItems.filter((item) => item.state === 'ready_to_import').map((item) => item.sourceId);
    if (!ids.length) return;
    setLegacyBusy(true);
    void importLegacySources(ids, legacyRevision).then(() => { inspectLegacy(); reload(); }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '旧来源导入失败')).finally(() => setLegacyBusy(false));
  };
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
  const batch = async (change: Record<string, unknown> | ((item: SourceCatalogItem) => Record<string, unknown>)) => {
    if (!selectedItems.length || batchBusy) return;
    setBatchBusy(true); setError('');
    try {
      const result = await batchSourceCatalog(selectedItems.map((item) => ({ cameraId: item.id, revision: item.revision,
        ...(typeof change === 'function' ? change(item) : change) })));
      result.items.forEach(replace); setSelected([]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '批量更新失败，请刷新后重试'); }
    finally { setBatchBusy(false); }
  };
  const updateCamera = async (camera: SourceCatalogItem, change: Record<string, unknown>) => {
    try { replace(await patchSourceCatalogItem(camera.id, camera.revision, change)); setError(''); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '更新失败，请刷新后重试'); }
  };
  const parsedBulk = useMemo(() => parseBulkSourceLines(bulkText), [bulkText]);
  const importBulk = async () => {
    if (!parsedBulk.entries.length || parsedBulk.errors.length) return;
    setBulkBusy(true); setBulkMessage(''); stopBulk.current = false;
    const submittedText = bulkText;
    setBulkProgress({ done: 0, total: parsedBulk.entries.length });
    const failures: string[] = [];
    const failedLines = new Set<number>();
    let completed = 0;
    const retainedLines = new Set(parsedBulk.entries.map((entry) => entry.line));
    for (const entry of parsedBulk.entries) {
      if (stopBulk.current) break;
      try {
        await createCamera({ name: entry.name, address: entry.url, adapter: entry.adapter,
          kind: 'network-stream', hardwareDecode: 'auto', credentialsRef: '', capabilities: {},
          profiles: [{ id: 'main', name: '主码流', role: 'main', endpoint: entry.url,
            videoCodec: 'unknown', audioCodec: '', width: 0, height: 0, fps: 0 }] });
        retainedLines.delete(entry.line);
      } catch (reason) {
        failedLines.add(entry.line);
        failures.push(`第 ${entry.line} 行（${entry.name}）：${reason instanceof Error ? reason.message : '导入失败'}`);
      }
      completed += 1; setBulkProgress({ done: completed, total: parsedBulk.entries.length });
    }
    const count = completed - failedLines.size;
    setBulkText(submittedText.split(/\r?\n/).filter((_, index) => retainedLines.has(index + 1)).join('\n'));
    setBulkMessage(`已导入 ${count} 项；失败 ${failedLines.size} 项，未处理 ${parsedBulk.entries.length - completed} 项。${failures.length ? ` ${failures.join('；')}` : '可在列表中点击“探测轨道”检查媒体信息。'}`);
    setBulkBusy(false); reload();
  };
  if (showLegacyRegistry) return <CameraRegistry onBack={() => { setShowLegacyRegistry(false); reload(); }} />;
  return <section className="source-catalog page-panel">
    <header className="page-heading"><div><span className="eyebrow">设备管理</span><h1>设备与来源</h1><p>管理摄像机与网络视频源，查看状态并快速预览。</p></div>
      <div><button className="primary-button" type="button" disabled={bulkBusy} onClick={() => setShowLegacyRegistry(true)}>添加 / ONVIF 发现</button><button type="button" disabled={bulkBusy} aria-expanded={showBulkImport} onClick={() => setShowBulkImport((value) => !value)}>批量添加</button><button type="button" disabled={legacyBusy} onClick={inspectLegacy}>检查旧 Studio 来源</button></div></header>
    {showBulkImport && <div className="bulk-source-panel"><h2>批量添加视频源</h2>
      <p>每行一项：<code>名称 | 链接</code>，也可用“名称: 链接”。空行和以 # 开头的行会跳过。示例：<code>门口 | rtsp://user:password@192.168.1.20:554/stream1</code></p>
      <p>支持 RTSP/RTSPS，以及后缀为 .m3u8、.flv、.mjpg、.mjpeg、.jpg、.jpeg、.png 的 HTTPS 链接。账号密码会从链接拆出并写入服务端凭据库；未探测的源可在导入后逐项探测。当前格式不清楚的链接请通过单项添加。批量导入允许部分成功，失败行会保留以便修改重试。</p>
      <textarea aria-label="批量视频源" disabled={bulkBusy} rows={8} value={bulkText} onChange={(event) => setBulkText(event.target.value)} placeholder={'门口 | rtsp://user:password@192.168.1.20:554/stream1\n仓库 | rtsp://192.168.1.21:554/stream2'} />
      <p role="status">待导入 {parsedBulk.entries.length} 项{parsedBulk.errors.length ? `；格式问题：${parsedBulk.errors.join('；')}` : ''}</p>
      <button type="button" className="primary-button" disabled={bulkBusy || !parsedBulk.entries.length || !!parsedBulk.errors.length} onClick={() => void importBulk()}>{bulkBusy ? `正在添加 ${bulkProgress.done} / ${bulkProgress.total}` : `添加 ${parsedBulk.entries.length} 项`}</button>
      {bulkBusy && <><progress aria-label="批量添加进度" value={bulkProgress.done} max={bulkProgress.total} /><button type="button" onClick={() => { stopBulk.current = true; setBulkMessage('将在当前项处理结束后停止，其余内容会保留。'); }}>停止后续添加</button></>}
      {bulkMessage && <p role="status">{bulkMessage}</p>}
    </div>}
    {legacyItems.length > 0 && <div className="legacy-import-panel" role="status"><strong>旧 Studio 来源</strong><span>已关联 {legacyItems.filter((item) => item.state === 'linked').length}</span><span>可导入 {legacyItems.filter((item) => item.state === 'ready_to_import').length}</span><span>需配置 {legacyItems.filter((item) => item.state === 'needs_configuration').length}</span><button type="button" disabled={legacyBusy || !legacyItems.some((item) => item.state === 'ready_to_import')} onClick={importReadyLegacy}>导入可安全关联项</button></div>}
    <div className="catalog-toolbar">
      <input aria-label="搜索设备" placeholder="搜索名称、标签或分组" value={query} onChange={(event) => { setQuery(event.target.value.slice(0, 128)); setPage(1); }} />
      <select aria-label="协议筛选" value={adapter} onChange={(event) => { setAdapter(event.target.value); setPage(1); }}><option value="">全部协议</option>{['onvif','rtsp','whep','hls','mjpeg','snapshot','http-flv','srt','rtp','v4l2'].map((value) => <option key={value}>{value}</option>)}</select>
      <select aria-label="启用状态" value={enabled} onChange={(event) => { setEnabled(event.target.value); setPage(1); }}><option value="">全部状态</option><option value="true">已启用</option><option value="false">已停用</option></select>
      <button type="button" disabled={loading} onClick={reload}>刷新列表</button>
      {(query || adapter || enabled) && <button type="button" onClick={resetFilters}>清除筛选</button>}
    </div>
    <div className="catalog-summary"><label className="catalog-select-page"><input type="checkbox" aria-label="全选当前页" disabled={loading || batchBusy || !items.length} checked={items.length > 0 && items.every((item) => selected.includes(item.id))} onChange={(event) => setSelected(event.target.checked ? items.map((item) => item.id) : [])} />全选本页</label><span>共 {total} 台 · 当前显示 {items.length} 台</span><span aria-live="polite">{loading ? '正在更新…' : `第 ${page} / ${Math.max(1, Math.ceil(total / pageSize))} 页`}</span></div>
    {selectedItems.length > 0 && <fieldset className="catalog-batch-bar" disabled={batchBusy || loading}>
      <legend>已选 {selectedItems.length} 台</legend>
      <button type="button" onClick={() => setSelected([])}>取消选择</button>
      <button type="button" onClick={() => void batch({ enabled: true })}>批量启用</button>
      <button type="button" onClick={() => void batch({ enabled: false })}>批量停用</button>
      <label>分组<input aria-label="批量移动到分组" maxLength={64} placeholder="目标分组" value={batchGroup} onChange={(event) => setBatchGroup(event.target.value)} /></label>
      <button type="button" onClick={() => void batch({ groupId: batchGroup.trim() })}>移动分组</button>
      <label>标签<input aria-label="批量增加标签" maxLength={32} placeholder="标签名称" value={batchTag} onChange={(event) => setBatchTag(event.target.value)} /></label>
      <button type="button" disabled={!batchTag.trim()} onClick={() => void batch((item) => ({ tags: [...new Set([...item.tags, batchTag.trim()])].slice(0, 32) }))}>增加标签</button>
      <button type="button" disabled={!batchTag.trim()} onClick={() => void batch((item) => ({ tags: item.tags.filter((tag) => tag !== batchTag.trim()) }))}>移除标签</button>
    </fieldset>}
    {error && <div className="alert conflict-alert" role="alert">{error}</div>}
    {loading && !items.length ? <p className="catalog-loading">正在读取设备列表…</p> : <div className="catalog-table" role="table" aria-busy={loading} aria-label="设备与来源">
      <div className="catalog-row catalog-head" role="row"><input type="checkbox" aria-label="选择本页全部设备" disabled={loading || batchBusy || !items.length} checked={items.length > 0 && items.every((item) => selected.includes(item.id))} onChange={(event) => setSelected(event.target.checked ? items.map((item) => item.id) : [])} /><span>名称 / 类型</span><span>协议 / 地址</span><span>状态</span><span>Profiles / 轨道</span><span>标签 / 分组</span><span>操作</span></div>
      {items.map((camera) => {
        const opened = expanded.includes(camera.id);
        return <div className="catalog-record" key={camera.id}>
          <div className="catalog-row" role="row">
            <input aria-label={`选择 ${camera.name}`} disabled={loading || batchBusy} type="checkbox" checked={selected.includes(camera.id)} onChange={(event) => setSelected((value) => event.target.checked ? [...value, camera.id] : value.filter((id) => id !== camera.id))} />
            <span className="catalog-name"><strong>{camera.name}</strong><small>{camera.kind === 'camera' ? '摄像机' : '网络流'}</small></span>
            <span className="catalog-address"><strong>{camera.adapter.toUpperCase()}</strong><small>{camera.addressDisplay || '地址已保护'}</small></span>
            <span className="catalog-health"><i className={`health-dot ${camera.health}`} />{camera.enabled ? ({ online: '在线', offline: '离线', unknown: '待检测' } as Record<string, string>)[camera.health] ?? camera.health : '已停用'}</span>
            <span>{camera.profileCount} / {camera.trackCount}</span>
            <span><small>{camera.groupId || '未分组'}</small><span className="tag-line">{camera.tags.map((tag) => <i key={tag}>{tag}</i>)}</span></span>
            <span className="row-actions"><button type="button" disabled={!camera.enabled || !camera.profiles.length} onClick={() => setPreview({ camera, profile: camera.profiles.find((profile) => profile.enabled) ?? camera.profiles[0] })}>预览</button><button type="button" aria-expanded={opened} onClick={() => setExpanded((value) => opened ? value.filter((id) => id !== camera.id) : [...value, camera.id])}>{opened ? '收起' : '详情'}</button>
              <button type="button" onClick={() => void updateCamera(camera, { enabled: !camera.enabled })}>{camera.enabled ? '停用' : '启用'}</button></span>
          </div>
          {opened && <div className="catalog-details"><div className="device-meta-editor">
            <label>分组<input maxLength={64} defaultValue={camera.groupId} onBlur={(event) => { if (event.currentTarget.value !== camera.groupId) void updateCamera(camera, { groupId: event.currentTarget.value }); }} /></label>
            <label>标签（逗号分隔）<input defaultValue={camera.tags.join(', ')} onBlur={(event) => { const tags = event.currentTarget.value.split(',').map((value) => value.trim()).filter(Boolean); if (JSON.stringify(tags) !== JSON.stringify(camera.tags)) void updateCamera(camera, { tags }); }} /></label>
          </div>{camera.profiles.map((profile) => <ProfileEditor key={profile.id} camera={camera} profile={profile} onChanged={replace} onPreview={() => setPreview({ camera, profile })} />)}</div>}
        </div>;
      })}
    </div>}
    {!loading && !items.length && !error && <div className="catalog-empty"><h2>{query || adapter || enabled ? '没有匹配的设备' : '还没有添加视频源'}</h2><p>{query || adapter || enabled ? '尝试调整关键词或清除筛选。' : '添加第一台摄像机，或粘贴多个链接批量导入。'}</p><button type="button" onClick={query || adapter || enabled ? resetFilters : () => setShowBulkImport(true)}>{query || adapter || enabled ? '重置筛选条件' : '批量添加视频源'}</button></div>}
    <nav className="catalog-pagination" aria-label="设备列表分页"><button type="button" disabled={loading || page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</button><span>第 {page} / {Math.max(1, Math.ceil(total / pageSize))} 页</span><button type="button" disabled={loading || page * pageSize >= total} onClick={() => setPage((value) => value + 1)}>下一页</button></nav>
    {preview && previewDocument && <Modal className="source-preview-dialog" label="独立来源预览" onClose={() => { setPreview(null); setPreviewTopology(null); }}><div className="profile-preview-card">
      <header><div><span className="eyebrow">Profile preview</span><h2>{preview.camera.name} · {preview.profile.name}</h2></div><button type="button" onClick={() => { setPreview(null); setPreviewTopology(null); }}>关闭并释放</button></header>
      <DirectPreview compact scene={previewDocument} />
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
    </div></Modal>}
  </section>;
}
