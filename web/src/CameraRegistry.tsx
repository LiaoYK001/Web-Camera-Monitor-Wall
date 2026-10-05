import { useEffect, useRef, useState } from 'react';
import { useOwnedRequest } from './useOwnedRequest';
import { useDraftGuard } from './useDraftGuard';
import { useDesktopWork } from './desktopRuntime';
import { withRequestTimeout } from './requestTimeout';
import { ControlApiError, createCamera, deleteCamera, detectCamera, discoverOnvif, fetchAnalyticsPolicies, fetchCameraPreferences, fetchCameras, fetchV3AnalyticsPolicies, patchV3AnalyticsPolicies, patchCameraPreference, probeOnvif, qualifyBrowserDirect, syncOnvifCamera, updateAnalyticsPolicies, updateCameraCredentials } from './api';
import type { AnalyticsPolicy, CameraAdapter, CameraDetection, CameraRecord } from './types';
import { loadSyncState } from './localRuntime';
import Go2rtcStreams from './Go2rtcStreams';
import DeviceControls from './CameraDeviceControls';

type EditableAnalyticsPolicy = Omit<AnalyticsPolicy, 'updatedAt'>;
type CameraPreference = { displayName: string; favorite: boolean; group: string };
const policyKey = (cameraId: string, profileId: string) => `${cameraId}\u0000${profileId}`;
const equivalent = (left: unknown, right: unknown): boolean => {
  if (left === right) return true;
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false;
  const a = Object.entries(left).filter(([key]) => key !== 'updatedAt');
  const b = Object.entries(right).filter(([key]) => key !== 'updatedAt');
  return a.length === b.length && a.every(([key, value]) => Object.hasOwn(right, key) && equivalent(value, (right as Record<string, unknown>)[key]));
};
function rebaseDraft<T>(baseline: T, draft: T, incoming: T): T {
  if (equivalent(baseline, draft)) return incoming;
  if (!baseline || !draft || typeof baseline !== 'object' || typeof draft !== 'object' || Array.isArray(draft)) return draft;
  const before = baseline as Record<string, unknown>;
  const next = { ...incoming } as Record<string, unknown>;
  Object.entries(draft).forEach(([key, value]) => {
    if (!equivalent(before[key], value)) next[key] = rebaseDraft(before[key], value, next[key]);
  });
  return next as T;
}
function safeAddressDisplay(value: string, hasCredentials = false): string {
  try {
    const parsed = new URL(value.includes('://') ? value : `https://${value}`);
    const port = parsed.port ? `:${parsed.port}` : '';
    const auth = hasCredentials || parsed.username || parsed.password ? '*****:*****@' : '';
    return `${parsed.protocol}//${auth}${parsed.hostname}${port}${parsed.pathname === '/' ? '' : parsed.pathname}`;
  } catch { return '地址不可用'; }
}

function extractUserinfo(value: string): { username: string; password: string } | null {
  try {
    const parsed = new URL(value.includes('://') ? value : `https://${value}`);
    if (!parsed.username && !parsed.password) return null;
    return {
      username: decodeURIComponent(parsed.username),
      password: decodeURIComponent(parsed.password),
    };
  } catch { return null; }
}
const defaultPolicy = (cameraId: string, profileId: string): EditableAnalyticsPolicy => ({
  cameraId, profileId, motionEnabled: false, sceneChangeEnabled: false, personEnabled: false,
  allowEventPromotion: false, promotionThreshold: .6, promotionHoldSeconds: 15,
  promotionCooldownSeconds: 30, forceAnalyticsAlwaysOn: false,
  motion: { sensitivity: .15, sampleFps: 2, debounceMs: 500, cooldownMs: 5000 },
  sceneChange: { threshold: .55, confirmFrames: 2, cooldownMs: 30000 },
  person: { confidenceThreshold: .6, sampleFps: 1, maxBoxes: 16, executionPreference: 'auto', allowServerFallback: false },
});

export default function CameraRegistry({ onBack }: { onBack: () => void }) {
  const [cameras, setCameras] = useState<CameraRecord[]>([]);
  const [address, setAddress] = useState('');
  const [name, setName] = useState('');
  const [credentialsRef, setCredentialsRef] = useState('');
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [pendingCredentials, setPendingCredentials] = useState<{ username: string; password: string } | null>(null);
  const [credentialsNotice, setCredentialsNotice] = useState('');
  const [editingCredentials, setEditingCredentials] = useState<string | null>(null);
  const [editUsername, setEditUsername] = useState('');
  const [editPassword, setEditPassword] = useState('');
  const [detection, setDetection] = useState<CameraDetection | null>(null);
  const [discovered, setDiscovered] = useState<Array<{ address: string; host: string }>>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [policies, setPolicies] = useState<Map<string, EditableAnalyticsPolicy>>(new Map());
  const [analyticsRevision, setAnalyticsRevision] = useState(1);
  const [preferences, setPreferences] = useState<Map<string, CameraPreference>>(new Map());
  const alive = useRef(false), reading = useRef<AbortController | null>(null);
  const { run, busy: requestBusy, mutating, cancelRead, isMutating } = useOwnedRequest(setError, () => reading.current?.abort());
  const [bridgeBusy, setBridgeBusy] = useState(false);
  const busy = requestBusy || bridgeBusy;
  const policyDrafts = useRef(new Map<string, EditableAnalyticsPolicy>());
  const policyBaseline = useRef(new Map<string, EditableAnalyticsPolicy>());
  const preferenceDrafts = useRef(new Map<string, CameraPreference>());
  const preferenceBaseline = useRef(new Map<string, CameraPreference>());
  const [preferencesReady, setPreferencesReady] = useState(false), [policiesReady, setPoliciesReady] = useState(false);
  const [readError, setReadError] = useState('');
  const submission = useRef<(Partial<CameraRecord> & { username?: string; password?: string }) | null>(null);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const dirty = Boolean(address || name || credentialsRef || loginUsername || loginPassword || pendingCredentials
    || editUsername || editPassword || policyDrafts.current.size || preferenceDrafts.current.size || unconfirmed);
  useDesktopWork('camera-registry', dirty, busy);
  useDraftGuard(dirty, busy, '设备草稿或显示/分析策略尚未保存，离开会丢弃这些修改。继续？', setNotice);
  const reload = async () => {
    reading.current?.abort();
    const controller = new AbortController(); reading.current = controller;
    const current = () => alive.current && reading.current === controller && !controller.signal.aborted;
    try {
      const result = await withRequestTimeout(15000, signal => fetchCameras(signal), controller.signal);
      if (!current()) return;
      setCameras(result.cameras); setReadError('');
    } catch {
      if (current()) setReadError('设备列表读取失败，请检查网络与权限后重试；已有草稿保留。');
      return;
    }
    // Independent reads: slow or denied analytics must not hide account preferences.
    void withRequestTimeout(15000, async signal => {
      try { return await fetchV3AnalyticsPolicies(signal); }
      catch (reason) {
        if (!(reason instanceof ControlApiError) || ![404, 405].includes(reason.status)) throw reason;
        const legacy = await fetchAnalyticsPolicies(signal); return { ...legacy, revision: 1 };
      }
    }, controller.signal).then(result => {
      if (!current()) return;
      setAnalyticsRevision(result.revision);
      const next = new Map<string, EditableAnalyticsPolicy>(result.policies.map(policy => [policyKey(policy.cameraId, policy.profileId), policy]));
      const baseline = new Map(next);
      policyDrafts.current.forEach((value, key) => {
        const fallback = defaultPolicy(value.cameraId, value.profileId), incoming = next.get(key) ?? fallback;
        const rebased = rebaseDraft(policyBaseline.current.get(key) ?? fallback, value, incoming);
        if (equivalent(rebased, incoming)) policyDrafts.current.delete(key); else policyDrafts.current.set(key, rebased);
        next.set(key, rebased);
      });
      policyBaseline.current = baseline; setPolicies(next); setPoliciesReady(true);
    }).catch(() => { if (current()) { setPoliciesReady(false); setReadError(value => value || '分析策略读取失败，暂时无法编辑；请重试读取。'); } });
    void withRequestTimeout(15000, async signal => {
      const account = await fetchCameraPreferences(signal);
      if (account !== null) return { values: new Map(Object.entries(account)), legacy: false };
      const local = await loadSyncState();
      return { values: new Map((local?.documents ?? []).filter(item => item.kind === 'camera-preference' && !item.deleted && item.document)
        .map(item => [item.id, { displayName: String(item.document?.displayName ?? ''), favorite: item.document?.favorite === true,
          group: String(item.document?.group ?? '') }])), legacy: true };
    }, controller.signal).then(result => {
      if (!current()) return;
      const next = new Map(result.values);
      preferenceDrafts.current.forEach((value, key) => {
        const fallback = { displayName: cameras.find(camera => camera.id === key)?.name ?? '', favorite: false, group: '' };
        const incoming = next.get(key) ?? fallback;
        const rebased = rebaseDraft(preferenceBaseline.current.get(key) ?? fallback, value, incoming);
        if (equivalent(rebased, incoming)) preferenceDrafts.current.delete(key); else preferenceDrafts.current.set(key, rebased);
        next.set(key, rebased);
      });
      preferenceBaseline.current = result.legacy ? new Map() : new Map(result.values);
      setPreferences(next); setPreferencesReady(true);
      if (result.legacy && result.values.size) setNotice('已读取本地旧显示偏好；逐台点击“同步显示偏好”后才保存到账号。');
    }).catch(() => { if (current()) { setPreferencesReady(false); setReadError(value => value || '账号显示偏好读取失败，暂不允许覆盖；请重试读取。'); } });
  };
  useEffect(() => {
    alive.current = true; void reload();
    return () => { alive.current = false; reading.current?.abort(); submission.current = null; };
  }, []);
  const changeAddress = (value: string) => {
    if (isMutating() || unconfirmed) return;
    cancelRead(); setAddress(value); setDetection(null); setPendingCredentials(null);
    setLoginUsername(''); setLoginPassword(''); setCredentialsRef(''); setCredentialsNotice(''); setError('');
    submission.current = null;
  };
  const acceptDetection = (result: CameraDetection & { credentialsExtracted?: boolean }, submittedAddress: string,
    credentials?: { username: string; password: string }) => {
    setDetection(result);
    if (!name) setName(result.adapter === 'onvif' ? 'ONVIF 摄像机' : result.address.split('/').filter(Boolean).at(-1) ?? '新摄像机');
    const pair = credentials ?? (result.credentialsExtracted ? extractUserinfo(submittedAddress) : null);
    if (pair) {
      setPendingCredentials(pair); setLoginUsername(pair.username); setLoginPassword('');
      setCredentialsNotice('已暂存当前设备凭据，保存时加密写入；更换地址将清除凭据。');
    } else if (result.probe === 'unreachable-or-auth-required' || result.probe === 'unreachable-or-unsupported') {
      setCredentialsNotice('若设备需要登录，请在下方输入账号密码后重试（不会写入链接）。');
    }
  };
  const detect = () => {
    const submittedAddress = address.trim(); setCredentialsNotice('');
    return run('自动检测', signal => detectCamera(submittedAddress, undefined, signal), result => acceptDetection(result, submittedAddress), false);
  };
  const finishCreation = (camera: CameraRecord) => {
    setCameras(current => [...current.filter(value => value.id !== camera.id), camera]);
    submission.current = null; setUnconfirmed(false); setAddress(''); setName(''); setCredentialsRef(''); setDetection(null);
    setLoginUsername(''); setLoginPassword(''); setPendingCredentials(null); setCredentialsNotice('');
    setNotice('设备已确认加入目录，可返回设备与来源配置和加入场景。'); void reload();
  };
  const add = () => {
    if (!detection) return;
    if (!submission.current) {
      const credentials = pendingCredentials ?? (loginUsername && loginPassword ? { username: loginUsername, password: loginPassword } : undefined);
      submission.current = { id: `camera-${crypto.randomUUID().replaceAll('-', '')}`, name: name.trim(), address: detection.address,
        adapter: detection.adapter, credentialsRef: credentialsRef.trim(), hardwareDecode: 'auto', profiles: detection.profiles,
        capabilities: detection.capabilities ?? { probe: detection.probe, contentType: detection.contentType ?? '' }, ...(credentials ?? {}) };
    }
    const submitted = submission.current;
    return run('保存设备', async signal => {
      try {
        const result = await createCamera(submitted, signal);
        if (result.id !== submitted.id) throw new Error('服务未确认本次提交的设备标识');
        return result;
      }
      catch (reason) {
        if (!(reason instanceof ControlApiError) || reason.status !== 409) throw reason;
        const record = (await fetchCameras(signal)).cameras.find(camera => camera.id === submitted.id);
        if (!record) throw reason;
        return record;
      }
    }, finishCreation, true, reason => {
      if (!(reason instanceof ControlApiError) || reason.status >= 500 || reason.status === 408 || reason.status === 409) setUnconfirmed(true);
      else { submission.current = null; setUnconfirmed(false); }
    });
  };
  const reconcileCreation = () => run('核对添加结果', signal => fetchCameras(signal), result => {
    setCameras(result.cameras);
    const record = result.cameras.find(camera => camera.id === submission.current?.id);
    if (record) finishCreation(record);
    else setNotice('目录中暂未找到这次提交。可继续提交同一设备，保留同一 ID；不自动创建第二条设备。');
  }, false);
  const rotateCredentials = (cameraId: string) => {
    if (!editUsername || !editPassword) { setError('请输入完整的账号与密码'); return; }
    return run('保存设备凭据', signal => updateCameraCredentials(cameraId, editUsername, editPassword, signal), () => {
      setEditingCredentials(null); setEditUsername(''); setEditPassword(''); setNotice('账号密码已加密保存并生效。'); void reload();
    });
  };
  const readOnvifProfiles = (credentials?: { username: string; password: string }) => {
    const submittedAddress = address.trim();
    return run('读取 ONVIF Profile', signal => probeOnvif(submittedAddress, credentialsRef.trim(), credentials, signal),
      result => acceptDetection(result, submittedAddress, credentials), false);
  };
  const discover = () => run('ONVIF 发现', signal => discoverOnvif(signal), result => setDiscovered(result.devices), false);
  const syncOnvif = (cameraId: string) => run('同步 ONVIF Profile', signal => syncOnvifCamera(cameraId, signal), () => { void reload(); });
  const qualifyDirect = (cameraId: string, profileId: string) => run('浏览器直连资格探测', signal => qualifyBrowserDirect(cameraId, profileId, signal), result => {
    setNotice(result.eligible ? '浏览器真直连 HTTPS、CORS 与媒体响应探测已通过。' : `该 Profile 必须使用 Gateway/Hybrid：${result.reason}`); void reload();
  });
  const remove = (camera: CameraRecord) => {
    if (busy || !window.confirm(`删除 ${camera.name}？引用此设备的场景与后续采集可能不可用，请先核对。`)) return;
    return run('删除设备', signal => deleteCamera(camera.id, signal), result => {
      if (!result.deleted || result.id !== camera.id) throw new Error('服务未确认删除结果');
      setCameras(current => current.filter(value => value.id !== camera.id));
      preferenceDrafts.current.delete(camera.id); policyDrafts.current.forEach((value, key) => { if (value.cameraId === camera.id) policyDrafts.current.delete(key); });
      setNotice('设备已从目录移除。'); void reload();
    });
  };
  const editPolicy = (cameraId: string, profileId: string, change: Partial<EditableAnalyticsPolicy>) => {
    const key = policyKey(cameraId, profileId), value = { ...(policies.get(key) ?? defaultPolicy(cameraId, profileId)), ...change };
    if (equivalent(value, policyBaseline.current.get(key) ?? defaultPolicy(cameraId, profileId))) policyDrafts.current.delete(key);
    else policyDrafts.current.set(key, value);
    setPolicies(current => new Map(current).set(key, value));
  };
  const savePolicySet = (values: EditableAnalyticsPolicy[]) => {
    if (!policiesReady) return;
    return run('保存分析策略', async signal => {
      try { return await patchV3AnalyticsPolicies(analyticsRevision, values, signal); }
      catch (reason) {
        if (!(reason instanceof ControlApiError) || ![404, 405].includes(reason.status)) throw reason;
        return { ...(await updateAnalyticsPolicies(values, signal)), revision: analyticsRevision };
      }
    }, saved => {
      setAnalyticsRevision(saved.revision);
      saved.policies.forEach(policy => { const key = policyKey(policy.cameraId, policy.profileId); policyBaseline.current.set(key, policy); policyDrafts.current.delete(key); });
      setPolicies(current => {
        const next = new Map(current);
        saved.policies.forEach(policy => next.set(policyKey(policy.cameraId, policy.profileId), policy)); return next;
      });
      setNotice(`已原子更新 ${saved.policies.length} 个 Profile 的分析策略。`); void reload();
    });
  };
  const setAllAnalytics = (enabled: boolean) => {
    const values = cameras.flatMap(camera => camera.profiles.map(profile => ({ ...(policies.get(policyKey(camera.id, profile.id)) ?? defaultPolicy(camera.id, profile.id)),
      motionEnabled: enabled, sceneChangeEnabled: enabled, personEnabled: enabled })));
    if (values.length) void savePolicySet(values);
  };
  const editPreference = (camera: CameraRecord, change: Partial<CameraPreference>) => {
    const value = { displayName: camera.name, favorite: false, group: '', ...preferences.get(camera.id), ...change };
    if (equivalent(value, preferenceBaseline.current.get(camera.id) ?? { displayName: camera.name, favorite: false, group: '' })) preferenceDrafts.current.delete(camera.id);
    else preferenceDrafts.current.set(camera.id, value);
    setPreferences(current => new Map(current).set(camera.id, value));
  };
  const savePreference = (camera: CameraRecord) => {
    if (!preferencesReady) return;
    const preference = preferences.get(camera.id) ?? { displayName: camera.name, favorite: false, group: '' };
    const baseline = preferenceBaseline.current.get(camera.id) ?? { displayName: camera.name, favorite: false, group: '' };
    return run('同步显示偏好', signal => patchCameraPreference(camera.id, preference, baseline, signal), saved => {
      preferenceBaseline.current = new Map(Object.entries(saved)); preferenceDrafts.current.delete(camera.id);
      const next = new Map(Object.entries(saved)); preferenceDrafts.current.forEach((value, key) => next.set(key, value)); setPreferences(next);
      setNotice('该设备的显示偏好已保存到当前账号；其他设备的草稿保持未保存。'); void reload();
    });
  };
  const leave = () => {
    if (window.dispatchEvent(new Event('webobs:before-navigate', { cancelable: true }))) onBack();
  };

  return <main className="registry-page">
    <header className="registry-header"><div><span className="eyebrow">Camera Source Adapter</span><h1>设备与码流</h1></div><button className="ghost-button" type="button" disabled={busy} onClick={leave}>返回设备与来源</button></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {readError && <div className="alert" role="alert">{readError}</div>}
    <div className="registry-actions"><button type="button" className="ghost-button" disabled={busy} onClick={() => void reload()}>重新读取设备与偏好</button>
      {busy && !mutating && <button type="button" onClick={cancelRead}>取消当前读取</button>}</div>
    {notice && <div className="notice" role="status">{notice}</div>}
    <Go2rtcStreams blocked={requestBusy} onBusyChange={setBridgeBusy} onImported={() => void reload()} />
    <section className="registry-add">
      <div><h2>添加设备</h2><p>可粘贴含账号密码的链接（会自动加密保存并脱敏显示），或在下方「设备登录」中单独填写。数据库与链接均不保存明文账密。</p></div>
      <p>HTTP 网页首页不是视频流。请使用完整的 RTSP、HLS 或 MJPEG 地址；go2rtc 转换后可填写 <code>rtsp://转换服务地址:18554/流名称</code>。</p>
      <label><span>地址</span><input value={address} maxLength={4096} disabled={mutating || unconfirmed} placeholder="rtsp://camera.example.invalid/stream 或 https://camera.example.invalid/live.m3u8" onChange={(event) => changeAddress(event.target.value)} /></label>
      <div className="registry-actions"><button className="primary-button" disabled={busy || unconfirmed || !address.trim()} type="button" onClick={() => void detect()}>自动检测</button><button className="ghost-button" disabled={busy || unconfirmed} type="button" onClick={() => void discover()}>ONVIF 发现</button></div>
      {unconfirmed && <div className="notice" role="status"><p>添加结果尚未确认，当前草稿与提交 ID 已保留在本页。先核对目录；继续提交时使用同一 ID，避免创建第二条设备。</p>
        <button type="button" disabled={busy} onClick={() => void reconcileCreation()}>核对添加结果</button>
        <button type="button" disabled={busy} onClick={() => void add()}>继续提交同一设备</button></div>}
      {credentialsNotice && <div className="notice" role="status">{credentialsNotice}</div>}
      {detection?.discoveryHint && <p role="status">{detection.discoveryHint}</p>}
      {detection?.adapter === 'mjpeg' && <p>当前 Web 监控的网关入口不直接拉取 HTTP MJPEG。可先用 go2rtc + FFmpeg 转为 H.264 RTSP，再检测并保存转换后的地址。</p>}
      {!pendingCredentials && <div className="device-login" aria-label="设备登录">
        <h3>设备登录（可选）</h3>
        <p>链接无法携带账密、或设备需要登录时，在此输入并保存（密文写入凭据库）。</p>
        <label><span>用户名</span><input autoComplete="username" disabled={busy || unconfirmed} value={loginUsername} maxLength={256} onChange={(event) => setLoginUsername(event.target.value)} /></label>
        <label><span>密码</span><input type="password" autoComplete="current-password" disabled={busy || unconfirmed} value={loginPassword} maxLength={512} onChange={(event) => setLoginPassword(event.target.value)} /></label>
        <button type="button" className="ghost-button" disabled={busy || unconfirmed || !loginUsername || !loginPassword} onClick={() => {
          setPendingCredentials({ username: loginUsername, password: loginPassword });
          setCredentialsNotice('账号密码已暂存，保存设备时加密写入。');
        }}>记住并加密保存</button>
      </div>}
      {pendingCredentials && <div className="notice" role="status">已暂存账号密码（显示为掩码），保存设备后仅以 Secret 引用绑定。</div>}
      {detection && <div className="detection-result"><strong>{detection.adapter.toUpperCase()} · {detection.probe}{detection.profileVersion ? ` · Profile ${detection.profileVersion}` : ''}</strong><span>{detection.profiles.length ? `${detection.profiles.length} 个码流 Profile` : '等待设备授权后读取 Profile'}</span><label><span>设备名称</span><input value={name} maxLength={128} disabled={busy || unconfirmed} onChange={(event) => setName(event.target.value)} /></label><label><span>凭据 Secret 引用（可选）</span><input value={credentialsRef} maxLength={256} disabled={busy || unconfirmed} placeholder="front-door" onChange={(event) => setCredentialsRef(event.target.value.replace(/[^a-zA-Z0-9._/-]/g, ''))} /></label><small>引用 /run/secrets/webobs-camera-credentials/&lt;名称&gt;.json；数据库不保存密码。</small>{detection.adapter === 'onvif' && <button className="ghost-button" disabled={busy || unconfirmed || !address.trim()} type="button" onClick={() => void readOnvifProfiles(pendingCredentials ?? (loginUsername && loginPassword ? { username: loginUsername, password: loginPassword } : undefined))}>读取 ONVIF Profile</button>}<button className="primary-button" disabled={busy || unconfirmed || !name.trim() || (detection.adapter === 'onvif' && detection.profiles.length === 0)} type="button" onClick={() => void add()}>保存到 Registry</button></div>}
      {discovered.length > 0 && <div className="discovery-list">{discovered.map((device) => <button type="button" key={device.address} disabled={mutating || unconfirmed} onClick={() => changeAddress(device.address)}><strong>{device.host}</strong><span>{safeAddressDisplay(device.address)}</span></button>)}</div>}
    </section>
    <section className="camera-list"><div className="section-title"><h2>Camera Registry</h2><span>{cameras.length} 台</span></div>
      <div className="analytics-batch"><span>当前列表分析开关</span><button className="ghost-button" disabled={busy || !policiesReady || !cameras.length} onClick={() => setAllAnalytics(true)}>Select All</button><button className="ghost-button" disabled={busy || !policiesReady || !cameras.length} onClick={() => setAllAnalytics(false)}>Unselect All</button><small>默认全部关闭；人物框为 v3-M2 预留接口。</small></div>
      {cameras.length === 0 ? <div className="registry-empty"><h3>尚未添加摄像机</h3><p>使用自动检测，或通过 ONVIF WS-Discovery 查找局域网设备。</p></div> : cameras.map((camera) => <article className="camera-card" key={camera.id}><div><span className="adapter-pill">{camera.adapter}</span><h3>{preferences.get(camera.id)?.displayName || camera.name}{preferences.get(camera.id)?.favorite ? ' ★' : ''}</h3><p>{camera.addressDisplay ?? safeAddressDisplay(camera.address, camera.credentialsConfigured)}</p><div className="camera-preference"><label>显示名称<input maxLength={128} disabled={busy || !preferencesReady} value={preferences.get(camera.id)?.displayName ?? camera.name} onChange={(event) => editPreference(camera, { displayName: event.target.value })} /></label><label>分组<input maxLength={64} disabled={busy || !preferencesReady} value={preferences.get(camera.id)?.group ?? ''} onChange={(event) => editPreference(camera, { group: event.target.value })} /></label><label><input type="checkbox" disabled={busy || !preferencesReady} checked={preferences.get(camera.id)?.favorite ?? false} onChange={(event) => editPreference(camera, { favorite: event.target.checked })} />收藏</label><button className="ghost-button" type="button" disabled={busy || !preferencesReady} onClick={() => void savePreference(camera)}>同步显示偏好</button><button className="ghost-button" type="button" disabled={busy} onClick={() => { if ((editUsername || editPassword) && !window.confirm("丢弃当前设备的账号密码草稿？")) return; setEditingCredentials(camera.id); setEditUsername(''); setEditPassword(''); }}>{camera.credentialsConfigured ? '修改账号密码' : '设置账号密码'}</button></div>
      {editingCredentials === camera.id && <div className="device-login" aria-label="修改账号密码">
        <label><span>用户名</span><input autoComplete="username" disabled={busy} value={editUsername} maxLength={256} onChange={(event) => setEditUsername(event.target.value)} /></label>
        <label><span>新密码</span><input type="password" autoComplete="new-password" disabled={busy} value={editPassword} maxLength={512} onChange={(event) => setEditPassword(event.target.value)} /></label>
        <div className="registry-actions"><button className="primary-button" disabled={busy || !editUsername || !editPassword} type="button" onClick={() => void rotateCredentials(camera.id)}>加密保存</button><button className="ghost-button" disabled={busy} type="button" onClick={() => { if ((editUsername || editPassword) && !window.confirm("丢弃当前设备的账号密码草稿？")) return; setEditingCredentials(null); setEditUsername(''); setEditPassword(''); }}>取消</button></div>
      </div>}
      </div><dl><div><dt>Profile</dt><dd>{camera.profiles.length}</dd></div><div><dt>硬解</dt><dd>{camera.hardwareDecode}</dd></div><div><dt>健康</dt><dd>{camera.health}</dd></div><div><dt>凭据</dt><dd>{camera.credentialsConfigured ? '已配置' : '无'}</dd></div></dl><div className="profile-list">{camera.profiles.map((profile) => {
        const proof = ((camera.capabilities.browserDirect as { profiles?: Record<string, { tlsVerified?: boolean; corsVerified?: boolean; reason?: string }> } | undefined)?.profiles?.[profile.id]);
        const policy = policies.get(policyKey(camera.id, profile.id)) ?? defaultPolicy(camera.id, profile.id);
        return <span key={profile.id}>{profile.role} · {profile.videoCodec || 'unknown'} {profile.width ? `${profile.width}×${profile.height}` : ''}
          {['whep', 'hls', 'mjpeg'].includes(camera.adapter) && <><small>{proof?.tlsVerified && proof?.corsVerified ? ' · Browser Direct 已验证' : proof ? ` · 未通过：${proof.reason}` : ' · 未探测'}</small><button className="ghost-button" disabled={busy} type="button" onClick={() => void qualifyDirect(camera.id, profile.id)}>验证浏览器真直连</button></>}
          <span className="analytics-policy" aria-label={`${camera.name} ${profile.name} 分析策略`}>
            <label><input type="checkbox" disabled={busy || !policiesReady} checked={policy.motionEnabled} onChange={(event) => editPolicy(camera.id, profile.id, { motionEnabled: event.target.checked })} />运动</label>
            <label><input type="checkbox" disabled={busy || !policiesReady} checked={policy.sceneChangeEnabled} onChange={(event) => editPolicy(camera.id, profile.id, { sceneChangeEnabled: event.target.checked })} />大范围变化</label>
            <label><input type="checkbox" disabled={busy || !policiesReady} checked={policy.personEnabled} onChange={(event) => editPolicy(camera.id, profile.id, { personEnabled: event.target.checked })} />人物框（v3-M2）</label>
            <label><input type="checkbox" disabled={busy || !policiesReady} checked={policy.allowEventPromotion} onChange={(event) => editPolicy(camera.id, profile.id, { allowEventPromotion: event.target.checked })} />事件提升到 M</label>
            {policy.allowEventPromotion && <><label>阈值<input type="number" min="0" max="1" step="0.05" disabled={busy || !policiesReady} value={policy.promotionThreshold} onChange={(event) => editPolicy(camera.id, profile.id, { promotionThreshold: Number(event.target.value) })} /></label><label>保持秒<input type="number" min="1" max="3600" disabled={busy || !policiesReady} value={policy.promotionHoldSeconds} onChange={(event) => editPolicy(camera.id, profile.id, { promotionHoldSeconds: Number(event.target.value) })} /></label><label>冷却秒<input type="number" min="0" max="86400" disabled={busy || !policiesReady} value={policy.promotionCooldownSeconds} onChange={(event) => editPolicy(camera.id, profile.id, { promotionCooldownSeconds: Number(event.target.value) })} /></label></>}
            <label title="低功耗模式下仍执行软件分析会增加设备功耗"><input type="checkbox" disabled={busy || !policiesReady} checked={policy.forceAnalyticsAlwaysOn} onChange={(event) => editPolicy(camera.id, profile.id, { forceAnalyticsAlwaysOn: event.target.checked })} />强制持续分析 ⚠</label>
            <button className="ghost-button" disabled={busy || !policiesReady} onClick={() => void savePolicySet([policy])}>保存策略</button>
          </span>
        </span>;
      })}</div><div className="camera-operations">{camera.adapter === 'onvif' && <><button className="ghost-button" disabled={busy} type="button" onClick={() => void syncOnvif(camera.id)}>同步 ONVIF Profile</button><DeviceControls camera={camera} busy={busy} fail={setError} /></>}<button className="danger-button" type="button" disabled={busy} onClick={() => void remove(camera)}>删除</button></div></article>)}
    </section>
    <footer className="adapter-footer">支持：{(['onvif','rtsp','mjpeg','snapshot','hls','http-flv','whep','srt','rtp','v4l2'] as CameraAdapter[]).join(' · ')}</footer>
  </main>;
}
