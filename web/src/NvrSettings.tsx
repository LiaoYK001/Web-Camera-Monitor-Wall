import { useEffect, useMemo, useState } from 'react';
import { fetchCameras, fetchNvrConfig, fetchNvrStatus, saveNvrConfig } from './api';
import type { CameraRecord, NvrCameraConfig, NvrConfig, NvrStatus } from './types';

const DEFAULT_CAMERA = (camera: CameraRecord): NvrCameraConfig => {
  const main = camera.profiles.find((profile) => profile.role === 'main') ?? camera.profiles[0];
  const sub = camera.profiles.find((profile) => profile.role === 'sub');
  return {
    id: camera.id, name: camera.name, policy: 'off', mainUrl: '', subUrl: '',
    cameraId: camera.id, mainProfileId: main?.id ?? 'main', subProfileId: sub?.id ?? '',
    stream: 'main', mode: 'auto', transport: 'tcp', segmentSeconds: 60,
    maxAgeHours: 720, maxBytes: 0, preEventSeconds: 0, schedule: [],
  };
};

const DEFAULT_CONFIG: NvrConfig = {
  schemaVersion: 1, segmentSeconds: 60, maxAgeHours: 720, maxBytes: 0,
  minFreeBytes: 0, cameras: [],
};

const stateLabel: Record<string, string> = {
  stopped: '未录制', recording: '录制中', event: '事件录制', degraded: '降级',
};

export default function NvrSettings({ onOpenArchive }: { onOpenArchive?: () => void }) {
  const [config, setConfig] = useState<NvrConfig | null>(null);
  const [saved, setSaved] = useState('');
  const [cameras, setCameras] = useState<CameraRecord[]>([]);
  const [status, setStatus] = useState<NvrStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    void Promise.all([fetchNvrConfig(controller.signal), fetchCameras(controller.signal), fetchNvrStatus(controller.signal)])
      .then(([value, catalog, state]) => {
        if (controller.signal.aborted) return;
        setConfig(value); setSaved(JSON.stringify(value)); setCameras(catalog.cameras); setStatus(state);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '录像配置不可用');
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!config) return;
    const timer = window.setInterval(() => {
      const controller = new AbortController();
      void fetchNvrStatus(controller.signal).then(setStatus).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [config]);

  const configured = useMemo(() => new Map((config?.cameras ?? []).filter((camera) => camera.cameraId).map((camera) => [camera.cameraId, camera])), [config]);
  const dirty = Boolean(config && JSON.stringify(config) !== saved);

  const updateCamera = (camera: CameraRecord, change: (current: NvrCameraConfig) => NvrCameraConfig) => {
    setConfig((current) => {
      const base = current ?? DEFAULT_CONFIG;
      const existing = base.cameras.find((item) => item.cameraId === camera.id) ?? DEFAULT_CAMERA(camera);
      const next = change(existing);
      const cameras = base.cameras.some((item) => item.cameraId === camera.id)
        ? base.cameras.map((item) => item.cameraId === camera.id ? next : item)
        : [...base.cameras, next];
      return { ...base, cameras };
    });
    setNotice('');
  };

  const save = async () => {
    if (!config || saving || !dirty) return;
    if (config.cameras.some((camera) => !camera.cameraId)) {
      setError('录像配置包含历史原始 RTSP 地址，当前页面不会回写已脱敏地址。请保留该配置并通过受认证的管理 API 修改原始 URL 项。');
      return;
    }
    setSaving(true); setError(''); setNotice('');
    try {
      const result = await saveNvrConfig(config);
      setConfig(result); setSaved(JSON.stringify(result));
      setStatus(await fetchNvrStatus());
      setNotice('录像配置已保存，后台录制将按策略启动。');
    } catch (reason) {
      setError(`${reason instanceof Error ? reason.message : '录像配置保存失败'}。当前配置已保留，可重试。`);
    } finally {
      setSaving(false);
    }
  };

  return <section className="nvr-settings page-panel" aria-label="录像配置">
    <header className="page-heading"><div><span className="eyebrow">Storage</span><h1>录像与存储</h1><p>为现有摄像机选择连续或事件录制；录像由同机 NVR 服务写入私有存储。</p></div>
      <div><button type="button" disabled={loading || saving || !dirty} onClick={() => void save()}>{saving ? '正在保存…' : '保存录像配置'}</button>{onOpenArchive && <button type="button" onClick={onOpenArchive}>打开录像时间线</button>}</div>
    </header>
    {error && <div className="alert conflict-alert" role="alert">{error}</div>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {loading && <p role="status">正在读取录像配置和设备目录…</p>}
    {!loading && config && <>
      <section className="settings-grid" aria-label="录像默认值">
        <article><h3>分段与保留</h3>
          <label>分段长度（秒）<input type="number" min="2" max="3600" step="1" value={config.segmentSeconds} onChange={(event) => setConfig({ ...config, segmentSeconds: Math.max(2, Math.min(3600, Number(event.target.value) || 2)) })} /></label>
          <label>保留小时<input type="number" min="1" max="87600" step="1" value={config.maxAgeHours} onChange={(event) => setConfig({ ...config, maxAgeHours: Math.max(1, Math.min(87600, Number(event.target.value) || 1)) })} /></label>
        </article>
        <article><h3>容量</h3>
          <label>配额（GB，0 表示不限制）<input type="number" min="0" max="1048576" step="1" value={config.maxBytes ? Math.floor(config.maxBytes / 1024 ** 3) : 0} onChange={(event) => setConfig({ ...config, maxBytes: Math.max(0, Number(event.target.value) || 0) * 1024 ** 3 })} /></label>
          <label>最低剩余空间（GB）<input type="number" min="0" max="1048576" step="1" value={Math.floor(config.minFreeBytes / 1024 ** 3)} onChange={(event) => setConfig({ ...config, minFreeBytes: Math.max(0, Number(event.target.value) || 0) * 1024 ** 3 })} /></label>
        </article>
      </section>
      <section className="settings-grid" aria-label="摄像机录像策略">
        {config.cameras.some((camera) => !camera.cameraId) && <article><h3>历史原始地址项</h3><p>配置中有 {config.cameras.filter((camera) => !camera.cameraId).length} 个原始 RTSP 地址项。为避免把脱敏地址写回配置，本页禁用保存；摄像机目录项仍可查看。</p></article>}
        {cameras.map((camera) => {
          const current = configured.get(camera.id) ?? DEFAULT_CAMERA(camera);
          const cameraStatus = status?.cameras.find((item) => item.id === current.id);
          const main = camera.profiles.find((profile) => profile.role === 'main') ?? camera.profiles[0];
          const sub = camera.profiles.find((profile) => profile.role === 'sub');
          return <article key={camera.id} data-camera-id={camera.id}>
            <h3>{camera.name}</h3>
            <label>录制策略<select value={current.policy} onChange={(event) => updateCamera(camera, (value) => ({ ...value, policy: event.target.value as NvrCameraConfig['policy'], cameraId: camera.id, name: camera.name, mainProfileId: main?.id ?? value.mainProfileId, subProfileId: sub?.id ?? value.subProfileId }))}>
              <option value="off">关闭</option><option value="continuous">连续录制</option><option value="event">事件录制</option><option value="scheduled">按计划</option>
            </select></label>
            <label>录像码流<select value={current.stream} onChange={(event) => updateCamera(camera, (value) => ({ ...value, stream: event.target.value as NvrCameraConfig['stream'], cameraId: camera.id, name: camera.name, mainProfileId: main?.id ?? value.mainProfileId, subProfileId: sub?.id ?? value.subProfileId }))}><option value="main" disabled={!main}>主码流</option><option value="sub" disabled={!sub}>子码流</option></select></label>
            <label>本机分段（秒）<input type="number" min="2" max="3600" step="1" value={current.segmentSeconds} onChange={(event) => updateCamera(camera, (value) => ({ ...value, segmentSeconds: Math.max(2, Math.min(3600, Number(event.target.value) || 2)) }))} /></label>
            <p><small>{cameraStatus ? `${stateLabel[cameraStatus.state] ?? cameraStatus.state} · ${cameraStatus.segments} 段` : '尚未启动'}{current.policy === 'scheduled' && !current.schedule.length ? ' · 按计划需要配置时间段，当前不会录制' : ''}</small></p>
          </article>;
        })}
        {!cameras.length && <article><h3>没有可用摄像机</h3><p>先在“设备与来源”添加摄像机，再配置录像。</p></article>}
      </section>
      <footer className="settings-save-bar"><span role="status">{dirty ? '有未保存的录像配置修改' : '录像配置已载入'}</span><button type="button" disabled={!dirty || saving} onClick={() => setConfig(JSON.parse(saved) as NvrConfig)}>撤销修改</button><button type="button" className="primary-button" disabled={!dirty || saving} onClick={() => void save()}>保存录像配置</button></footer>
    </>}
  </section>;
}
