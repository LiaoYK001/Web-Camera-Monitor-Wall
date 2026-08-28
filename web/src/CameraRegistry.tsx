import { useEffect, useRef, useState } from 'react';
import { createCamera, deleteCamera, detectCamera, discoverOnvif, fetchAnalyticsPolicies, fetchCameras, fetchOnvifPresets, fetchOnvifSnapshot, mutateOnvifPreset, probeOnvif, pullOnvifEvents, qualifyBrowserDirect, sendOnvifPtz, sendOnvifTalk, syncOnvifCamera, updateAnalyticsPolicies } from './api';
import type { AnalyticsPolicy, CameraAdapter, CameraDetection, CameraRecord, OnvifPreset } from './types';
import { loadSyncState } from './localRuntime';
import { queueCameraPreference, synchronizeBrowserState } from './syncRuntime';

type EditableAnalyticsPolicy = Omit<AnalyticsPolicy, 'updatedAt'>;
type CameraPreference = { displayName: string; favorite: boolean; group: string };
const policyKey = (cameraId: string, profileId: string) => `${cameraId}\u0000${profileId}`;
const defaultPolicy = (cameraId: string, profileId: string): EditableAnalyticsPolicy => ({
  cameraId, profileId, motionEnabled: false, sceneChangeEnabled: false, personEnabled: false,
  allowEventPromotion: false, promotionThreshold: .6, promotionHoldSeconds: 15,
  promotionCooldownSeconds: 30, forceAnalyticsAlwaysOn: false,
});

function DeviceControls({ camera, busy, fail }: { camera: CameraRecord; busy: boolean; fail: (message: string) => void }) {
  const capabilities = ((camera.capabilities.onvif ?? {}) as Record<string, unknown>);
  const [presets, setPresets] = useState<OnvifPreset[]>([]);
  const [snapshot, setSnapshot] = useState('');
  const [status, setStatus] = useState('');
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const invoke = async (action: () => Promise<unknown>, success: string) => {
    try { await action(); setStatus(success); } catch (reason) { fail(reason instanceof Error ? reason.message : '设备操作失败'); }
  };
  const move = (x: number, y: number, zoom = 0) => invoke(
    () => sendOnvifPtz(camera.id, { operation: 'continuous', x, y, zoom, durationMs: 350 }), 'PTZ 命令已发送',
  );
  const toggleTalk = async () => {
    if (recorder.current?.state === 'recording') { recorder.current.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/ogg';
      const next = new MediaRecorder(stream, { mimeType }); chunks.current = []; recorder.current = next;
      next.ondataavailable = (event) => { if (event.data.size) chunks.current.push(event.data); };
      next.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunks.current, { type: mimeType });
        if (blob.size > 512 * 1024) { fail('对讲片段超过 512 KiB，请缩短录音'); return; }
        const reader = new FileReader();
        reader.onload = () => void invoke(() => sendOnvifTalk(camera.id, {
          operation: 'start', contentType: mimeType, data: String(reader.result).split(',', 2)[1] ?? '',
        }), '对讲片段已发送');
        reader.readAsDataURL(blob);
      };
      next.start(); setStatus('正在录音，再次点击即发送（最长 10 秒）');
      window.setTimeout(() => { if (next.state === 'recording') next.stop(); }, 10000);
    } catch (reason) { fail(reason instanceof Error ? reason.message : '麦克风不可用'); }
  };
  if (!Object.values(capabilities).some(Boolean)) return null;
  return <div className="device-controls">
    {capabilities.ptz === true && <><div className="ptz-pad" aria-label="PTZ 控制">
      <button disabled={busy} onClick={() => void move(0, 1)}>↑</button><button disabled={busy} onClick={() => void move(-1, 0)}>←</button>
      <button disabled={busy} onClick={() => void sendOnvifPtz(camera.id, { operation: 'stop' })}>■</button><button disabled={busy} onClick={() => void move(1, 0)}>→</button>
      <button disabled={busy} onClick={() => void move(0, -1)}>↓</button><button disabled={busy} onClick={() => void move(0, 0, .5)}>＋</button><button disabled={busy} onClick={() => void move(0, 0, -.5)}>－</button>
    </div><div className="preset-controls"><button className="ghost-button" onClick={() => void fetchOnvifPresets(camera.id).then((value) => setPresets(value.presets)).catch((reason: unknown) => fail(reason instanceof Error ? reason.message : '读取预置位失败'))}>预置位</button>
      {presets.map((preset) => <button key={preset.token} onClick={() => void invoke(() => sendOnvifPtz(camera.id, { operation: 'gotoPreset', presetToken: preset.token }), `已转到 ${preset.name}`)}>{preset.name}</button>)}
      <button onClick={() => void invoke(() => mutateOnvifPreset(camera.id, { operation: 'set', name: `Preset ${presets.length + 1}` }), '预置位已保存')}>保存当前位置</button></div></>}
    <div className="device-actions">
      {capabilities.snapshot === true && <button onClick={() => void fetchOnvifSnapshot(camera.id).then((value) => { setSnapshot(`data:${value.contentType};base64,${value.data}`); setStatus('快照已读取'); }).catch((reason: unknown) => fail(reason instanceof Error ? reason.message : '快照失败'))}>快照</button>}
      {capabilities.events === true && <button onClick={() => void pullOnvifEvents(camera.id).then((value) => setStatus(`收到 ${value.events.length} 个设备事件`)).catch((reason: unknown) => fail(reason instanceof Error ? reason.message : '事件拉取失败'))}>拉取事件</button>}
      {capabilities.talk === true && <button onClick={() => void toggleTalk()}>{recorder.current?.state === 'recording' ? '停止并发送' : '短按对讲'}</button>}
    </div>
    {snapshot && <img className="device-snapshot" src={snapshot} alt={`${camera.name} 快照`} />}
    {status && <small role="status">{status}</small>}
  </div>;
}

export default function CameraRegistry({ onBack }: { onBack: () => void }) {
  const [cameras, setCameras] = useState<CameraRecord[]>([]);
  const [address, setAddress] = useState('');
  const [name, setName] = useState('');
  const [credentialsRef, setCredentialsRef] = useState('');
  const [detection, setDetection] = useState<CameraDetection | null>(null);
  const [discovered, setDiscovered] = useState<Array<{ address: string; host: string }>>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [policies, setPolicies] = useState<Map<string, EditableAnalyticsPolicy>>(new Map());
  const [preferences, setPreferences] = useState<Map<string, CameraPreference>>(new Map());
  const reload = async () => { try {
    const [cameraResult, policyResult, syncState] = await Promise.all([
      fetchCameras(), fetchAnalyticsPolicies(), loadSyncState(),
    ]);
    setCameras(cameraResult.cameras);
    setPolicies(new Map(policyResult.policies.map((policy) => [policyKey(policy.cameraId, policy.profileId), policy])));
    setPreferences(new Map((syncState?.documents ?? []).filter((item) =>
      item.kind === 'camera-preference' && !item.deleted && item.document).map((item) => [item.id, {
        displayName: String(item.document?.displayName ?? ''), favorite: item.document?.favorite === true,
        group: String(item.document?.group ?? ''),
      }])));
  } catch (reason) { setError(reason instanceof Error ? reason.message : '无法读取摄像机'); } };
  useEffect(() => { void reload(); }, []);

  const detect = async () => {
    setBusy(true); setError('');
    try {
      const result = await detectCamera(address.trim());
      setDetection(result);
      if (!name) setName(result.address.split('/').filter(Boolean).at(-1) ?? '新摄像机');
    } catch (reason) { setError(reason instanceof Error ? reason.message : '自动检测失败'); }
    finally { setBusy(false); }
  };
  const add = async () => {
    if (!detection) return;
    setBusy(true); setError('');
    try {
      await createCamera({ name: name.trim(), address: detection.address, adapter: detection.adapter,
        credentialsRef: credentialsRef.trim(), hardwareDecode: 'auto', profiles: detection.profiles,
        capabilities: detection.capabilities ?? { probe: detection.probe, contentType: detection.contentType ?? '' } });
      setAddress(''); setName(''); setCredentialsRef(''); setDetection(null); await reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '添加失败'); }
    finally { setBusy(false); }
  };
  const readOnvifProfiles = async () => {
    setBusy(true); setError('');
    try {
      const result = await probeOnvif(address.trim(), credentialsRef.trim());
      setDetection(result);
      if (!name) setName('ONVIF 摄像机');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'ONVIF Profile 读取失败'); }
    finally { setBusy(false); }
  };
  const syncOnvif = async (cameraId: string) => {
    setBusy(true); setError('');
    try { await syncOnvifCamera(cameraId); await reload(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'ONVIF 同步失败'); }
    finally { setBusy(false); }
  };
  const qualifyDirect = async (cameraId: string, profileId: string) => {
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await qualifyBrowserDirect(cameraId, profileId);
      setNotice(result.eligible
        ? '浏览器真直连 HTTPS、CORS 与媒体响应探测已通过。'
        : `该 Profile 必须使用 Gateway/Hybrid：${result.reason}`);
      await reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '浏览器直连资格探测失败'); }
    finally { setBusy(false); }
  };
  const editPolicy = (cameraId: string, profileId: string, change: Partial<EditableAnalyticsPolicy>) => {
    setPolicies((current) => {
      const next = new Map(current); const key = policyKey(cameraId, profileId);
      next.set(key, { ...(current.get(key) ?? defaultPolicy(cameraId, profileId)), ...change });
      return next;
    });
  };
  const savePolicySet = async (values: EditableAnalyticsPolicy[]) => {
    setBusy(true); setError('');
    try {
      const saved = await updateAnalyticsPolicies(values);
      setPolicies((current) => {
        const next = new Map(current);
        saved.policies.forEach((policy) => next.set(policyKey(policy.cameraId, policy.profileId), policy));
        return next;
      });
      setNotice(`已原子更新 ${saved.policies.length} 个 Profile 的分析策略。`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '分析策略更新失败'); }
    finally { setBusy(false); }
  };
  const setAllAnalytics = (enabled: boolean) => {
    const values = cameras.flatMap((camera) => camera.profiles.map((profile) => ({
      ...(policies.get(policyKey(camera.id, profile.id)) ?? defaultPolicy(camera.id, profile.id)),
      motionEnabled: enabled, sceneChangeEnabled: enabled, personEnabled: enabled,
    })));
    if (values.length) void savePolicySet(values);
  };
  const editPreference = (camera: CameraRecord, change: Partial<CameraPreference>) => setPreferences((current) => {
    const next = new Map(current);
    next.set(camera.id, { displayName: camera.name, favorite: false, group: '', ...current.get(camera.id), ...change });
    return next;
  });
  const savePreference = async (camera: CameraRecord) => {
    const preference = preferences.get(camera.id) ?? { displayName: camera.name, favorite: false, group: '' };
    try {
      await queueCameraPreference(camera.id, preference);
      await synchronizeBrowserState();
      setNotice('摄像机显示偏好已进入加密双向同步。');
    } catch (reason) {
      setNotice(reason instanceof Error && reason.message.includes('尚未完成配对')
        ? '显示偏好已保存在加密离线队列；浏览器配对后同步。'
        : (reason instanceof Error ? reason.message : '显示偏好同步失败'));
    }
  };

  return <main className="registry-page">
    <header className="registry-header"><div><span className="eyebrow">Camera Source Adapter</span><h1>设备与码流</h1></div><button className="ghost-button" type="button" onClick={onBack}>返回 Studio</button></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {notice && <div className="notice" role="status">{notice}</div>}
    <section className="registry-add">
      <div><h2>添加设备</h2><p>输入 IP、主机名或 URL。地址中禁止明文账号密码；凭据通过 Secret 引用绑定。</p></div>
      <label><span>地址</span><input value={address} placeholder="camera.example.invalid 或 rtsp://camera.example.invalid/live" onChange={(event) => { setAddress(event.target.value); setDetection(null); }} /></label>
      <div className="registry-actions"><button className="primary-button" disabled={busy || !address.trim()} type="button" onClick={() => void detect()}>自动检测</button><button className="ghost-button" disabled={busy} type="button" onClick={() => void discoverOnvif().then((result) => setDiscovered(result.devices)).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '发现失败'))}>ONVIF 发现</button></div>
      {detection && <div className="detection-result"><strong>{detection.adapter.toUpperCase()} · {detection.probe}{detection.profileVersion ? ` · Profile ${detection.profileVersion}` : ''}</strong><span>{detection.profiles.length ? `${detection.profiles.length} 个码流 Profile` : '等待设备授权后读取 Profile'}</span><label><span>设备名称</span><input value={name} maxLength={128} onChange={(event) => setName(event.target.value)} /></label><label><span>凭据 Secret 引用（可选）</span><input value={credentialsRef} maxLength={256} placeholder="front-door" onChange={(event) => setCredentialsRef(event.target.value.replace(/[^a-zA-Z0-9._/-]/g, ''))} /></label><small>引用 /run/secrets/webobs-camera-credentials/&lt;名称&gt;.json；数据库不保存密码。</small>{detection.adapter === 'onvif' && <button className="ghost-button" disabled={busy || !address.trim()} type="button" onClick={() => void readOnvifProfiles()}>读取 ONVIF Profile</button>}<button className="primary-button" disabled={!name.trim() || (detection.adapter === 'onvif' && detection.profiles.length === 0)} type="button" onClick={() => void add()}>保存到 Registry</button></div>}
      {discovered.length > 0 && <div className="discovery-list">{discovered.map((device) => <button type="button" key={device.address} onClick={() => { setAddress(device.address); setDetection(null); }}><strong>{device.host}</strong><span>{device.address}</span></button>)}</div>}
    </section>
    <section className="camera-list"><div className="section-title"><h2>Camera Registry</h2><span>{cameras.length} 台</span></div>
      <div className="analytics-batch"><span>当前列表分析开关</span><button className="ghost-button" disabled={busy || !cameras.length} onClick={() => setAllAnalytics(true)}>Select All</button><button className="ghost-button" disabled={busy || !cameras.length} onClick={() => setAllAnalytics(false)}>Unselect All</button><small>默认全部关闭；人物框为 v3-M2 预留接口。</small></div>
      {cameras.length === 0 ? <div className="registry-empty"><h3>尚未添加摄像机</h3><p>使用自动检测，或通过 ONVIF WS-Discovery 查找局域网设备。</p></div> : cameras.map((camera) => <article className="camera-card" key={camera.id}><div><span className="adapter-pill">{camera.adapter}</span><h3>{preferences.get(camera.id)?.displayName || camera.name}{preferences.get(camera.id)?.favorite ? ' ★' : ''}</h3><p>{camera.address}</p><div className="camera-preference"><label>显示名称<input maxLength={128} value={preferences.get(camera.id)?.displayName ?? camera.name} onChange={(event) => editPreference(camera, { displayName: event.target.value })} /></label><label>分组<input maxLength={64} value={preferences.get(camera.id)?.group ?? ''} onChange={(event) => editPreference(camera, { group: event.target.value })} /></label><label><input type="checkbox" checked={preferences.get(camera.id)?.favorite ?? false} onChange={(event) => editPreference(camera, { favorite: event.target.checked })} />收藏</label><button className="ghost-button" onClick={() => void savePreference(camera)}>同步显示偏好</button></div></div><dl><div><dt>Profile</dt><dd>{camera.profiles.length}</dd></div><div><dt>硬解</dt><dd>{camera.hardwareDecode}</dd></div><div><dt>健康</dt><dd>{camera.health}</dd></div></dl><div className="profile-list">{camera.profiles.map((profile) => {
        const proof = ((camera.capabilities.browserDirect as { profiles?: Record<string, { tlsVerified?: boolean; corsVerified?: boolean; reason?: string }> } | undefined)?.profiles?.[profile.id]);
        const policy = policies.get(policyKey(camera.id, profile.id)) ?? defaultPolicy(camera.id, profile.id);
        return <span key={profile.id}>{profile.role} · {profile.videoCodec || 'unknown'} {profile.width ? `${profile.width}×${profile.height}` : ''}
          {['whep', 'hls', 'mjpeg'].includes(camera.adapter) && <><small>{proof?.tlsVerified && proof?.corsVerified ? ' · Browser Direct 已验证' : proof ? ` · 未通过：${proof.reason}` : ' · 未探测'}</small><button className="ghost-button" disabled={busy} type="button" onClick={() => void qualifyDirect(camera.id, profile.id)}>验证浏览器真直连</button></>}
          <span className="analytics-policy" aria-label={`${camera.name} ${profile.name} 分析策略`}>
            <label><input type="checkbox" checked={policy.motionEnabled} onChange={(event) => editPolicy(camera.id, profile.id, { motionEnabled: event.target.checked })} />运动</label>
            <label><input type="checkbox" checked={policy.sceneChangeEnabled} onChange={(event) => editPolicy(camera.id, profile.id, { sceneChangeEnabled: event.target.checked })} />大范围变化</label>
            <label><input type="checkbox" checked={policy.personEnabled} onChange={(event) => editPolicy(camera.id, profile.id, { personEnabled: event.target.checked })} />人物框（v3-M2）</label>
            <label><input type="checkbox" checked={policy.allowEventPromotion} onChange={(event) => editPolicy(camera.id, profile.id, { allowEventPromotion: event.target.checked })} />事件提升到 M</label>
            {policy.allowEventPromotion && <><label>阈值<input type="number" min="0" max="1" step="0.05" value={policy.promotionThreshold} onChange={(event) => editPolicy(camera.id, profile.id, { promotionThreshold: Number(event.target.value) })} /></label><label>保持秒<input type="number" min="1" max="3600" value={policy.promotionHoldSeconds} onChange={(event) => editPolicy(camera.id, profile.id, { promotionHoldSeconds: Number(event.target.value) })} /></label><label>冷却秒<input type="number" min="0" max="86400" value={policy.promotionCooldownSeconds} onChange={(event) => editPolicy(camera.id, profile.id, { promotionCooldownSeconds: Number(event.target.value) })} /></label></>}
            <label title="低功耗模式下仍执行软件分析会增加设备功耗"><input type="checkbox" checked={policy.forceAnalyticsAlwaysOn} onChange={(event) => editPolicy(camera.id, profile.id, { forceAnalyticsAlwaysOn: event.target.checked })} />强制持续分析 ⚠</label>
            <button className="ghost-button" disabled={busy} onClick={() => void savePolicySet([policy])}>保存策略</button>
          </span>
        </span>;
      })}</div><div className="camera-operations">{camera.adapter === 'onvif' && <><button className="ghost-button" disabled={busy} type="button" onClick={() => void syncOnvif(camera.id)}>同步 ONVIF Profile</button><DeviceControls camera={camera} busy={busy} fail={setError} /></>}<button className="danger-button" type="button" onClick={() => { if (window.confirm(`删除 ${camera.name}？`)) void deleteCamera(camera.id).then(reload); }}>删除</button></div></article>)}
    </section>
    <footer className="adapter-footer">支持：{(['onvif','rtsp','mjpeg','snapshot','hls','http-flv','whep','srt','rtp','v4l2'] as CameraAdapter[]).join(' · ')}</footer>
  </main>;
}
